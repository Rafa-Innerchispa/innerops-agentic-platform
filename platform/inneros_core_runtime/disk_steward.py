"""AG-37 — Disk Steward: inventario multi-disco, alertas y movimientos con aprobación WhatsApp."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "ralfia_disk_steward_proposals"
STATE_DIR = Path(os.getenv("RALPHI_DATA_ROOT", "/home/rlopez/data")) / "ralfia"
STATE_FILE = STATE_DIR / "disk_steward_state.json"
LOG_FILE = STATE_DIR / "disk_steward.log"

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

BACKUP_SCAN_DIRS = [
    "/home/rlopez/data/backups",
    "/home/rlopez/data/backups/disaster_recovery",
    "/home/rlopez/data/backups/snapshots",
    "/home/rlopez/backups",
    "/mnt/datos_agentes/backups",
]

ARCHIVE_ROOT = Path(os.getenv("DISK_ARCHIVE_ROOT", "/home/rlopez/data/archive/disk_steward"))

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


def _generated_dir_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    scan_roots = [root for root in GENERATED_ARCHIVE_ROOTS if root.exists()]
    for root in scan_roots:
        if not root.is_dir() or root.is_symlink():
            continue
        children = list(root.iterdir()) if root.name in {"worktrees", "tmp", ".cache", ".npm"} else [root]
        for src in children:
            if src.is_symlink() or not src.exists():
                continue
            if not _is_generated_archive_candidate(src):
                continue
            age_hours = _path_age_hours(src)
            if age_hours < GENERATED_ARCHIVE_MIN_AGE_HOURS and not _is_relative_to(src, Path("/home/rlopez/inneros/inneros_core/var/local_execution/worktrees")):
                continue
            size_b = _path_size_bytes(src)
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
            candidates.append(
                {
                    "op": "archive_dir",
                    "src": str(src),
                    "dest": str(dest),
                    "size_gb": size_gb,
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


def scan_backups() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in BACKUP_SCAN_DIRS:
        p = Path(raw)
        if not p.exists():
            continue
        size_b = _dir_size_bytes(p, max_depth=3)
        items.append({"path": str(p), "size_gb": round(size_b / 1024**3, 2)})
    return sorted(items, key=lambda x: -x["size_gb"])


def _safe_move_candidates() -> list[dict[str, Any]]:
    """Candidatos a mover a disco de archivo (solo propuesta; requiere WhatsApp)."""
    candidates: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    patterns: list[tuple[Path, str, int]] = [
        (Path("/home/rlopez/data/backups/snapshots"), "snapshot_*.tar.gz", 4),
        (Path("/home/rlopez/data/backups/disaster_recovery"), "disaster_recovery_*.tar.gz", 14),
    ]
    for directory, glob_pat, min_days in patterns:
        if not directory.is_dir():
            continue
        for src in directory.glob(glob_pat):
            if not src.is_file():
                continue
            try:
                age_days = (now - datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)).days
            except OSError:
                continue
            if age_days < min_days:
                continue
            dest = ARCHIVE_ROOT / directory.name / src.name
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
    candidates.extend(_generated_dir_candidates())
    return sorted(candidates, key=lambda item: item.get("size_gb", 0), reverse=True)[:20]


def build_status(*, include_candidates: bool = True) -> dict[str, Any]:
    mounts = scan_mounts()
    backups = scan_backups()
    primary = [m for m in mounts if m.get("is_primary")]
    worst = max(primary, key=lambda m: m.get("use_pct", 0), default={})
    overall = "ok"
    if any(m.get("level") == "critical" for m in primary):
        overall = "critical"
    elif any(m.get("level") == "warning" for m in primary):
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
        "archive_root": str(ARCHIVE_ROOT),
    }
    if include_candidates:
        status["move_candidates"] = _safe_move_candidates()
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
    from raphiia_openai.notifications.evolution_client import send_whatsapp_interactive

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
    return send_whatsapp_interactive(
        text,
        [
            {"id": f"maint.confirm.{pid}", "label": "Sí, mover"},
            {"id": f"maint.cancel.{pid}", "label": "No mover"},
        ],
        footer="Disk Steward · AG-37",
        fallback_text=text + f"\n\nconfirmar movimiento {pid}",
    )


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
        try:
            from raphiia_openai.notifications.evolution_client import send_whatsapp

            send_whatsapp(msg)
        except Exception as exc:
            _log(f"alert_failed: {exc}")

        if auto_propose and status.get("move_candidates"):
            prop = create_move_proposal(reason=msg.replace("*", ""))
            if prop.get("ok"):
                result["proposal"] = prop["proposal"]
                result["notify"] = _notify_proposal(prop["proposal"])
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
