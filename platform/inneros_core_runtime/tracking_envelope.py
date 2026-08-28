"""Canonical InnerOS tracking envelope + W3C traceparent helpers.

This is the Google-native / A2A / IDE Task Bridge correlation contract.
Live Gemini/Vertex calls must reuse the same envelope; NON-LIVE harnesses
must set live_mode="NON-LIVE" and never report PASS for a simulated path.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

TRACEPARENT_RE = re.compile(
    r"^[\t ]*(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})[\t ]*$",
    re.IGNORECASE,
)

ENVELOPE_KEYS = (
    "project_id",
    "original_task_id",
    "takeover_task_id",
    "correlation_id",
    "trace_id",
    "traceparent",
    "span_id",
    "a2a_task_id",
    "context_id",
    "agent",
    "provider",
    "model",
    "repo",
    "base_sha",
    "branch",
    "worktree",
    "commit",
    "resource_lease_id",
    "tool_ids",
    "run_ids",
    "test_refs",
    "evidence_hash",
    "live_mode",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex(n_bytes: int) -> str:
    return secrets.token_hex(n_bytes)


def parse_traceparent(header: str | None) -> dict[str, str] | None:
    raw = (header or "").strip()
    if not raw:
        return None
    match = TRACEPARENT_RE.match(raw)
    if not match:
        return None
    return {
        "version": match.group("version").lower(),
        "trace_id": match.group("trace_id").lower(),
        "span_id": match.group("span_id").lower(),
        "flags": match.group("flags").lower(),
    }


def make_traceparent(*, trace_id: str | None = None, parent_span_id: str | None = None, flags: str = "01") -> str:
    tid = (trace_id or _hex(16)).lower()
    sid = (parent_span_id or _hex(8)).lower()
    if len(tid) != 32 or len(sid) != 16:
        raise ValueError("trace_id must be 32 hex chars and span_id 16 hex chars")
    return f"00-{tid}-{sid}-{flags.lower()}"


def child_span(traceparent: str) -> str:
    parsed = parse_traceparent(traceparent)
    if not parsed:
        raise ValueError("invalid_traceparent")
    return make_traceparent(trace_id=parsed["trace_id"], flags=parsed["flags"])


def live_mode_for(*, simulated: bool = False, quota_blocked: bool = False) -> str:
    if simulated or quota_blocked:
        return "NON-LIVE"
    return "LIVE"


def build_envelope(
    *,
    project_id: str = "innerops-agentic-platform",
    original_task_id: str = "",
    takeover_task_id: str = "",
    correlation_id: str = "",
    traceparent_header: str = "",
    a2a_task_id: str = "",
    context_id: str = "",
    agent: str = "",
    provider: str = "",
    model: str = "",
    repo: str = "Rafa-Innerchispa/innerops-agentic-platform",
    base_sha: str = "",
    branch: str = "",
    worktree: str = "",
    commit: str = "",
    resource_lease_id: str = "",
    tool_ids: list[str] | None = None,
    run_ids: list[str] | None = None,
    test_refs: list[str] | None = None,
    evidence_hash: str = "",
    simulated: bool = False,
    quota_blocked: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parse_traceparent(traceparent_header)
    if parsed:
        trace_id = parsed["trace_id"]
        span_id = parsed["span_id"]
        traceparent = make_traceparent(trace_id=trace_id, parent_span_id=span_id, flags=parsed["flags"])
    else:
        trace_id = _hex(16)
        span_id = _hex(8)
        traceparent = make_traceparent(trace_id=trace_id, parent_span_id=span_id)

    correlation = (correlation_id or context_id or a2a_task_id or f"corr_{trace_id[:16]}").strip()
    envelope: dict[str, Any] = {
        "project_id": project_id,
        "original_task_id": original_task_id,
        "takeover_task_id": takeover_task_id,
        "correlation_id": correlation,
        "trace_id": trace_id,
        "span_id": span_id,
        "traceparent": traceparent,
        "a2a_task_id": a2a_task_id,
        "context_id": context_id or correlation,
        "agent": agent,
        "provider": provider,
        "model": model,
        "repo": repo,
        "base_sha": base_sha,
        "branch": branch,
        "worktree": worktree,
        "commit": commit,
        "resource_lease_id": resource_lease_id,
        "tool_ids": list(tool_ids or []),
        "run_ids": list(run_ids or []),
        "test_refs": list(test_refs or []),
        "evidence_hash": evidence_hash,
        "live_mode": live_mode_for(simulated=simulated, quota_blocked=quota_blocked),
        "ts": _now(),
    }
    if extra:
        envelope.update(extra)
    return envelope
