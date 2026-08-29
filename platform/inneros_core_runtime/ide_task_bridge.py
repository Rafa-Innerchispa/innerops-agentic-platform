"""Canonical IDE Task Bridge — MCP inbox + A2A + ACP on one lifecycle.

Delivery to an IDE inbox is never treated as execution. External repair and
ACP-native paths reuse the same correlation_id and tracking envelope.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from inneros_core_runtime import google_adk_a2a
from inneros_core_runtime.tracking_envelope import build_envelope

BRIDGE_VERSION = "ide_task_bridge_v1"
SUPPORTED_TARGETS = google_adk_a2a.IDE_TARGETS
INBOX_PATHS = {
    "cursor": "cursor/INBOX.md",
    "codex": "codex/INBOX.md",
    "antigravity": "antigravity/INBOX.md",
    "gemini": "gemini/INBOX.md",
    "chatgpt": "chatgpt/INBOX.md",
}

DispatchStore = dict[str, dict[str, Any]]


def normalize_target(target: str) -> str:
    raw = (target or "").strip().lower()
    aliases = {
        "chatgpt": "gemini",
        "chatgpt_a": "gemini",
        "google": "gemini",
        "cursor_ide": "cursor",
    }
    return aliases.get(raw, raw)


def _idempotency_key(*, target: str, correlation_id: str, title: str) -> str:
    blob = f"{target}|{correlation_id}|{title}".encode()
    return hashlib.sha256(blob).hexdigest()[:24]


def project_execution_state(
    *,
    ops_status: str = "",
    a2a_status: dict[str, Any] | None = None,
    target: str = "cursor",
) -> dict[str, Any]:
    return google_adk_a2a.project_ide_task_bridge(
        a2a_status=a2a_status,
        ops_status=ops_status,
        target=target,
    )


def dispatch_ide_task(
    *,
    title: str,
    body: str,
    target: str,
    correlation_id: str = "",
    ops_task_id: str = "",
    repo: str = "Rafa-Innerchispa/innerops-agentic-platform",
    branch: str = "",
    worktree: str = "",
    transport: str = "ide_inbox",
    dry_run: bool = False,
    store: DispatchStore | None = None,
    message_writer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create one durable dispatch: ops metadata + IDE inbox message contract."""
    target_id = normalize_target(target)
    if target_id not in SUPPORTED_TARGETS:
        return {
            "ok": False,
            "error": "unsupported_ide",
            "target": target,
            "supported": list(SUPPORTED_TARGETS),
        }

    envelope = build_envelope(
        agent=target_id,
        provider="inneros-ide-bridge",
        correlation_id=correlation_id,
        branch=branch,
        worktree=worktree,
        repo=repo,
        extra={"ops_task_id": ops_task_id, "transport": transport},
    )
    corr = str(envelope["correlation_id"])
    idem = _idempotency_key(target=target_id, correlation_id=corr, title=title)
    bucket = store if store is not None else {}

    if idem in bucket:
        existing = bucket[idem]
        return {
            "ok": True,
            "duplicate": True,
            "idempotency_key": idem,
            **existing,
        }

    inbox_path = INBOX_PATHS.get(target_id, f"{target_id}/INBOX.md")
    message = {
        "from_agent": "INNEROS",
        "target_agent": target_id,
        "title": title,
        "body": body,
        "correlation_id": corr,
        "ops_task_id": ops_task_id,
        "transport": transport,
        "inbox_path": inbox_path,
        "metadata": {
            "repo": repo,
            "branch": branch,
            "worktree": worktree,
            "traceparent": envelope["traceparent"],
        },
    }

    write_result: dict[str, Any] = {"ok": True, "dry_run": dry_run}
    if not dry_run and message_writer is not None:
        write_result = message_writer(message)

    a2a_stub = {"status": {"state": "submitted"}, "correlation_id": corr, "envelope": envelope}
    projection = project_execution_state(
        a2a_status=a2a_stub,
        ops_status="proposed",
        target=target_id,
    )

    record = {
        "bridge_version": BRIDGE_VERSION,
        "target": target_id,
        "correlation_id": corr,
        "ops_task_id": ops_task_id,
        "transport": transport,
        "inbox_path": inbox_path,
        "envelope": envelope,
        "message": message,
        "write_result": write_result,
        "execution_projection": projection,
        "delivered_to_inbox": projection.get("delivered_to_inbox"),
        "running": projection.get("running"),
        "completed": projection.get("completed"),
    }
    bucket[idem] = record
    return {"ok": True, "duplicate": False, "idempotency_key": idem, **record}


def mark_ops_progress(
    *,
    store: DispatchStore,
    idempotency_key: str,
    ops_status: str,
    a2a_state: str = "",
) -> dict[str, Any]:
    record = store.get(idempotency_key)
    if not record:
        return {"ok": False, "error": "unknown_dispatch", "idempotency_key": idempotency_key}
    a2a_status = {"status": {"state": a2a_state or ops_status}, "correlation_id": record["correlation_id"]}
    projection = project_execution_state(
        a2a_status=a2a_status,
        ops_status=ops_status,
        target=record["target"],
    )
    record["execution_projection"] = projection
    record["ops_status"] = ops_status
    return {"ok": True, "idempotency_key": idempotency_key, "execution_projection": projection}
