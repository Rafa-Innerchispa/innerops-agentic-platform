"""InnerOS restore points: auditable release/config checkpoints, not backups.

Restore points capture bounded configuration/source snapshots plus hashes so a
human can inspect and approve rollback. They deliberately do not claim to be a
full backup, filesystem snapshot, or disaster-recovery copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_RESTORE_ROOT = Path(os.getenv("INNEROS_RESTORE_POINTS_ROOT", "/home/rlopez/data/inneros_restore_points"))
DEFAULT_MAX_FILE_BYTES = int(os.getenv("INNEROS_RESTORE_POINT_MAX_FILE_BYTES", str(2 * 1024 * 1024)))
DEFAULT_MAX_TOTAL_BYTES = int(os.getenv("INNEROS_RESTORE_POINT_MAX_TOTAL_BYTES", str(100 * 1024 * 1024)))

EXCLUDED_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
EXCLUDED_PARTS = {"var/local_execution", "var/local_models", "data/docker", "data/mongodb"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", label.strip().lower()).strip("-._")
    return slug[:64] or "restore-point"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_NAMES:
        return True
    text = "/".join(path.parts)
    return any(fragment in text for fragment in EXCLUDED_PARTS)


def _iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if not _is_excluded(root):
                yield root
            continue
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_NAMES and not _is_excluded(current_path / d)]
            if _is_excluded(current_path):
                continue
            for name in files:
                file_path = current_path / name
                if not _is_excluded(file_path) and not file_path.is_symlink():
                    yield file_path


def _safe_rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        drive = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(path.anchor).strip("/\\:")) or "abs"
        return f"_external/{drive}/{str(path.resolve()).lstrip('/')}"


def create_restore_point(
    label: str,
    *,
    roots: list[str | Path],
    output_root: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """Create a bounded restore point and return its manifest."""

    out_base = Path(output_root) if output_root else DEFAULT_RESTORE_ROOT
    created_at = _now()
    point_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_slug(label)}"
    point_dir = out_base / point_id
    files_dir = point_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=False)

    root_paths = [Path(p).expanduser() for p in roots]
    existing_roots = [str(p.resolve()) for p in root_paths if p.exists()]
    common_base = Path(os.path.commonpath(existing_roots or [str(Path.cwd())]))
    copied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    total_bytes = 0

    for file_path in sorted(set(_iter_files(root_paths)), key=lambda p: str(p)):
        try:
            stat = file_path.stat()
        except OSError as exc:
            skipped.append({"path": str(file_path), "reason": f"stat_failed:{exc}"})
            continue
        rel = _safe_rel(file_path, common_base)
        entry = {"path": str(file_path), "relative_path": rel, "size_bytes": stat.st_size}
        if stat.st_size > max_file_bytes:
            entry["reason"] = "file_too_large"
            try:
                entry["sha256"] = _sha256(file_path)
            except OSError:
                pass
            skipped.append(entry)
            continue
        if total_bytes + stat.st_size > max_total_bytes:
            entry["reason"] = "restore_point_budget_exceeded"
            skipped.append(entry)
            continue
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        sha = _sha256(dest)
        total_bytes += stat.st_size
        copied.append({**entry, "sha256": sha, "stored_as": str(dest.relative_to(point_dir))})

    manifest = {
        "schema": "inneros.restore_point.v1",
        "point_id": point_id,
        "label": label,
        "created_at": created_at,
        "type": "release_config_checkpoint_not_backup",
        "restore_requires_explicit_owner_approval": True,
        "root_paths": [str(p) for p in root_paths],
        "common_base": str(common_base),
        "limits": {"max_file_bytes": max_file_bytes, "max_total_bytes": max_total_bytes},
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "copied_bytes": total_bytes,
        "files": copied,
        "skipped": skipped,
        "metadata": metadata or {},
    }
    (point_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "restore_point": manifest, "path": str(point_dir)}


def list_restore_points(*, output_root: str | Path | None = None, limit: int = 50) -> dict[str, Any]:
    root = Path(output_root) if output_root else DEFAULT_RESTORE_ROOT
    points: list[dict[str, Any]] = []
    if not root.exists():
        return {"ok": True, "restore_points": []}
    for manifest_path in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        points.append(
            {
                "point_id": manifest.get("point_id"),
                "label": manifest.get("label"),
                "created_at": manifest.get("created_at"),
                "copied_count": manifest.get("copied_count"),
                "skipped_count": manifest.get("skipped_count"),
                "path": str(manifest_path.parent),
            }
        )
        if len(points) >= limit:
            break
    return {"ok": True, "restore_points": points}


def build_restore_plan(point_id: str, *, output_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(output_root) if output_root else DEFAULT_RESTORE_ROOT
    manifest_path = root / point_id / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "error": "restore_point_not_found", "point_id": point_id}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actions = []
    for item in manifest.get("files") or []:
        actions.append(
            {
                "op": "restore_file_after_owner_approval",
                "source": str(root / point_id / item["stored_as"]),
                "dest": item["path"],
                "sha256": item["sha256"],
                "requires_approval": True,
            }
        )
    return {
        "ok": True,
        "point_id": point_id,
        "action_count": len(actions),
        "actions": actions,
        "execute_supported": False,
        "reason": "restore execution is intentionally separated behind an owner approval gate",
    }
