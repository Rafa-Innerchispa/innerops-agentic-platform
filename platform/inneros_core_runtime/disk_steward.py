"""AG-37 — Disk Steward: inventario multi-disco, alertas y movimientos con aprobación WhatsApp."""

from __future__ import annotations

import json
import os
import secrets
import hashlib
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "ralfia_disk_steward_proposals"
MIGRATION_COLLECTION = "ralfia_disk_steward_migrations"
ALERT_COLLECTION = "ralfia_disk_steward_alerts"
STATE_DIR = Path(os.getenv("RALPHI_DATA_ROOT", "/home/rlopez/data")) / "ralfia"
STATE_FILE = STATE_DIR / "disk_steward_state.json"
LOG_FILE = STATE_DIR / "disk_steward.log"
POLICY_FILE = STATE_DIR / "disk_steward_backup_policy.json"


def _filesystem_for(path: Path) -> str:
    try:
        proc = subprocess.run(["findmnt", "-no", "SOURCE", "-T", str(path)], capture_output=True, text=True, timeout=5, check=False)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def _detect_archive_base() -> Path:
    """Pick a mounted data disk, never a plain directory on the root filesystem."""
    root_fs = _filesystem_for(Path("/"))
    candidates = [
        Path("/home/rlopez/data"),
        Path("/mnt/datos_agentes"),
        Path("/srv/backups"),
    ]
    best: tuple[int, Path] | None = None
    for candidate in candidates:
        if not candidate.exists():
            continue
        fs = _filesystem_for(candidate)
        if not fs or fs == root_fs:
            continue
        try:
            usage = shutil.disk_usage(candidate)
        except OSError:
            continue
        score = usage.total
        if best is None or score > best[0]:
            best = (score, candidate)
    if best:
        return best[1]
    return Path("/home/rlopez/data")

# Libre ≤20% en disco principal = CRÍTICO (requisito Rafael)
CRITICAL_FREE_PCT = float(os.getenv("DISK_CRITICAL_FREE_PCT", "20"))
WARN_FREE_PCT = float(os.getenv("DISK_WARN_FREE_PCT", "30"))

PRIMARY_MOUNTS = tuple(
    m.strip()
    for m in os.getenv(
        "DISK_PRIMARY_MOUNTS",
        "/,/home/rlopez/data,/home/rlopez/projects",
    ).split(",")
    if m.strip()
)

DEFAULT_ARCHIVE_BASE = Path(os.getenv("DISK_ARCHIVE_BASE") or str(_detect_archive_base()))

BACKUP_SCAN_DIRS = [
    "/home/rlopez/data/backups",
    "/home/rlopez/data/backups/disaster_recovery",
    "/home/rlopez/data/backups/snapshots",
    "/home/rlopez/backups",
    "/mnt/datos_agentes/backups",
    "/home/rlopez/inneros/inneros_core/backups",
    "/home/rlopez/inneros/inneros_core/platform/backups",
]

ARCHIVE_ROOT = Path(os.getenv("DISK_ARCHIVE_ROOT", str(DEFAULT_ARCHIVE_BASE / "backups/disk_steward/archive")))
MIGRATION_ROOT = Path(os.getenv("DISK_MIGRATION_ROOT", str(DEFAULT_ARCHIVE_BASE / "backups/off-root")))

ALLOWED_DEST_ROOTS = tuple(
    Path(p)
    for p in os.getenv(
        "DISK_ALLOWED_DEST_ROOTS",
        ",".join(
            [
                str(DEFAULT_ARCHIVE_BASE / "backups"),
                str(DEFAULT_ARCHIVE_BASE / "archive"),
                "/home/rlopez/data/archive",
                "/home/rlopez/data/backups",
                "/mnt/datos_agentes/backups",
            ]
        ),
    ).split(",")
    if p.strip()
)

# Origenes que NUNCA se mueven sin revision manual explicita.
# Algunos subdirectorios generados bajo InnerOS se permiten por allowlist exacta
# en _is_generated_archive_candidate().
PROTECTED_PREFIXES = (
    "/home/rlopez/inneros",
    "/home/rlopez/projects/inneros",
    "/home/rlopez/data/mongodb",
    "/home/rlopez/data/docker",
    "/var/lib/docker",
)

GENERATED_ARCHIVE_ROOTS = tuple(
    Path(p)
    for p in os.getenv(
        "DISK_GENERATED_ARCHIVE_ROOTS",
        "/home/rlopez/inneros/inneros_core/var/local_execution/worktrees,"
        "/home/rlopez/inneros/inneros_core/platform/worktrees,"
        "/home/rlopez/inneros/inneros_core/tmp,"
        "/home/rlopez/.cache,"
        "/home/rlopez/.npm",
    ).split(",")
    if p.strip()
)
GENERATED_ARCHIVE_MIN_GB = float(os.getenv("DISK_GENERATED_ARCHIVE_MIN_GB", "1.0"))
GENERATED_ARCHIVE_MIN_AGE_HOURS = float(os.getenv("DISK_GENERATED_ARCHIVE_MIN_AGE_HOURS", "2"))
GENERATED_ARCHIVE_SCAN_BUDGET_SEC = float(os.getenv("DISK_GENERATED_ARCHIVE_SCAN_BUDGET_SEC", "8"))
GENERATED_ARCHIVE_MAX_CHILDREN = int(os.getenv("DISK_GENERATED_ARCHIVE_MAX_CHILDREN", "80"))
BACKUP_SCAN_BUDGET_SEC = float(os.getenv("DISK_BACKUP_SCAN_BUDGET_SEC", "8"))
BACKUP_SIZE_TIMEOUT_SEC = float(os.getenv("DISK_BACKUP_SIZE_TIMEOUT_SEC", "3"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().strftime('%F %T')}] {msg}\n"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


def _dir_size_bytes(path: Path, *, max_depth: int = 2) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for child in path.iterdir():
            if child.is_symlink():
                continue
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
            elif max_depth > 0 and child.is_dir():
                total += _dir_size_bytes(child, max_depth=max_depth - 1)
    except OSError:
        pass
    return total


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _is_generated_archive_candidate(path: Path) -> bool:
    if path.is_symlink():
        return False
    return any(_is_relative_to(path, root) for root in GENERATED_ARCHIVE_ROOTS)


def _path_age_hours(path: Path) -> float:
    try:
        return max(0.0, (time.time() - path.stat().st_mtime) / 3600)
    except OSError:
        return 0.0


def _path_size_bytes(path: Path) -> int:
    try:
        proc = subprocess.run(["du", "-sb", str(path)], capture_output=True, text=True, timeout=20, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return int(proc.stdout.split()[0])
    except Exception:
        pass
    return _dir_size_bytes(path, max_depth=6)


def _quick_dir_size(path: Path, *, timeout_sec: float = BACKUP_SIZE_TIMEOUT_SEC) -> dict[str, Any]:
    if not path.exists():
        return {"bytes": 0, "status": "missing"}
    try:
        proc = subprocess.run(["du", "-sb", str(path)], capture_output=True, text=True, timeout=timeout_sec, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return {"bytes": int(proc.stdout.split()[0]), "status": "ok"}
        return {"bytes": 0, "status": "du_failed", "error": (proc.stderr or "").strip()[:200]}
    except subprocess.TimeoutExpired:
        return {"bytes": 0, "status": "timeout", "timeout_sec": timeout_sec}
    except Exception as exc:
        return {"bytes": 0, "status": "error", "error": str(exc)[:200]}


def _safe_resolve(raw: str) -> Path:
    if not raw or "\x00" in raw:
        raise ValueError("invalid_path")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("absolute_path_required")
    return path.resolve()


def _mount_source(path: Path) -> str:
    try:
        proc = subprocess.run(["findmnt", "-no", "SOURCE", "-T", str(path)], capture_output=True, text=True, timeout=10, check=False)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def _different_filesystem(src: Path, dest_root: Path) -> bool:
    src_fs = _mount_source(src)
    dest_fs = _mount_source(dest_root)
    return bool(src_fs and dest_fs and src_fs != dest_fs)


def _is_allowed_dest(path: Path) -> bool:
    return any(_is_relative_to(path, root) or path == root.resolve() for root in ALLOWED_DEST_ROOTS)


def _record_alert(kind: str, status: dict[str, Any], detail: dict[str, Any] | None = None) -> None:
    doc = {
        "schema": "ralfia.disk_steward.alert.v1",
        "kind": kind,
        "host": status.get("hostname") or os.uname().nodename,
        "overall": status.get("overall"),
        "primary_worst": status.get("primary_worst"),
        "pressured_mounts": status.get("pressured_mounts") or [],
        "detail": detail or {},
        "created_at": _now(),
    }
    try:
        mongo_store.get_db()[ALERT_COLLECTION].insert_one(doc)
    except Exception as exc:
        _log(f"alert_record_failed: {exc}")


def _is_allowed_source(path: Path) -> bool:
    if path.is_symlink():
        return False
    if _is_generated_archive_candidate(path):
        return True
    return any(_is_relative_to(path, Path(root)) for root in BACKUP_SCAN_DIRS)


def _reject_hot_or_protected_source(path: Path) -> str | None:
    if not path.exists():
        return "missing_source"
    if path.is_symlink():
        return "symlink_source_blocked"
    protected = any(str(path).startswith(prefix) for prefix in PROTECTED_PREFIXES)
    if protected and not _is_generated_archive_candidate(path):
        return "protected_source"
    if not _is_allowed_source(path):
        return "source_not_allowlisted"
    return None


def _checksum_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sample_checksums(path: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    if path.is_file():
        return [{"relative_path": path.name, "sha256": _checksum_file(path), "bytes": path.stat().st_size}]
    samples: list[dict[str, Any]] = []
    try:
        files = sorted([p for p in path.rglob("*") if p.is_file() and not p.is_symlink()], key=lambda p: str(p))[:limit]
    except OSError:
        files = []
    for item in files:
        try:
            samples.append({"relative_path": str(item.relative_to(path)), "sha256": _checksum_file(item), "bytes": item.stat().st_size})
        except OSError:
            continue
    return samples


def _plan_id(seed: str) -> str:
    return "dsm_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _copy_path(src: Path, dest: Path) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            return {"ok": False, "error": "destination_exists", "dest": str(dest)}
        shutil.copytree(src, dest, symlinks=False)
    elif src.is_file():
        if dest.exists():
            return {"ok": False, "error": "destination_exists", "dest": str(dest)}
        shutil.copy2(src, dest)
    else:
        return {"ok": False, "error": "unsupported_source_type", "src": str(src)}
    return {"ok": True, "src": str(src), "dest": str(dest)}


def disk_steward_inventory(*, include_candidates: bool = True) -> dict[str, Any]:
    status = build_status(include_candidates=include_candidates)
    return {
        "ok": True,
        "schema": "ralfia.disk_steward.inventory.v1",
        "status": status,
        "policy": disk_steward_backup_policy(),
        "safety": {
            "allowed_dest_roots": [str(p) for p in ALLOWED_DEST_ROOTS],
            "backup_scan_dirs": BACKUP_SCAN_DIRS,
            "protected_prefixes": PROTECTED_PREFIXES,
            "cleanup_requires_verified_true": True,
        },
    }


def disk_steward_backup_policy(preferred_backup_root: str | None = None, write: bool = False) -> dict[str, Any]:
    root = _safe_resolve(preferred_backup_root) if preferred_backup_root else MIGRATION_ROOT.resolve()
    if not _is_allowed_dest(root):
        return {"ok": False, "error": "destination_not_allowlisted", "destination": str(root), "allowed_dest_roots": [str(p) for p in ALLOWED_DEST_ROOTS]}
    policy = {
        "schema": "ralfia.disk_steward.backup_policy.v1",
        "preferred_backup_root": str(root),
        "allowed_dest_roots": [str(p) for p in ALLOWED_DEST_ROOTS],
        "warn_free_pct": WARN_FREE_PCT,
        "critical_free_pct": CRITICAL_FREE_PCT,
        "never_store_dr_backup_on_same_filesystem_as_source": True,
        "cleanup_requires_verified_true": True,
        "updated_at": _now(),
    }
    if write:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        POLICY_FILE.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    elif POLICY_FILE.exists():
        try:
            current = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
            policy = {**policy, **current, "policy_file": str(POLICY_FILE)}
        except Exception:
            policy["policy_file_error"] = "could_not_read_existing_policy"
    return {"ok": True, "policy": policy, "written": bool(write), "policy_file": str(POLICY_FILE)}


def disk_steward_plan_migration(
    source_path: str = "",
    destination_root: str = "",
    reason: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    status = build_status(include_candidates=True)
    candidates = status.get("move_candidates") or []
    if source_path:
        src = _safe_resolve(source_path)
        err = _reject_hot_or_protected_source(src)
        if err:
            return {"ok": False, "error": err, "source_path": str(src)}
        size_b = _path_size_bytes(src)
        selected = {"src": str(src), "size_gb": round(size_b / 1024**3, 2), "reason": reason or "owner_requested_migration"}
    elif candidates:
        selected = candidates[0]
        src = _safe_resolve(str(selected["src"]))
    else:
        return {"ok": False, "error": "no_move_candidates", "status": status}

    dest_root = _safe_resolve(destination_root) if destination_root else MIGRATION_ROOT.resolve()
    if not _is_allowed_dest(dest_root):
        return {"ok": False, "error": "destination_not_allowlisted", "destination_root": str(dest_root), "allowed_dest_roots": [str(p) for p in ALLOWED_DEST_ROOTS]}
    try:
        rel = src.relative_to(Path.home())
    except ValueError:
        rel = Path(src.name)
    dest = (dest_root / os.uname().nodename / rel).resolve()
    if _mount_source(src) and _mount_source(dest_root) and _mount_source(src) == _mount_source(dest_root):
        return {"ok": False, "error": "destination_same_filesystem_as_source", "source_mount": _mount_source(src), "destination_mount": _mount_source(dest_root)}
    pid = _plan_id(f"{src}:{dest}:{_path_size_bytes(src)}")
    plan = {
        "plan_id": pid,
        "schema": "ralfia.disk_steward.migration_plan.v1",
        "status": "planned",
        "host": os.uname().nodename,
        "source_path": str(src),
        "destination_path": str(dest),
        "destination_root": str(dest_root),
        "source_size_bytes": _path_size_bytes(src),
        "source_size_gb": round(_path_size_bytes(src) / 1024**3, 2),
        "source_mount": _mount_source(src),
        "destination_mount": _mount_source(dest_root),
        "reason": reason or selected.get("reason") or "disk_steward_candidate",
        "dry_run": bool(dry_run),
        "cleanup_allowed_after_verify": True,
        "created_at": _now(),
        "updated_at": _now(),
    }
    mongo_store.get_db()[MIGRATION_COLLECTION].update_one({"plan_id": pid}, {"$set": plan, "$setOnInsert": {"first_seen_at": plan["created_at"]}}, upsert=True)
    return {"ok": True, "plan": plan, "executed": False}


def disk_steward_execute_migration(plan_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    clean_id = (plan_id or "").strip()
    if not clean_id:
        return {"ok": False, "error": "plan_id_required"}
    db = mongo_store.get_db()
    plan = db[MIGRATION_COLLECTION].find_one({"plan_id": clean_id}, {"_id": 0})
    if not plan:
        return {"ok": False, "error": "plan_not_found", "plan_id": clean_id}
    src = _safe_resolve(str(plan["source_path"]))
    dest = _safe_resolve(str(plan["destination_path"]))
    err = _reject_hot_or_protected_source(src)
    if err:
        return {"ok": False, "error": err, "plan_id": clean_id}
    if not _is_allowed_dest(dest):
        return {"ok": False, "error": "destination_not_allowlisted", "destination_path": str(dest)}
    if dry_run:
        return {"ok": True, "plan_id": clean_id, "dry_run": True, "would_copy": {"src": str(src), "dest": str(dest)}, "executed": False}
    before = {"source_size_bytes": _path_size_bytes(src), "sample_checksums": _sample_checksums(src)}
    copied = _copy_path(src, dest)
    after = {"destination_size_bytes": _path_size_bytes(dest), "sample_checksums": _sample_checksums(dest)}
    verified = bool(copied.get("ok") and before["source_size_bytes"] == after["destination_size_bytes"])
    patch = {
        "status": "copied" if verified else "copy_failed",
        "executed_at": _now(),
        "updated_at": _now(),
        "copy_result": copied,
        "verify_after_copy": {"size_match": verified, **before, **after},
    }
    db[MIGRATION_COLLECTION].update_one({"plan_id": clean_id}, {"$set": patch})
    return {"ok": verified, "plan_id": clean_id, "dry_run": False, **patch}


def disk_steward_verify_migration(plan_id: str) -> dict[str, Any]:
    clean_id = (plan_id or "").strip()
    db = mongo_store.get_db()
    plan = db[MIGRATION_COLLECTION].find_one({"plan_id": clean_id}, {"_id": 0})
    if not plan:
        return {"ok": False, "error": "plan_not_found", "plan_id": clean_id}
    src = _safe_resolve(str(plan["source_path"]))
    dest = _safe_resolve(str(plan["destination_path"]))
    if not dest.exists():
        return {"ok": False, "error": "destination_missing", "plan_id": clean_id}
    src_size = _path_size_bytes(src) if src.exists() else int(plan.get("source_size_bytes") or 0)
    dest_size = _path_size_bytes(dest)
    src_samples = _sample_checksums(src) if src.exists() else []
    dest_samples = _sample_checksums(dest)
    ok = bool(src_size == dest_size and (not src_samples or src_samples == dest_samples))
    patch = {"status": "verified" if ok else "verify_failed", "verified_at": _now(), "updated_at": _now(), "verification": {"source_size_bytes": src_size, "destination_size_bytes": dest_size, "size_match": src_size == dest_size, "sample_checksums_match": (not src_samples or src_samples == dest_samples)}}
    db[MIGRATION_COLLECTION].update_one({"plan_id": clean_id}, {"$set": patch})
    return {"ok": ok, "plan_id": clean_id, **patch}


def disk_steward_cleanup_verified(plan_id: str, *, verified: bool = False) -> dict[str, Any]:
    if not verified:
        return {"ok": False, "error": "verified_true_required"}
    clean_id = (plan_id or "").strip()
    db = mongo_store.get_db()
    plan = db[MIGRATION_COLLECTION].find_one({"plan_id": clean_id}, {"_id": 0})
    if not plan:
        return {"ok": False, "error": "plan_not_found", "plan_id": clean_id}
    if plan.get("status") != "verified":
        return {"ok": False, "error": "plan_not_verified", "status": plan.get("status")}
    src = _safe_resolve(str(plan["source_path"]))
    dest = _safe_resolve(str(plan["destination_path"]))
    if not dest.exists():
        return {"ok": False, "error": "destination_missing"}
    err = _reject_hot_or_protected_source(src)
    if err and err != "missing_source":
        return {"ok": False, "error": err}
    if not src.exists():
        return {"ok": True, "idempotent": True, "plan_id": clean_id, "status": "cleaned", "source_path": str(src)}
    if src.is_dir():
        shutil.rmtree(src)
    else:
        src.unlink()
    patch = {"status": "cleaned", "cleaned_at": _now(), "updated_at": _now()}
    db[MIGRATION_COLLECTION].update_one({"plan_id": clean_id}, {"$set": patch})
    return {"ok": True, "plan_id": clean_id, **patch}


def _generated_dir_candidates(*, budget_sec: float = GENERATED_ARCHIVE_SCAN_BUDGET_SEC) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    started = time.monotonic()
    scan_roots = [root for root in GENERATED_ARCHIVE_ROOTS if root.exists()]
    for root in scan_roots:
        if time.monotonic() - started > budget_sec:
            break
        if not root.is_dir() or root.is_symlink():
            continue
        if root.name in {"worktrees", "tmp", ".cache", ".npm"}:
            try:
                children = list(root.iterdir())[:GENERATED_ARCHIVE_MAX_CHILDREN]
            except OSError:
                children = []
        else:
            children = [root]
        for src in children:
            if time.monotonic() - started > budget_sec:
                break
            if src.is_symlink() or not src.exists():
                continue
            if not _is_generated_archive_candidate(src):
                continue
            age_hours = _path_age_hours(src)
            if age_hours < GENERATED_ARCHIVE_MIN_AGE_HOURS and not _is_relative_to(src, Path("/home/rlopez/inneros/inneros_core/var/local_execution/worktrees")):
                continue
            size = _quick_dir_size(src)
            size_b = int(size.get("bytes") or 0)
            size_gb = round(size_b / 1024**3, 2)
            if size_gb < GENERATED_ARCHIVE_MIN_GB:
                continue
            key = str(src.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                rel = src.resolve().relative_to(Path.home())
            except ValueError:
                rel = Path(src.name)
            dest = ARCHIVE_ROOT / "generated" / rel
            if not _different_filesystem(src, ARCHIVE_ROOT):
                continue
            candidates.append(
                {
                    "op": "archive_dir",
                    "src": str(src),
                    "dest": str(dest),
                    "size_gb": size_gb,
                    "size_status": size.get("status", "unknown"),
                    "age_hours": round(age_hours, 1),
                    "reason": "generated/cache/worktree artifact on pressured root filesystem -> archive on data disk",
                }
            )
    return sorted(candidates, key=lambda item: item.get("size_gb", 0), reverse=True)[:20]


def scan_mounts() -> list[dict[str, Any]]:
    mounts: list[dict[str, Any]] = []
    try:
        out = subprocess.check_output(["df", "-P", "-B1"], text=True, timeout=30)
    except Exception as exc:
        return [{"error": str(exc)}]
    for line in out.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem, blocks, used, avail, cap_pct, mountpoint = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        if filesystem.startswith("tmpfs") or filesystem.startswith("overlay") or mountpoint.startswith("/snap"):
            continue
        total = int(blocks)
        used_b = int(used)
        avail_b = int(avail)
        free_pct = round(100 * avail_b / max(total, 1), 1)
        use_pct = int(cap_pct.rstrip("%"))
        level = "ok"
        if free_pct <= CRITICAL_FREE_PCT:
            level = "critical"
        elif free_pct <= WARN_FREE_PCT:
            level = "warning"
        mounts.append(
            {
                "filesystem": filesystem,
                "mount": mountpoint,
                "total_gb": round(total / 1024**3, 2),
                "used_gb": round(used_b / 1024**3, 2),
                "free_gb": round(avail_b / 1024**3, 2),
                "free_pct": free_pct,
                "use_pct": use_pct,
                "level": level,
                "is_primary": mountpoint in PRIMARY_MOUNTS,
            }
        )
    return sorted(mounts, key=lambda m: m.get("mount", ""))


def scan_backups(*, budget_sec: float = BACKUP_SCAN_BUDGET_SEC) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    started = time.monotonic()
    for raw in BACKUP_SCAN_DIRS:
        if time.monotonic() - started > budget_sec:
            items.append({"path": raw, "size_gb": 0.0, "size_status": "scan_budget_exhausted"})
            break
        p = Path(raw)
        if not p.exists():
            continue
        size = _quick_dir_size(p)
        items.append({"path": str(p), "size_gb": round(int(size.get("bytes") or 0) / 1024**3, 2), "size_status": size.get("status", "unknown")})
    return sorted(items, key=lambda x: -x["size_gb"])


def _safe_move_candidates(*, budget_sec: float = GENERATED_ARCHIVE_SCAN_BUDGET_SEC) -> list[dict[str, Any]]:
    """Candidatos a mover a disco de archivo (solo propuesta; requiere WhatsApp)."""
    candidates: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    started = time.monotonic()

    patterns: list[tuple[Path, str, int]] = [
        (Path("/home/rlopez/data/backups/snapshots"), "snapshot_*.tar.gz", 4),
        (Path("/home/rlopez/data/backups/disaster_recovery"), "disaster_recovery_*.tar.gz", 14),
    ]
    for directory, glob_pat, min_days in patterns:
        if not directory.is_dir():
            continue
        for src in directory.glob(glob_pat):
            if time.monotonic() - started > budget_sec:
                return sorted(candidates, key=lambda item: item.get("size_gb", 0), reverse=True)[:20]
            if not src.is_file():
                continue
            try:
                age_days = (now - datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)).days
            except OSError:
                continue
            if age_days < min_days:
                continue
            dest = ARCHIVE_ROOT / directory.name / src.name
            if not _different_filesystem(src, ARCHIVE_ROOT):
                continue
            candidates.append(
                {
                    "op": "mv",
                    "src": str(src),
                    "dest": str(dest),
                    "size_gb": round(src.stat().st_size / 1024**3, 2),
                    "age_days": age_days,
                    "reason": f"backup antiguo ({age_days}d) → archivo en data",
                }
            )
    remaining_budget = max(0.5, budget_sec - (time.monotonic() - started))
    candidates.extend(_generated_dir_candidates(budget_sec=remaining_budget))
    return sorted(candidates, key=lambda item: item.get("size_gb", 0), reverse=True)[:20]


def build_status(*, include_candidates: bool = True) -> dict[str, Any]:
    mounts = scan_mounts()
    backups = scan_backups()
    primary = [m for m in mounts if m.get("is_primary")]
    watched = primary or mounts
    worst = max(watched, key=lambda m: m.get("use_pct", 0), default={})
    pressured = [m for m in mounts if m.get("level") in ("warning", "critical")]
    overall = "ok"
    if any(m.get("level") == "critical" for m in mounts):
        overall = "critical"
    elif any(m.get("level") == "warning" for m in mounts):
        overall = "warning"

    status: dict[str, Any] = {
        "schema": "ralfia.disk_steward.v1",
        "timestamp": _now(),
        "hostname": os.uname().nodename,
        "overall": overall,
        "thresholds": {"critical_free_pct": CRITICAL_FREE_PCT, "warn_free_pct": WARN_FREE_PCT},
        "mounts": mounts,
        "backups": backups,
        "primary_worst": worst,
        "pressured_mounts": pressured,
        "archive_root": str(ARCHIVE_ROOT),
        "migration_root": str(MIGRATION_ROOT),
        "default_archive_base": str(DEFAULT_ARCHIVE_BASE),
    }
    if include_candidates:
        status["move_candidates"] = _safe_move_candidates()
        status["candidate_scan_budget_sec"] = GENERATED_ARCHIVE_SCAN_BUDGET_SEC
    try:
        from raphiia_openai.deferred_tasks_status import get_deferred_tasks_status

        status["deferred_tasks"] = get_deferred_tasks_status()
    except Exception:
        status["deferred_tasks"] = {"ok": False}
    return status


def _proposal_id() -> str:
    return f"dm_{secrets.token_hex(3)}"


def create_move_proposal(*, reason: str | None = None) -> dict[str, Any]:
    status = build_status(include_candidates=True)
    candidates = status.get("move_candidates") or []
    if not candidates:
        return {"ok": False, "error": "no_move_candidates", "status": status}

    pid = _proposal_id()
    doc = {
        "proposal_id": pid,
        "hostname": status["hostname"],
        "status": "pending_approval",
        "reason": reason or f"Espacio bajo en {status.get('primary_worst', {}).get('mount', '/')} "
        f"({status.get('primary_worst', {}).get('free_pct', '?')}% libre)",
        "actions": candidates,
        "freed_gb_estimate": round(sum(a.get("size_gb", 0) for a in candidates), 2),
        "created_at": _now(),
        "updated_at": _now(),
    }
    mongo_store.get_db()[COLLECTION].insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "proposal": doc}


def _notify_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai.notifications.evolution_client import send_alert_whatsapp, send_whatsapp_interactive

    pid = proposal["proposal_id"]
    lines = [
        f"*InnerOS · Disk Steward* ({proposal['hostname']})",
        proposal["reason"],
        f"Acciones propuestas: {len(proposal['actions'])} (~{proposal['freed_gb_estimate']} GB)",
        "",
    ]
    for i, act in enumerate(proposal["actions"][:3], 1):
        lines.append(f"{i}. `{Path(act['src']).name}` → archivo data ({act.get('size_gb', '?')} GB)")
    if len(proposal["actions"]) > 3:
        lines.append(f"… y {len(proposal['actions']) - 3} más")
    lines.append("")
    lines.append("¿Puedo mover estos archivos? Responde con botones o:")
    lines.append(f"`confirmar movimiento {pid}` / `cancelar movimiento {pid}`")

    text = "\n".join(lines)
    fallback_text = text + f"\n\nconfirmar movimiento {pid}"
    try:
        result = send_whatsapp_interactive(
            text,
            [
                {"id": f"maint.confirm.{pid}", "label": "Sí, mover"},
                {"id": f"maint.cancel.{pid}", "label": "No mover"},
            ],
            footer="Disk Steward · AG-37",
            fallback_text=fallback_text,
        )
    except Exception as exc:
        result = {"ok": False, "error": str(exc)[:300], "channel": "interactive"}
    if result.get("ok"):
        return result
    fallback = send_alert_whatsapp(fallback_text)
    fallback["interactive_failed"] = result
    return fallback


def run_check(*, auto_propose: bool = True) -> dict[str, Any]:
    status = build_status(include_candidates=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    host = status["hostname"]
    out_path = STATE_DIR / f"disk_steward_{host}.json"
    out_path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

    result: dict[str, Any] = {"ok": True, "status": status, "alerts": []}

    if status["overall"] in ("warning", "critical"):
        msg = (
            f"*DISK {'CRÍTICO' if status['overall'] == 'critical' else 'AVISO'}* · {host}\n"
            f"Disco: `{status.get('primary_worst', {}).get('mount', '/')}` "
            f"libre {status.get('primary_worst', {}).get('free_pct', '?')}% "
            f"({status.get('primary_worst', {}).get('free_gb', '?')} GB)\n"
            f"Umbral crítico: ≤{CRITICAL_FREE_PCT}% libre en discos principales."
        )
        result["alerts"].append(msg)
        _record_alert("disk_pressure", status, {"message": msg})
        try:
            from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

            notify = send_alert_whatsapp(msg)
            result["notify"] = notify
            if not notify.get("ok"):
                _record_alert("whatsapp_notify_failed", status, notify)
        except Exception as exc:
            _log(f"alert_failed: {exc}")
            _record_alert("whatsapp_notify_exception", status, {"error": str(exc)[:300]})

        if auto_propose and status.get("move_candidates"):
            prop = create_move_proposal(reason=msg.replace("*", ""))
            if prop.get("ok"):
                result["proposal"] = prop["proposal"]
                result["proposal_notify"] = _notify_proposal(prop["proposal"])
                if not result["proposal_notify"].get("ok"):
                    _record_alert("whatsapp_proposal_failed", status, result["proposal_notify"])
    else:
        _log(f"DISK_OK worst={status.get('primary_worst')}")

    return result


def confirm_move(sender: str, proposal_id: str) -> dict[str, Any]:
    from raphiia_openai import whatsapp_identity

    identity = whatsapp_identity.resolve_identity(sender)
    if not whatsapp_identity.is_owner(identity):
        return {"ok": False, "error": "unauthorized", "text": "Solo el owner puede aprobar movimientos de disco."}

    db = mongo_store.get_db()
    doc = db[COLLECTION].find_one({"proposal_id": proposal_id, "status": "pending_approval"}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "not_found", "text": f"No hay propuesta pendiente `{proposal_id}`."}

    executed: list[dict[str, Any]] = []
    for act in doc.get("actions") or []:
        src = Path(str(act.get("src", "")))
        dest = Path(str(act.get("dest", "")))
        if not src.exists():
            executed.append({"src": str(src), "ok": False, "error": "missing"})
            continue
        protected = any(str(src).startswith(p) for p in PROTECTED_PREFIXES)
        if protected and not _is_generated_archive_candidate(src):
            executed.append({"src": str(src), "ok": False, "error": "protected"})
            continue
        if src.is_dir() and not _is_generated_archive_candidate(src):
            executed.append({"src": str(src), "ok": False, "error": "dir_not_allowlisted"})
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            executed.append({"src": str(src), "dest": str(dest), "ok": True})
            _log(f"MOVED {src} -> {dest}")
        except Exception as exc:
            executed.append({"src": str(src), "ok": False, "error": str(exc)})

    db[COLLECTION].update_one(
        {"proposal_id": proposal_id},
        {"$set": {"status": "executed", "executed_at": _now(), "executed_by": sender, "results": executed}},
    )
    ok_n = sum(1 for e in executed if e.get("ok"))
    text = f"Movimiento `{proposal_id}` ejecutado: {ok_n}/{len(executed)} archivos movidos a archivo data."
    return {"ok": True, "executed": executed, "text": text}


def cancel_move(sender: str, proposal_id: str) -> dict[str, Any]:
    from raphiia_openai import whatsapp_identity

    identity = whatsapp_identity.resolve_identity(sender)
    if not whatsapp_identity.is_owner(identity):
        return {"ok": False, "error": "unauthorized"}
    db = mongo_store.get_db()
    r = db[COLLECTION].update_one(
        {"proposal_id": proposal_id, "status": "pending_approval"},
        {"$set": {"status": "cancelled", "cancelled_at": _now(), "cancelled_by": sender}},
    )
    if r.matched_count == 0:
        return {"ok": False, "text": f"No había propuesta pendiente `{proposal_id}`."}
    return {"ok": True, "text": f"Cancelado movimiento `{proposal_id}`. Nada se movió."}


def handle_button(button_id: str, sender: str) -> dict[str, Any] | None:
    import re

    m = re.fullmatch(r"maint\.confirm\.(dm_[a-f0-9]+)", button_id)
    if m:
        return confirm_move(sender, m.group(1))
    m = re.fullmatch(r"maint\.cancel\.(dm_[a-f0-9]+)", button_id)
    if m:
        return cancel_move(sender, m.group(1))
    return None
