"""RalfIA Agent Coordination Bus task protocol.

This module is deliberately storage-independent so every agent adapter can use
the same lifecycle and validation rules before touching MongoDB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PROTOCOL_VERSION = "1.0.0"

TASK_STATUSES = frozenset(
    {
        "proposed",
        "accepted",
        "in_progress",
        "blocked",
        "awaiting_approval",
        "verification",
        "completed",
        "partial",
        "failed",
        "cancelled",
    }
)

LEGACY_STATUS_ALIASES = {
    "pending": "proposed",
    "dispatched": "accepted",
    "started": "in_progress",
    "done": "completed",
}

TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
ACTIVE_STATUSES = TASK_STATUSES - TERMINAL_STATUSES

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"accepted", "cancelled"}),
    "accepted": frozenset({"in_progress", "blocked", "cancelled"}),
    "in_progress": frozenset({"blocked", "awaiting_approval", "verification", "partial", "failed", "cancelled"}),
    "blocked": frozenset({"in_progress", "failed", "cancelled"}),
    "awaiting_approval": frozenset({"in_progress", "verification", "cancelled"}),
    "verification": frozenset({"in_progress", "completed", "partial", "failed"}),
    "completed": frozenset(),
    "partial": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(status: str | None) -> str:
    value = (status or "").strip().lower()
    return LEGACY_STATUS_ALIASES.get(value, value)


def validate_transition(current: str, target: str, *, allow_legacy_direct: bool = False) -> dict[str, Any]:
    current_n = normalize_status(current)
    target_n = normalize_status(target)
    if current_n not in TASK_STATUSES:
        return {"ok": False, "error": "invalid_current_status", "status": current_n}
    if target_n not in TASK_STATUSES:
        return {"ok": False, "error": "invalid_target_status", "status": target_n}
    if current_n == target_n:
        return {"ok": True, "idempotent": True, "current": current_n, "target": target_n}
    if allow_legacy_direct and current in LEGACY_STATUS_ALIASES and target_n in TASK_STATUSES:
        return {"ok": True, "idempotent": False, "current": current_n, "target": target_n, "legacy_direct": True}
    if target_n not in ALLOWED_TRANSITIONS[current_n]:
        return {
            "ok": False,
            "error": "invalid_transition",
            "current": current_n,
            "target": target_n,
            "allowed": sorted(ALLOWED_TRANSITIONS[current_n]),
        }
    return {"ok": True, "idempotent": False, "current": current_n, "target": target_n}


def validate_evidence(target_status: str, evidence: dict[str, Any] | None) -> dict[str, Any]:
    target = normalize_status(target_status)
    if target not in TERMINAL_STATUSES - {"cancelled"}:
        return {"ok": True}
    if not isinstance(evidence, dict) or not evidence:
        return {"ok": False, "error": "evidence_required", "status": target}
    result = str(evidence.get("status") or evidence.get("result") or "").strip().upper()
    if target == "completed" and result not in {"PASS", "OK", "COMPLETED"}:
        return {
            "ok": False,
            "error": "completion_result_required",
            "accepted_results": ["PASS", "OK", "COMPLETED"],
        }
    return {"ok": True}


def build_transition(
    *,
    current_status: str,
    target_status: str,
    actor: str,
    current_revision: int = 1,
    owner: str | None = None,
    evidence: dict[str, Any] | None = None,
    force_handoff: bool = False,
    allow_legacy_direct: bool = False,
) -> dict[str, Any]:
    actor_n = (actor or "").strip().lower()
    if not actor_n:
        return {"ok": False, "error": "actor_required"}

    transition = validate_transition(current_status, target_status, allow_legacy_direct=allow_legacy_direct)
    if not transition["ok"]:
        return transition
    if transition.get("idempotent"):
        return {**transition, "patch": {}, "revision": int(current_revision)}

    target = transition["target"]
    owner_n = (owner or "").strip().lower() or None
    if owner_n and owner_n != actor_n and not force_handoff:
        return {"ok": False, "error": "ownership_conflict", "owner": owner_n, "actor": actor_n}

    evidence_check = validate_evidence(target, evidence)
    if not evidence_check["ok"]:
        return evidence_check

    now = _now()
    patch: dict[str, Any] = {
        "status": target,
        "protocol_version": PROTOCOL_VERSION,
        "revision": int(current_revision) + 1,
        "updated_at": now,
        "updated_by": actor_n,
    }
    if target == "accepted":
        patch.update({"owner": actor_n, "accepted_at": now, "accepted_by": actor_n})
    elif target == "in_progress":
        patch.update({"owner": actor_n, "started_at": now, "last_heartbeat_at": now})
    elif target == "blocked":
        patch["blocked_at"] = now
    elif target == "awaiting_approval":
        patch["approval_requested_at"] = now
    elif target == "verification":
        patch["verification_started_at"] = now
    elif target in TERMINAL_STATUSES:
        patch.update({"completed_at": now, "evidence": evidence or {}})

    if force_handoff and owner_n != actor_n:
        patch.update({"owner": actor_n, "previous_owner": owner_n, "handoff_at": now})

    history = {
        "from": transition["current"],
        "to": target,
        "actor": actor_n,
        "at": now,
        "revision": patch["revision"],
    }
    return {"ok": True, "idempotent": False, "patch": patch, "history": history, "revision": patch["revision"]}
