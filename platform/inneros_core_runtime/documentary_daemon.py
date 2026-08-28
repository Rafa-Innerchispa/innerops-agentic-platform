"""Daemon ligero del Agente Documental."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mcp_diagnostics, mongo_store, ralfia_time

COORD_ROOT = Path(os.getenv("AI_COORDINATION_ROOT", "/home/rlopez/data/ai_coordination"))
SESSION_LOG = COORD_ROOT / "SESSION_LOG.md"
STATE_KEY = "documentary_sync"
POLL_SECONDS = int(os.getenv("DOCUMENTARY_POLL_SECONDS", "120"))
SESSION_LOG_MIN_INTERVAL_SEC = int(os.getenv("DOCUMENTARY_SESSION_LOG_MIN_INTERVAL", "300"))
MCP_STATUS_FILE = COORD_ROOT / "MCP_RUNTIME_STATUS.md"
TOOL_GUARD_FILE = COORD_ROOT / "MCP_TOOL_GUARD.md"

# Archivos que el propio daemon escribe → no deben re-disparar sync (anti feedback loop)
SELF_WRITTEN_PATHS = {
    "SESSION_LOG.md",
    "MCP_RUNTIME_STATUS.md",
    "MCP_TOOL_GUARD.md",
}

# SESSION_LOG NO se observa: el daemon lo escribe y generaba bucle cada POLL_SECONDS
WATCH_PATHS = [
    "MAPA_CENTRAL.md",
    "TASKS.md",
    "PROJECTS_REGISTRY.md",
    "MONGO_SCHEMA.md",
    "codex/OUTBOX.md",
    "codex/INBOX.md",
    "cursor/INBOX.md",
    "cursor/OUTBOX.md",
    "antigravity/INBOX.md",
    "antigravity/OUTBOX.md",
    "chatgpt/INBOX.md",
    "chatgpt/OUTBOX.md",
    "notion/INBOX.md",
    "HUB/ESTADO_VIVO.md",
    "HUB/CANAL_UNICO_COMUNICACION.md",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot() -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for rel in WATCH_PATHS:
        path = COORD_ROOT / rel
        if path.is_dir() or not path.exists():
            continue
        files[rel] = {
            "hash": _file_hash(path),
            "modified_at": ralfia_time.to_local_iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)),
            "size": path.stat().st_size,
        }
    return {"ts": _now_iso(), "files": files, "mcp_runtime": _runtime_snapshot()}


def _runtime_snapshot() -> dict[str, Any]:
    try:
        version = mcp_diagnostics.mcp_version()
        return {
            "server_version": version.get("server_version"),
            "catalog_version": version.get("catalog_version"),
            "manifest_hash": version.get("manifest_hash"),
            "tool_names_hash": version.get("tool_names_hash"),
            "tool_names": version.get("tool_names", []),
            "tool_count": version.get("catalog_tool_count"),
            "runtime_tool_count": version.get("runtime_tool_count"),
            "public_url": version.get("public_url"),
            "oauth_issuer": version.get("oauth_issuer"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _runtime_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    prev = (previous or {}).get("mcp_runtime") or {}
    curr = current.get("mcp_runtime") or {}
    keys = ("server_version", "catalog_version", "manifest_hash", "tool_names_hash", "tool_count", "runtime_tool_count", "public_url")
    return any(prev.get(k) != curr.get(k) for k in keys)


def _write_runtime_status(current: dict[str, Any]) -> None:
    runtime = current.get("mcp_runtime") or {}
    MCP_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        [
            "# MCP Runtime Status",
            "",
            f"- Updated: {current.get('ts')}",
            f"- Server: {runtime.get('server_version', 'unknown')}",
            f"- Catalog version: {runtime.get('catalog_version', 'unknown')}",
            f"- Manifest hash: {runtime.get('manifest_hash', 'unknown')}",
            f"- Tool names hash: {runtime.get('tool_names_hash', 'unknown')}",
            f"- Tool count: {runtime.get('tool_count', 'unknown')}",
            f"- Runtime tool count: {runtime.get('runtime_tool_count', 'unknown')}",
            f"- Public URL: {runtime.get('public_url', 'unknown')}",
            f"- OAuth issuer: {runtime.get('oauth_issuer', 'unknown')}",
            "",
            "This file is updated automatically by the Agente Documental whenever the live MCP snapshot changes.",
            "",
        ]
    )
    MCP_STATUS_FILE.write_text(body, encoding="utf-8")


def _runtime_status_needs_refresh(current: dict[str, Any]) -> bool:
    if not MCP_STATUS_FILE.exists():
        return True
    runtime = current.get("mcp_runtime") or {}
    try:
        existing = MCP_STATUS_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return True
    needles = [
        f"- Server: {runtime.get('server_version', 'unknown')}",
        f"- Catalog version: {runtime.get('catalog_version', 'unknown')}",
        f"- Manifest hash: {runtime.get('manifest_hash', 'unknown')}",
        f"- Tool names hash: {runtime.get('tool_names_hash', 'unknown')}",
        f"- Tool count: {runtime.get('tool_count', 'unknown')}",
        f"- Runtime tool count: {runtime.get('runtime_tool_count', 'unknown')}",
    ]
    return not all(needle in existing for needle in needles)


def _write_tool_guard(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    runtime = current.get("mcp_runtime") or {}
    prev_runtime = (previous or {}).get("mcp_runtime") or {}
    current_tools = sorted(runtime.get("tool_names") or [])
    previous_tools = sorted(prev_runtime.get("tool_names") or [])
    removed_tools = sorted(set(previous_tools) - set(current_tools))
    added_tools = sorted(set(current_tools) - set(previous_tools))
    status = "stable"
    if removed_tools:
        status = "tool_loss_detected"
    elif added_tools:
        status = "catalog_expanded"
    TOOL_GUARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    body_lines = [
        "# MCP Tool Guard",
        "",
        f"- Updated: {current.get('ts')}",
        f"- Status: {status}",
        f"- Server: {runtime.get('server_version', 'unknown')}",
        f"- Catalog version: {runtime.get('catalog_version', 'unknown')}",
        f"- Manifest hash: {runtime.get('manifest_hash', 'unknown')}",
        f"- Tool names hash: {runtime.get('tool_names_hash', 'unknown')}",
        f"- Current tool count: {len(current_tools)}",
        f"- Previous tool count: {len(previous_tools)}",
        f"- Removed tools: {', '.join(removed_tools) if removed_tools else 'none'}",
        f"- Added tools: {', '.join(added_tools) if added_tools else 'none'}",
        "",
        "This file is written by the Agente Documental to make tool removals explicit.",
    ]
    if removed_tools:
        body_lines.extend(
            [
                "",
                "ALERT: one or more tools disappeared relative to the last stored snapshot.",
                "Recreate or refresh the connector only after confirming whether the removals were intentional.",
            ]
        )
    TOOL_GUARD_FILE.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return {
        "status": status,
        "removed_tools": removed_tools,
        "added_tools": added_tools,
        "current_tool_count": len(current_tools),
        "previous_tool_count": len(previous_tools),
    }


def _append_session_log(summary: str, *, force: bool = False) -> bool:
    """Append a SESSION_LOG con debounce (anti ruido DOC-NOISE)."""
    if not SESSION_LOG.parent.exists():
        return False
    state = _load_state()
    last_ts = (state.get("last_session_log_at") or "") if isinstance(state, dict) else ""
    now = time.time()
    if not force and last_ts:
        try:
            last = datetime.fromisoformat(last_ts.replace("Z", "+00:00")).timestamp()
            if now - last < SESSION_LOG_MIN_INTERVAL_SEC:
                return False
        except Exception:
            pass
    with SESSION_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{ralfia_time.format_log()} | DOCUMENTAL | {summary}\n")
    # Persist debounce marker without full snapshot overwrite races
    try:
        prev = _load_state()
        prev["last_session_log_at"] = _now_iso()
        _save_state(prev)
    except Exception:
        pass
    return True


def _filter_meaningful_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ignora cambios de archivos que el propio documental genera."""
    out: list[dict[str, Any]] = []
    for change in changes:
        rel = change.get("path") or ""
        if rel in SELF_WRITTEN_PATHS:
            continue
        if rel.startswith("ChatGPT/"):
            # Espejo de chatgpt/ — dedupe: solo contar chatgpt/
            continue
        out.append(change)
    return out


def _load_state() -> dict[str, Any]:
    state = mongo_store.get_coordination_state(STATE_KEY)
    return state.get("state") if state.get("ok") else {"files": {}}


def _save_state(snapshot: dict[str, Any]) -> None:
    mongo_store.upsert_coordination_state(key=STATE_KEY, data=snapshot)


def _diff(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    prev_files = (previous or {}).get("files", {})
    curr_files = current.get("files", {})
    changes: list[dict[str, Any]] = []
    for rel, info in curr_files.items():
        prev = prev_files.get(rel)
        if not prev:
            changes.append({"path": rel, "before_hash": None, "after_hash": info["hash"], "change_type": "created"})
        elif prev.get("hash") != info.get("hash"):
            # Comparación semántica ligera: mismo tamaño + hash distinto raro; hash manda
            changes.append({"path": rel, "before_hash": prev.get("hash"), "after_hash": info.get("hash"), "change_type": "modified"})
    for rel, prev in prev_files.items():
        if rel not in curr_files:
            changes.append({"path": rel, "before_hash": prev.get("hash"), "after_hash": None, "change_type": "deleted"})
    return changes


def _summarize_change(rel: str, change_type: str) -> str:
    if rel == "TASKS.md":
        return "TASKS updated"
    if rel == "MAPA_CENTRAL.md":
        return "MAPA_CENTRAL updated"
    if rel.startswith("codex/"):
        return f"Codex note changed: {rel}"
    if rel.startswith("cursor/"):
        return f"Cursor note changed: {rel}"
    if rel.startswith("antigravity/"):
        return f"Antigravity note changed: {rel}"
    if rel.startswith("chatgpt/"):
        return f"chatgpt note changed: {rel}"
    if rel.startswith("notion/"):
        return f"Notion note changed: {rel}"
    if rel.startswith("HUB"):
        return "HUB updated"
    return f"{change_type}: {rel}"


def run_once() -> int:
    previous = _load_state()
    current = _snapshot()
    raw_changes = _diff(previous, current)
    changes = _filter_meaningful_changes(raw_changes)
    runtime_changed = _runtime_changed(previous, current)
    needs_runtime_refresh = runtime_changed or _runtime_status_needs_refresh(current)
    tool_guard = _write_tool_guard(current, previous) if needs_runtime_refresh else None
    if needs_runtime_refresh:
        _write_runtime_status(current)
        runtime = current.get("mcp_runtime") or {}
        # Solo loguear si el runtime cambió de verdad (no refresh de archivo vacío)
        if runtime_changed:
            mongo_store.log_coordination(
                agent="DOCUMENTAL",
                summary=f"MCP runtime changed: {runtime.get('server_version', 'unknown')} / {runtime.get('catalog_version', 'unknown')}",
                event="mcp_runtime_change",
                project="coordination",
                tool_used="agent_documental_daemon",
                metadata=runtime,
            )
            if tool_guard and tool_guard.get("removed_tools"):
                mongo_store.log_coordination(
                    agent="DOCUMENTAL",
                    summary=f"MCP tool loss detected: {', '.join(tool_guard['removed_tools'])}",
                    event="mcp_tool_loss",
                    project="coordination",
                    tool_used="agent_documental_daemon",
                    metadata={
                        "removed_tools": tool_guard["removed_tools"],
                        "added_tools": tool_guard["added_tools"],
                        "current_tool_count": tool_guard["current_tool_count"],
                        "previous_tool_count": tool_guard["previous_tool_count"],
                    },
                )
                mongo_store.register_change(
                    agent="DOCUMENTAL",
                    project="coordination",
                    path="MCP_TOOL_GUARD.md",
                    summary=f"MCP tool loss detected: {', '.join(tool_guard['removed_tools'])}",
                    before_hash=(previous or {}).get("mcp_runtime", {}).get("tool_names_hash"),
                    after_hash=runtime.get("tool_names_hash"),
                    service="agent_documental_daemon",
                    change_type="documentation_modified",
                    metadata={"source": "tool_guard", **tool_guard, **runtime},
                )
            mongo_store.register_change(
                agent="DOCUMENTAL",
                project="coordination",
                path="MCP_RUNTIME_STATUS.md",
                summary=f"MCP runtime snapshot updated: {runtime.get('server_version', 'unknown')}",
                before_hash=(previous or {}).get("mcp_runtime", {}).get("manifest_hash"),
                after_hash=runtime.get("manifest_hash"),
                service="agent_documental_daemon",
                change_type="documentation_modified",
                metadata={"source": "runtime_snapshot", **runtime},
            )
            _append_session_log(
                f"MCP runtime updated to {runtime.get('server_version', 'unknown')} / catalog {runtime.get('catalog_version', 'unknown')}",
                force=True,
            )
            if tool_guard and tool_guard.get("removed_tools"):
                _append_session_log(
                    f"MCP tool guard: {tool_guard['status']} (removed={len(tool_guard['removed_tools'])})",
                    force=True,
                )
    if not changes:
        # Conservar debounce marker
        if isinstance(previous, dict) and previous.get("last_session_log_at"):
            current["last_session_log_at"] = previous["last_session_log_at"]
        _save_state(current)
        return 0

    batch_summary = f"{len(changes)} change(s) synced"
    mongo_store.log_coordination(
        agent="DOCUMENTAL",
        summary=batch_summary,
        event="documentation_sync",
        project="coordination",
        tool_used="agent_documental_daemon",
        metadata={"changes": changes[:20], "raw_ignored": len(raw_changes) - len(changes)},
    )
    _append_session_log(batch_summary)

    for change in changes:
        mongo_store.register_change(
            agent="DOCUMENTAL",
            project="coordination",
            path=change["path"],
            summary=_summarize_change(change["path"], change["change_type"]),
            before_hash=change["before_hash"],
            after_hash=change["after_hash"],
            service="agent_documental_daemon",
            change_type=f"documentation_{change['change_type']}",
            metadata={"source": "polling"},
        )

    if isinstance(previous, dict) and previous.get("last_session_log_at"):
        # refresh after append
        refreshed = _load_state()
        current["last_session_log_at"] = refreshed.get("last_session_log_at") or previous.get("last_session_log_at")
    _save_state(current)
    return len(changes)


def main() -> None:
    COORD_ROOT.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            run_once()
        except Exception as exc:
            mongo_store.log_mcp_error(
                error_type="documentary_daemon_error",
                tool="agent_documental_daemon",
                message=str(exc),
                resolved=False,
                metadata={"root": str(COORD_ROOT)},
            )
        time.sleep(POLL_SECONDS)
