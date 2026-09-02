"""Trusted local filesystem plane for Ralphi IA owner operations.

This is intentionally broader than the repo-scoped Local Execution Plane, but
still avoids irreversible destruction and sensitive paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPABILITY = "local_filesystem_plane"
DEFAULT_ROOTS = [
    "/home/rlopez",
    "/tmp",
]
MAX_READ_BYTES = int(os.getenv("RALFIA_FS_MAX_READ_BYTES", "200000"))
MAX_WRITE_BYTES = int(os.getenv("RALFIA_FS_MAX_WRITE_BYTES", "2000000"))
MAX_LIST_ITEMS = int(os.getenv("RALFIA_FS_MAX_LIST_ITEMS", "500"))
QUARANTINE_ROOT = Path(os.getenv("RALFIA_FS_QUARANTINE_ROOT", "/home/rlopez/inneros/inneros_core/var/quarantine/local_fs"))

DENIED_PARTS = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".docker",
    ".kube",
    ".local/share/keyrings",
    ".config/rclone",
    ".config/gcloud",
    ".config/gh",
    ".env",
    "id_rsa",
    "id_ed25519",
    "secrets",
    "secret",
    "credentials",
    "certs",
    "private_keys",
}
DENIED_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
    ".sqlite",
    ".db",
    ".dump",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|private[_-]?key)\s*[:=]\s*[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[opsu]_[A-Za-z0-9_]{20,}"),
]
SOURCE_CODE_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
SOURCE_CODE_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|private[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[opsu]_[A-Za-z0-9_]{20,}"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_roots() -> list[Path]:
    raw = os.getenv("RALFIA_FS_ROOTS_JSON", "").strip()
    roots = DEFAULT_ROOTS
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                roots = parsed
        except json.JSONDecodeError:
            pass
    return [Path(r).expanduser().resolve() for r in roots]


def _require_metadata(actor: str, task_id: str, correlation_id: str) -> None:
    if not (actor or "").strip():
        raise ValueError("actor_required")
    if not (task_id or "").strip():
        raise ValueError("task_id_required")
    if not (correlation_id or "").strip():
        raise ValueError("correlation_id_required")


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_resolve(path: str | Path) -> Path:
    value = str(path or "").strip()
    if not value:
        raise ValueError("path_required")
    target = Path(value).expanduser()
    if not target.is_absolute():
        target = Path("/home/rlopez") / target
    resolved = target.resolve(strict=False)
    roots = _load_roots()
    if not any(_is_under(resolved, root) for root in roots):
        raise PermissionError("path_outside_trusted_roots")
    _deny_sensitive(resolved)
    return resolved


def _deny_sensitive(path: Path) -> None:
    text = str(path)
    lowered = text.lower()
    parts = [p.lower() for p in path.parts]
    joined = "/".join(parts)
    for denied in DENIED_PARTS:
        d = denied.lower()
        if "/" in d:
            if d in joined:
                raise PermissionError("sensitive_path_denied")
        elif d in parts:
            raise PermissionError("sensitive_path_denied")
    if path.suffix.lower() in DENIED_SUFFIXES:
        raise PermissionError("sensitive_file_type_denied")
    if "/.git/" in lowered and not lowered.endswith("/.gitignore"):
        raise PermissionError("git_internal_path_denied")


def _check_content(content: str, *, source_code: bool = False) -> None:
    data = (content or "").encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise ValueError("content_too_large")
    patterns = SOURCE_CODE_SECRET_PATTERNS if source_code else SECRET_PATTERNS
    for pattern in patterns:
        if pattern.search(content or ""):
            raise PermissionError("secret_content_denied")


def _audit(action: str, actor: str, target: Path, result: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
    if os.getenv("RALFIA_FS_DISABLE_AUDIT", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        from raphiia_openai import mongo_store

        mongo_store.log_coordination(
            agent=(actor or "SYSTEM").upper(),
            event="local_filesystem",
            summary=f"{action}: {target}",
            project="ralfia-local-filesystem-plane",
            tool_used=f"{CAPABILITY}.{action}",
            metadata={
                "capability": CAPABILITY,
                "action": action,
                "target": str(target),
                "result": {k: v for k, v in result.items() if k not in {"content"}},
                "extra": extra or {},
                "at": _now_iso(),
            },
        )
    except Exception:
        pass


def policy() -> dict[str, Any]:
    return {
        "ok": True,
        "capability": CAPABILITY,
        "trusted_roots": [str(p) for p in _load_roots()],
        "writes": "allowed_under_trusted_roots",
        "delete": "not_available_use_quarantine",
        "sudo": "denied",
        "sensitive_paths_denied": sorted(DENIED_PARTS),
        "sensitive_suffixes_denied": sorted(DENIED_SUFFIXES),
        "max_read_bytes": MAX_READ_BYTES,
        "max_write_bytes": MAX_WRITE_BYTES,
        "quarantine_root": str(QUARANTINE_ROOT),
    }


def list_path(path: str, limit: int = 100) -> dict[str, Any]:
    try:
        target = _safe_resolve(path)
        if not target.exists():
            return {"ok": False, "error": "path_missing", "path": str(target)}
        if target.is_file():
            st = target.stat()
            return {"ok": True, "path": str(target), "type": "file", "size": st.st_size, "mtime": st.st_mtime}
        max_items = max(1, min(int(limit or 100), MAX_LIST_ITEMS))
        items = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:max_items]:
            try:
                st = child.stat()
                items.append({"name": child.name, "path": str(child), "type": "dir" if child.is_dir() else "file", "size": st.st_size, "mtime": st.st_mtime})
            except Exception as exc:
                items.append({"name": child.name, "path": str(child), "error": str(exc)})
        return {"ok": True, "path": str(target), "type": "dir", "items": items, "truncated": len(items) >= max_items}
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    try:
        target = _safe_resolve(path)
        if not target.is_file():
            return {"ok": False, "error": "file_missing", "path": str(target)}
        limit = max(1, min(int(max_bytes or MAX_READ_BYTES), MAX_READ_BYTES))
        raw = target.read_bytes()
        truncated = len(raw) > limit
        return {
            "ok": True,
            "path": str(target),
            "bytes": len(raw),
            "truncated": truncated,
            "content": raw[:limit].decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def mkdir(path: str, actor: str, task_id: str, correlation_id: str) -> dict[str, Any]:
    try:
        _require_metadata(actor, task_id, correlation_id)
        target = _safe_resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        result = {"ok": True, "path": str(target), "exists": target.is_dir()}
        _audit("mkdir", actor, target, result, {"task_id": task_id, "correlation_id": correlation_id})
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def write_file(path: str, content: str, actor: str, task_id: str, correlation_id: str, mode: str = "replace") -> dict[str, Any]:
    try:
        _require_metadata(actor, task_id, correlation_id)
        target = _safe_resolve(path)
        _check_content(content, source_code=target.suffix.lower() in SOURCE_CODE_SUFFIXES)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        if mode not in {"replace", "create", "append"}:
            raise ValueError("invalid_write_mode")
        if mode == "create" and existed:
            return {"ok": False, "error": "file_exists", "path": str(target)}
        if mode == "append":
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content or "")
        else:
            target.write_text(content or "", encoding="utf-8")
        digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]
        result = {"ok": True, "path": str(target), "mode": mode, "existed": existed, "bytes": len((content or "").encode("utf-8")), "content_hash": digest}
        _audit("write_file", actor, target, result, {"task_id": task_id, "correlation_id": correlation_id})
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def move_to_quarantine(path: str, actor: str, task_id: str, correlation_id: str, reason: str = "") -> dict[str, Any]:
    try:
        _require_metadata(actor, task_id, correlation_id)
        target = _safe_resolve(path)
        if not target.exists():
            return {"ok": False, "error": "path_missing", "path": str(target)}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest_dir = QUARANTINE_ROOT / stamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / target.name
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{target.name}.{counter}"
            counter += 1
        shutil.move(str(target), str(dest))
        result = {"ok": True, "original_path": str(target), "quarantine_path": str(dest), "rollback": f"mv {dest} {target}"}
        _audit("move_to_quarantine", actor, target, result, {"task_id": task_id, "correlation_id": correlation_id, "reason": reason})
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}


def git_init_repo(path: str, actor: str, task_id: str, correlation_id: str, default_branch: str = "main") -> dict[str, Any]:
    try:
        _require_metadata(actor, task_id, correlation_id)
        target = _safe_resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        branch = (default_branch or "main").strip()
        if not re.match(r"^[A-Za-z0-9._/-]+$", branch):
            raise ValueError("invalid_branch_name")
        if (target / ".git").exists():
            head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(target), capture_output=True, text=True, timeout=20, check=False)
            result = {"ok": True, "idempotent": True, "path": str(target), "head": (head.stdout or "").strip()}
            _audit("git_init_repo", actor, target, result, {"task_id": task_id, "correlation_id": correlation_id})
            return result
        init = subprocess.run(["git", "init", "-b", branch], cwd=str(target), capture_output=True, text=True, timeout=60, check=False)
        result = {"ok": init.returncode == 0, "path": str(target), "branch": branch, "stdout": init.stdout[-2000:], "stderr": init.stderr[-2000:]}
        _audit("git_init_repo", actor, target, result, {"task_id": task_id, "correlation_id": correlation_id})
        return result
    except Exception as exc:
        return {"ok": False, "capability": CAPABILITY, "error": str(exc)}
