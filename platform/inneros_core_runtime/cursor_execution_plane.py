"""Truthful Cursor execution classification for the IDE Task Bridge.

Cursor has independent execution paths: a real IDE session, the Cursor
headless CLI, or the authenticated local Cursor SDK already used by the
background worker.  Inbox ACK alone is never an executable session.
This module separates delivery from execution without fabricating liveness.
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
CONSUMER_STATE_KEY = "cursor_inbox_consumer_liveness"
HEARTBEAT_TTL_SECONDS = 300
SESSION_FILE = Path.home() / ".inneros" / "agent_sessions" / "cursor.json"
CONSUMER_FILE = Path.home() / ".inneros" / "agent_sessions" / "cursor_inbox_consumer.json"
MCP_HEALTH_URL = os.getenv("RALFIA_MCP_HEALTH_URL", "http://127.0.0.1:8102/health")

# Infrastructure must not masquerade as an interactive Cursor IDE/agent session.
INFRASTRUCTURE_HEARTBEAT_SOURCES = frozenset(
    {
        "cursor_ops_runner.claim",
        "cursor_ops_orchestrator",
        "interactive_ops_runner.claim",
        "cursor_coordination_boot",
    }
)
AUTHENTIC_CONSUMER_SOURCES = frozenset(
    {
        "cursor_inbox_consumer",
        "cursor_private_worker",
        "cursor_ide_agent_session",
        "cursor_mcp_consumer_poll",
    }
)


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


def _heartbeat_counts_as_active_session(*, source: str, consumer_authentic: bool | None) -> bool:
    if consumer_authentic is not None:
        return bool(consumer_authentic)
    src = (source or "").strip()
    if src in INFRASTRUCTURE_HEARTBEAT_SOURCES:
        return False
    if src in AUTHENTIC_CONSUMER_SOURCES:
        return True
    return False


def register_session_heartbeat(
    *,
    identity: dict[str, Any] | None = None,
    host: str = "",
    lane: str = "",
    role: str = "",
    pid: int | None = None,
    source: str = "cursor_coordination_boot",
    consumer_authentic: bool | None = None,
) -> dict[str, Any]:
    """Persist liveness metadata. Only authentic consumer heartbeats mark session active."""
    ident = _sanitize_identity(identity)
    counts = _heartbeat_counts_as_active_session(source=source, consumer_authentic=consumer_authentic)
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
        "consumer_authentic": counts,
        "counts_as_active_session": counts,
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
    return {
        "ok": file_ok or mongo_ok,
        "file_ok": file_ok,
        "mongo_ok": mongo_ok,
        "session": payload,
        "counts_as_active_session": counts,
    }


def _upsert_liveness_state(
    *,
    state_key: str,
    file_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    file_ok = False
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(__import__("json").dumps(payload, indent=2) + "\n", encoding="utf-8")
        file_ok = True
    except OSError:
        pass
    mongo_ok = False
    try:
        from raphiia_openai import mongo_store

        mongo_store.upsert_coordination_state(key=state_key, data=payload)
        mongo_ok = True
    except Exception:
        pass
    return {"ok": file_ok or mongo_ok, "file_ok": file_ok, "mongo_ok": mongo_ok, "session": payload}


def register_cursor_consumer_heartbeat(
    *,
    identity: dict[str, Any] | None = None,
    host: str = "",
    lane: str = "cursor_interactive",
    role: str = "inbox_consumer",
    source: str = "cursor_inbox_consumer",
) -> dict[str, Any]:
    """Inbox/delivery liveness only — does NOT prove Cursor IDE can execute ops."""
    ident = dict(identity or {})
    ident.setdefault("mailbox", "cursor")
    ident.setdefault("raw_agent", "cursor")
    payload = {
        "agent": "cursor",
        "identity": _sanitize_identity(ident),
        "host": host or ident.get("host") or socket.gethostname(),
        "lane": lane,
        "role": role,
        "pid": int(os.getpid()),
        "source": source,
        "last_seen_at": _now(),
        "transport": "inbox_consumer_tick",
        "delivery_only": True,
        "consumer_authentic": True,
        "counts_as_active_session": False,
    }
    out = _upsert_liveness_state(state_key=CONSUMER_STATE_KEY, file_path=CONSUMER_FILE, payload=payload)
    out["counts_as_active_session"] = False
    return out


def register_cursor_ide_session(
    *,
    identity: dict[str, Any] | None = None,
    host: str = "",
    source: str = "cursor_ide_agent_session",
) -> dict[str, Any]:
    """Interactive Cursor IDE / Private Worker session — required before claim/execute."""
    ident = dict(identity or {})
    ident.setdefault("mailbox", "cursor")
    return register_session_heartbeat(
        identity=ident,
        host=host,
        lane="cursor_interactive",
        role="ide_executor",
        source=source,
        consumer_authentic=True,
    )


def _read_state_row(*, state_key: str, file_path: Path, ttl_seconds: int) -> dict[str, Any]:
    session: dict[str, Any] | None = None
    source = ""
    try:
        from raphiia_openai import mongo_store

        row = mongo_store.get_coordination_state(state_key)
        if row.get("ok"):
            session = dict((row.get("state") or {}))
            source = "mongo"
    except Exception:
        pass
    if not session and file_path.is_file():
        try:
            session = __import__("json").loads(file_path.read_text(encoding="utf-8"))
            source = "file"
        except Exception:
            session = None
    last_seen = _parse_ts((session or {}).get("last_seen_at"))
    age_seconds = None
    active = False
    counts = bool((session or {}).get("counts_as_active_session"))
    if (session or {}).get("source") in INFRASTRUCTURE_HEARTBEAT_SOURCES:
        counts = False
    if (session or {}).get("delivery_only"):
        counts = False
    if (session or {}).get("consumer_authentic") is True and not (session or {}).get("delivery_only"):
        counts = True
    if last_seen:
        age_seconds = max(0, int((datetime.now(timezone.utc) - last_seen).total_seconds()))
        active = counts and age_seconds <= int(ttl_seconds)
    return {
        "ok": True,
        "active": active,
        "consumer_authentic": counts,
        "source": source or "none",
        "age_seconds": age_seconds,
        "ttl_seconds": int(ttl_seconds),
        "session": session or {},
    }


def read_inbox_consumer_liveness(*, ttl_seconds: int = HEARTBEAT_TTL_SECONDS) -> dict[str, Any]:
    """Delivery path alive (ACK timer); not execution capability."""
    row = _read_state_row(state_key=CONSUMER_STATE_KEY, file_path=CONSUMER_FILE, ttl_seconds=ttl_seconds)
    sess = row.get("session") or {}
    row["delivery_only"] = True
    last_seen = _parse_ts(sess.get("last_seen_at"))
    if last_seen:
        age = max(0, int((datetime.now(timezone.utc) - last_seen).total_seconds()))
        row["age_seconds"] = age
        row["active"] = age <= int(ttl_seconds)
    else:
        row["active"] = False
    row["consumer_authentic"] = bool(sess.get("consumer_authentic"))
    return row


def read_session_liveness(*, ttl_seconds: int = HEARTBEAT_TTL_SECONDS) -> dict[str, Any]:
    """Return whether an interactive Cursor IDE session was seen recently."""
    row = _read_state_row(state_key=SESSION_STATE_KEY, file_path=SESSION_FILE, ttl_seconds=ttl_seconds)
    row["limitation"] = (
        "An inactive IDE heartbeat alone does not prove headless unavailable; "
        "check authenticated SDK or CLI readiness separately."
    )
    return row


def probe_cursor_sdk_readiness() -> dict[str, Any]:
    """Read-only SDK preflight; this is NOT proof that a task completed.

    The SDK runner used by cursor_headless_executor is independent of the
    optional cursor-agent CLI.  A missing CLI must not suppress a working SDK.
    Never return the API key or a secret-bearing exception string.
    """
    from importlib.util import find_spec

    try:
        installed = find_spec("cursor_sdk") is not None
    except (ImportError, ValueError):
        installed = False
    try:
        from inneros_core_runtime import cursor_api_credentials as credentials
        auth_ready = bool(credentials.cursor_api_key_status().get("present"))
    except Exception:
        auth_ready = False
    try:
        from inneros_core_runtime import cursor_headless_dispatch as dispatch
        enabled = bool(dispatch.headless_execute_enabled())
    except Exception:
        enabled = False
    try:
        from inneros_core_runtime import cursor_headless_lanes as lanes
        host_eligible = bool(lanes.is_ha_execution_node())
    except Exception:
        host_eligible = False

    return {
        "installed": installed,
        "auth_ready": auth_ready,
        "enabled": enabled,
        "host_eligible": host_eligible,
        "ready": all((installed, auth_ready, enabled, host_eligible)),
    }


def classify_cursor_execution(
    *,
    cli_probe: dict[str, Any] | None = None,
    sdk_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map live probes to headless_ready | partial | remote_inbox_only."""
    cli = dict(cli_probe or {})
    sdk = dict(sdk_probe) if sdk_probe is not None else probe_cursor_sdk_readiness()
    mcp = probe_mcp_bridge()
    session = read_session_liveness()
    consumer = read_inbox_consumer_liveness()
    cli_ready = bool(cli.get("installed") and cli.get("headless_supported") and cli.get("auth_ready"))
    # The headless SDK is a separate, authenticated execution path.  Requiring
    # an IDE heartbeat or CLI binary also when its own worker is ready causes
    # owner-approved tasks to be stranded in the inbox.
    sdk_ready = bool(sdk.get("ready") and sdk.get("installed") and sdk.get("auth_ready")
                     and sdk.get("enabled") and sdk.get("host_eligible"))
    headless_ready = cli_ready or sdk_ready
    mcp_ok = bool(mcp.get("reachable"))
    session_active = bool(session.get("active"))
    consumer_active = bool(consumer.get("active"))

    if headless_ready:
        classification = "headless_ready"
        provider_status = "ready"
        transport = "local_cursor_sdk_headless" if sdk_ready else "cursor_cli_headless"
    elif mcp_ok and session_active:
        classification = "partial"
        provider_status = "interactive_session"
        transport = "ide_inbox+interactive_agent"
    elif mcp_ok and consumer_active:
        classification = "remote_inbox_only"
        provider_status = "inbox_delivery_only"
        transport = "ide_inbox+consumer_ack"
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
    if mcp_ok and not session_active and not headless_ready:
        blockers.append("no_active_cursor_ide_session")
    if consumer_active and not session_active and not headless_ready:
        blockers.append("inbox_consumer_active_but_ide_session_required_for_execute")

    return {
        "ok": True,
        "execution_classification": classification,
        "provider_status": provider_status,
        "transport": transport,
        "headless_ready": headless_ready,
        "mcp_bridge": mcp,
        "interactive_session": session,
        "inbox_consumer": consumer,
        "blockers": blockers,
        "control_path": (
            "Owner authorization → claim → headless SDK worker → evidence → "
            "Temporal/Mongo terminal" if sdk_ready else
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
        "sdk_probe_summary": {
            "installed": bool(sdk.get("installed")),
            "auth_ready": bool(sdk.get("auth_ready")),
            "enabled": bool(sdk.get("enabled")),
            "host_eligible": bool(sdk.get("host_eligible")),
            "ready": sdk_ready,
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
    if (classified.get("sdk_probe_summary") or {}).get("ready"):
        merged["note"] = "Authenticated local Cursor SDK headless preflight ready; task completion still requires real evidence."
    else:
        merged["note"] = (
            f"classification={classified['execution_classification']}. "
            + (classified["control_path"] if classified["execution_classification"] == "partial" else "Delivery-only until an authenticated executor is ready.")
        )
    return merged
