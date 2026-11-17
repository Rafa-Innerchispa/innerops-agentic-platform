"""Windows <-> InnerOS <-> Kiro Autonomous Bridge capabilities for MCP Small."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pymongo import MongoClient

DEFAULT_HOST_ID = os.getenv("INNEROS_WINDOWS_HOST_ID", "ralphi-lenovo")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_DB = os.getenv("MONGO_DB", "pcdoctor_swarm")


def _db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    return client[MONGO_DB]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _freshness(updated_at: str | None) -> tuple[bool, float | None]:
    if not updated_at:
        return False, None
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age <= 60.0, round(age, 2)
    except Exception:
        return False, None


def _get_state(host_id: str | None = None) -> dict[str, Any]:
    hid = (host_id or DEFAULT_HOST_ID).strip() or DEFAULT_HOST_ID
    doc = _db()["ralfia_windows_bridge_state"].find_one({"_id": hid})
    if not doc:
        return {"ok": False, "error": "windows_bridge_not_connected", "host_id": hid}
    fresh, age_sec = _freshness(doc.get("updated_at"))
    doc["bridge_fresh"] = fresh
    doc["heartbeat_age_sec"] = age_sec
    return {"ok": True, "host_id": hid, "state": doc}


def windows_status(host_id: str | None = None) -> dict[str, Any]:
    res = _get_state(host_id)
    if not res.get("ok"):
        return res
    st = res["state"]
    return {
        "ok": True,
        "host_id": res["host_id"],
        "bridge_fresh": st.get("bridge_fresh"),
        "heartbeat_age_sec": st.get("heartbeat_age_sec"),
        "updated_at": st.get("updated_at"),
        "windows": st.get("windows"),
        "bridge": st.get("bridge"),
    }


def windows_kiro_status(host_id: str | None = None) -> dict[str, Any]:
    res = _get_state(host_id)
    if not res.get("ok"):
        return res
    st = res["state"]
    kiro = st.get("kiro") or {}
    logs = kiro.get("logs") or {}
    return {
        "ok": True,
        "host_id": res["host_id"],
        "bridge_fresh": st.get("bridge_fresh"),
        "updated_at": st.get("updated_at"),
        "kiro_running": kiro.get("running"),
        "mcp_config": kiro.get("mcp_config"),
        "connected_servers": logs.get("connected_servers"),
        "latest_log_dir": logs.get("latest_dir"),
        "mcp_events": (logs.get("mcp_events") or [])[-10:],
    }


def windows_kiro_sessions(host_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    res = _get_state(host_id)
    if not res.get("ok"):
        return res
    st = res["state"]
    kiro = st.get("kiro") or {}
    logs = kiro.get("logs") or {}
    capped = max(1, min(int(limit or 5), 10))
    return {
        "ok": True,
        "host_id": res["host_id"],
        "updated_at": st.get("updated_at"),
        "sessions": (kiro.get("sessions") or [])[:capped],
        "kiro_tail": (logs.get("kiro_tail") or [])[-capped:],
    }


def windows_workspace_status(host_id: str | None = None) -> dict[str, Any]:
    res = _get_state(host_id)
    if not res.get("ok"):
        return res
    st = res["state"]
    return {
        "ok": True,
        "host_id": res["host_id"],
        "updated_at": st.get("updated_at"),
        "workspace": st.get("workspace"),
    }


def windows_tests_results(host_id: str | None = None) -> dict[str, Any]:
    res = _get_state(host_id)
    if not res.get("ok"):
        return res
    st = res["state"]
    return {
        "ok": True,
        "host_id": res["host_id"],
        "updated_at": st.get("updated_at"),
        "tests": st.get("tests"),
    }


def windows_bridge_health(host_id: str | None = None) -> dict[str, Any]:
    hid = (host_id or DEFAULT_HOST_ID).strip() or DEFAULT_HOST_ID
    db = _db()
    res = _get_state(hid)
    recent_receipts = list(
        db["ralfia_windows_bridge_receipts"]
        .find({"target_host": hid}, {"_id": 0})
        .sort("finished_at", -1)
        .limit(5)
    )
    if not res.get("ok"):
        return {**res, "recent_receipts": recent_receipts}
    st = res["state"]
    return {
        "ok": True,
        "host_id": hid,
        "bridge_fresh": st.get("bridge_fresh"),
        "heartbeat_age_sec": st.get("heartbeat_age_sec"),
        "bridge": st.get("bridge"),
        "recent_receipts": recent_receipts,
    }


def windows_bridge_dispatch(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    host_id: str | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    wait_seconds: int = 10,
) -> dict[str, Any]:
    hid = (host_id or DEFAULT_HOST_ID).strip() or DEFAULT_HOST_ID
    db = _db()
    idem = (idempotency_key or "").strip() or f"wincmd_{uuid.uuid4().hex[:12]}"
    existing = db["ralfia_windows_bridge_receipts"].find_one({"idempotency_key": idem}, {"_id": 0})
    if existing:
        return {"ok": True, "deduplicated": True, "receipt": existing}

    cmd_id = f"cmd_{uuid.uuid4().hex[:12]}"
    doc = {
        "command_id": cmd_id,
        "target_host": hid,
        "action": action,
        "params": params or {},
        "idempotency_key": idem,
        "correlation_id": correlation_id,
        "status": "QUEUED",
        "created_at": _utc_iso(),
    }
    db["ralfia_windows_bridge_commands"].insert_one(dict(doc))

    wait_cap = max(0, min(int(wait_seconds or 0), 20))
    deadline = time.time() + wait_cap
    while time.time() < deadline:
        cur = db["ralfia_windows_bridge_commands"].find_one({"command_id": cmd_id}, {"_id": 0})
        if cur and cur.get("status") in ("SUCCESS", "FAILED", "BLOCKED"):
            return {"ok": cur["status"] == "SUCCESS", "command": cur}
        time.sleep(0.5)

    cur = db["ralfia_windows_bridge_commands"].find_one({"command_id": cmd_id}, {"_id": 0})
    return {"ok": True, "pending": True, "command": cur}


def windows_bridge_receipt(command_id: str) -> dict[str, Any]:
    db = _db()
    cmd = db["ralfia_windows_bridge_commands"].find_one({"command_id": command_id}, {"_id": 0})
    rcpt = db["ralfia_windows_bridge_receipts"].find_one({"command_id": command_id}, {"_id": 0})
    if not cmd and not rcpt:
        return {"ok": False, "error": "command_not_found", "command_id": command_id}
    return {"ok": True, "command_id": command_id, "command": cmd, "receipt": rcpt}


def _manifest(
    capability_id: str,
    *,
    title: str,
    description: str,
    keywords: list[str],
    mode: str,
    properties: dict[str, Any],
    required: list[str],
    required_scopes: list[str],
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "windows",
        "risk_class": "medium" if mode == "mutation" else "low",
        "mode": mode,
        "description": description,
        "keywords": keywords + ["windows", "kiro", "ghostbridge", "bridge"],
        "parameters_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "required_scopes": required_scopes,
    }


def _wrap(fn: Callable[..., dict[str, Any]]) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def _inner(parameters: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        return fn(**(parameters or {}))

    return _inner


def register_windows_capabilities(register_fn: Callable[[dict[str, Any], Any], Any] | None = None) -> int:
    if register_fn is None:
        from inneros_core_runtime.capability_gateway import register_capability
        register_fn = register_capability

    specs = [
        (
            _manifest(
                "windows.status.v1",
                title="Windows host and bridge status",
                description="Read-only status of Windows host, Tailscale IP, Python, Kiro/Antigravity processes, and bridge health.",
                keywords=["status", "host", "processes"],
                mode="read_only",
                properties={"host_id": {"type": "string"}},
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_status),
        ),
        (
            _manifest(
                "windows.kiro.status.v1",
                title="Kiro IDE & MCP GhostBridge connection status",
                description="Read-only status of Kiro IDE, sanitized mcp.json config, connected MCP servers, and recent mcp.log events.",
                keywords=["kiro", "mcp", "ghostbridge-evidence"],
                mode="read_only",
                properties={"host_id": {"type": "string"}},
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_kiro_status),
        ),
        (
            _manifest(
                "windows.kiro.sessions.v1",
                title="Recent Kiro IDE sessions and sanitized logs",
                description="Read-only list of recent Kiro IDE sessions and sanitized kiro.log tail.",
                keywords=["sessions", "logs", "history"],
                mode="read_only",
                properties={"host_id": {"type": "string"}, "limit": {"type": "integer"}},
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_kiro_sessions),
        ),
        (
            _manifest(
                "windows.workspace.status.v1",
                title="GhostBridge Windows workspace Git and MCP status",
                description="Read-only Git branch, HEAD, dirty files, agents, hooks, and inbox files for GhostBridge on Windows.",
                keywords=["workspace", "git", "branch"],
                mode="read_only",
                properties={"host_id": {"type": "string"}},
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_workspace_status),
        ),
        (
            _manifest(
                "windows.tests.results.v1",
                title="Latest GhostBridge MCP test results on Windows",
                description="Read-only summary of the latest GhostBridge MCP pytest execution on Windows.",
                keywords=["tests", "pytest", "results"],
                mode="read_only",
                properties={"host_id": {"type": "string"}},
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_tests_results),
        ),
        (
            _manifest(
                "windows.bridge.health.v1",
                title="Windows <-> InnerOS bridge health and recent receipts",
                description="Read-only heartbeat freshness, PID, allowed actions, and recent command receipts.",
                keywords=["health", "heartbeat", "receipts"],
                mode="read_only",
                properties={"host_id": {"type": "string"}},
                required=[],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_bridge_health),
        ),
        (
            _manifest(
                "windows.bridge.dispatch.v1",
                title="Dispatch allowlisted command to Windows Kiro Bridge",
                description="Enqueue an idempotent allowlisted command (refresh_snapshot, kiro_status, workspace_git_status, run_ghostbridge_mcp_tests, deliver_kiro_inbox_task, ps_diagnostic) and wait for receipt.",
                keywords=["dispatch", "command", "inbox", "diagnostic"],
                mode="mutation",
                properties={
                    "action": {"type": "string"},
                    "params": {"type": "object"},
                    "host_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "wait_seconds": {"type": "integer"},
                },
                required=["action"],
                required_scopes=["ralfia:agents"],
            ),
            _wrap(windows_bridge_dispatch),
        ),
        (
            _manifest(
                "windows.bridge.receipt.v1",
                title="Query Windows bridge command receipt",
                description="Read-only lookup of command lifecycle (QUEUED -> ACK -> RUNNING -> SUCCESS/FAILED) and receipt.",
                keywords=["receipt", "lifecycle", "ack"],
                mode="read_only",
                properties={"command_id": {"type": "string"}},
                required=["command_id"],
                required_scopes=["ralfia:read"],
            ),
            _wrap(windows_bridge_receipt),
        ),
    ]
    for manifest, handler in specs:
        register_fn(manifest, handler)
    return len(specs)
