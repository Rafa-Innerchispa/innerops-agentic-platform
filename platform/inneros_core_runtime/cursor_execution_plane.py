"""Truthful Cursor execution classification for the IDE Task Bridge.

Cursor on the AMD headless host does not expose a supported headless CLI runner.
Interactive execution is available when an agent session (Cursor Composer / SSH)
is live and the MCP bridge is reachable.  This module separates delivery
(ide_inbox) from execution (claim → running → completed) without fabricating
headless capabilities.
"""
from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_STATE_KEY = "cursor_ide_session"
HEARTBEAT_TTL_SECONDS = 300
SESSION_FILE = Path.home() / ".inneros" / "agent_sessions" / "cursor.json"
MCP_HEALTH_URL = os.getenv("RALFIA_MCP_HEALTH_URL", "http://127.0.0.1:8102/health")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def probe_mcp_bridge(*, url: str = MCP_HEALTH_URL, timeout: float = 2.0) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(512).decode("utf-8", errors="replace")
            return {"ok": True, "reachable": True, "status_code": resp.status, "url": url, "body_preview": body[:120]}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reachable": True, "status_code": exc.code, "url": url, "error": type(exc).__name__}
    except Exception as exc:
        return {"ok": False, "reachable": False, "url": url, "error": type(exc).__name__}


def _sanitize_identity(raw: dict[str, Any] | None) -> dict[str, Any]:
    ident = dict(raw or {})
    nested = ident.get("identity")
    if isinstance(nested, dict) and nested.get("mailbox"):
        ident = nested
    if ident.get("error") and not ident.get("mailbox"):
        return {}
    keys = ("actor_id", "mailbox", "raw_agent", "display", "account", "host", "lane", "role")
    return {k: ident[k] for k in keys if ident.get(k) is not None}


def register_session_heartbeat(
    *,
    identity: dict[str, Any] | None = None,
    host: str = "",
    lane: str = "",
    role: str = "",
    pid: int | None = None,
    source: str = "cursor_coordination_boot",
) -> dict[str, Any]:
    """Persist liveness for the active Cursor agent session (Mongo + local file)."""
    ident = _sanitize_identity(identity)
    payload = {
        "agent": "cursor",
        "identity": ident,
        "host": host or ident.get("host") or socket.gethostname(),
        "lane": lane or ident.get("lane") or "",
        "role": role or ident.get("role") or "",
        "pid": int(pid or os.getpid()),
        "source": source,
        "last_seen_at": _now(),
        "transport": "interactive_agent_session",
    }
    file_ok = False
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(__import__("json").dumps(payload, indent=2) + "\n", encoding="utf-8")
        file_ok = True
    except OSError:
        pass
    mongo_ok = False
    try:
        from raphiia_openai import mongo_store

        mongo_store.upsert_coordination_state(key=SESSION_STATE_KEY, data=payload)
        mongo_ok = True
    except Exception:
        pass
    return {"ok": file_ok or mongo_ok, "file_ok": file_ok, "mongo_ok": mongo_ok, "session": payload}


def read_session_liveness(*, ttl_seconds: int = HEARTBEAT_TTL_SECONDS) -> dict[str, Any]:
    """Return whether an interactive Cursor session was seen recently."""
    session: dict[str, Any] | None = None
    source = ""
    try:
        from raphiia_openai import mongo_store

        row = mongo_store.get_coordination_state(SESSION_STATE_KEY)
        if row.get("ok"):
            session = dict((row.get("state") or {}))
            source = "mongo"
    except Exception:
        pass
    if not session and SESSION_FILE.is_file():
        try:
            session = __import__("json").loads(SESSION_FILE.read_text(encoding="utf-8"))
            source = "file"
        except Exception:
            session = None
    last_seen = _parse_ts((session or {}).get("last_seen_at"))
    age_seconds = None
    active = False
    if last_seen:
        age_seconds = max(0, int((datetime.now(timezone.utc) - last_seen).total_seconds()))
        active = age_seconds <= int(ttl_seconds)
    return {
        "ok": True,
        "active": active,
        "source": source or "none",
        "age_seconds": age_seconds,
        "ttl_seconds": int(ttl_seconds),
        "session": session or {},
    }


def classify_cursor_execution(*, cli_probe: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map live probes to headless_ready | partial | remote_inbox_only."""
    cli = dict(cli_probe or {})
    mcp = probe_mcp_bridge()
    session = read_session_liveness()
    headless_ready = bool(cli.get("installed") and cli.get("headless_supported") and cli.get("auth_ready"))
    mcp_ok = bool(mcp.get("reachable"))
    session_active = bool(session.get("active"))

    if headless_ready:
        classification = "headless_ready"
        provider_status = "ready"
        transport = "external_repair"
    elif mcp_ok and session_active:
        classification = "partial"
        provider_status = "interactive_session"
        transport = "ide_inbox+interactive_agent"
    elif mcp_ok:
        classification = "remote_inbox_only"
        provider_status = "remote_inbox"
        transport = "ide_inbox"
    else:
        classification = "remote_inbox_only"
        provider_status = "unavailable"
        transport = "ide_inbox"

    blockers: list[str] = []
    if not headless_ready:
        reason = str(cli.get("unavailable_reason") or "headless_runner_not_confirmed")
        if reason and reason not in blockers:
            blockers.append(reason)
    if not mcp_ok:
        blockers.append("mcp_bridge_unreachable")
    if mcp_ok and not session_active:
        blockers.append("no_active_cursor_agent_session")

    return {
        "ok": True,
        "execution_classification": classification,
        "provider_status": provider_status,
        "transport": transport,
        "headless_ready": headless_ready,
        "mcp_bridge": mcp,
        "interactive_session": session,
        "blockers": blockers,
        "control_path": (
            "ChatGPT/RalfIA: ide_dispatch_task → cursor/INBOX → poll_agent_inbox → "
            "ide_claim_task → ide_mark_task_running → ide_complete_task "
            "(requires active Cursor agent session on reachable host)"
        ),
        "cli_probe_summary": {
            "installed": bool(cli.get("installed")),
            "cli_path": cli.get("cli_path") or "",
            "version": cli.get("version") or "",
            "headless_supported": bool(cli.get("headless_supported")),
            "auth_ready": bool(cli.get("auth_ready")),
        },
    }


def enrich_cursor_provider_status(base: dict[str, Any]) -> dict[str, Any]:
    """Merge external_repair CLI probe with truthful Cursor execution classification."""
    classified = classify_cursor_execution(cli_probe=base)
    merged = {**base, **classified}
    merged["provider"] = "cursor"
    merged["provider_status"] = classified["provider_status"]
    merged["transport"] = classified["transport"]
    merged["headless_supported"] = classified["headless_ready"]
    session = dict((classified.get("interactive_session") or {}).get("session") or {})
    if session.get("identity") and isinstance(session["identity"], dict) and session["identity"].get("error"):
        session["identity"] = _sanitize_identity(session["identity"])
        merged["interactive_session"] = {**(classified.get("interactive_session") or {}), "session": session}
    merged["note"] = (
        "Cursor CLI on server is not a headless runner; "
        f"classification={classified['execution_classification']}. "
        + (classified["control_path"] if classified["execution_classification"] == "partial" else "Delivery-only until session is active.")
    )
    return merged
