"""Default autonomy contract for IDE coding agents.

Owner intent: reversible work should proceed without permission-seeking. Human
interruptions are reserved for genuinely gated actions.
"""
from __future__ import annotations

from typing import Any

POLICY_VERSION = "inneros_agent_autonomy_v1"
POLICY_MARKER = "[INNEROS_AUTONOMY_POLICY_V1]"
AUTONOMY_TARGETS = frozenset({"codex", "antigravity", "cursor", "gemini"})
ESCALATION_ALLOWLIST = frozenset(
    {
        "destructive_or_irreversible",
        "unavailable_secret_or_credential",
        "unapproved_paid_spend",
        "account_level_approval",
        "out_of_scope_hardware_network_firmware_mutation",
    }
)


def normalize_target(value: str) -> str:
    key = str(value or "").strip().lower().replace("_", "-")
    aliases = {"anti-gravity": "antigravity", "google-antigravity": "antigravity", "codex-cli": "codex"}
    return aliases.get(key, key)


def interactive_override(payload: dict[str, Any] | None) -> bool:
    payload = payload or {}
    mode = str(payload.get("interaction_mode") or "").strip().lower()
    return bool(payload.get("allow_owner_questions") is True or mode in {"interactive", "human-in-loop", "human_in_loop"})


def applies(target: str, payload: dict[str, Any] | None = None) -> bool:
    return normalize_target(target) in AUTONOMY_TARGETS and not interactive_override(payload)


def metadata() -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "question_budget": 0,
        "reversible_decisions": "execute_without_owner_confirmation",
        "retry_policy": {"automatic": True, "minimum_safe_fallbacks_before_blocked": 1},
        "progress_channel": "heartbeat_or_status_not_permission_question",
        "ack_is_execution": False,
        "escalation_allowlist": sorted(ESCALATION_ALLOWLIST),
    }


def instruction_block() -> str:
    allowed = ", ".join(sorted(ESCALATION_ALLOWLIST))
    return (
        f"{POLICY_MARKER}\n"
        "AUTONOMY MODE IS OWNER-APPROVED FOR THIS TASK.\n"
        "question_budget=0 for reversible decisions inside the assigned scope. Infer routine intent from the task and prior context, then act.\n"
        "Do not ask whether to inspect files, create/use an isolated worktree, run tests, retry a failed command, fix ordinary code/test/lint issues, commit, or push your own assigned branch.\n"
        "For a recoverable failure: record the attempt, diagnose it, apply a safe reversible fix, retry automatically, and try at least one safe fallback before declaring BLOCKED.\n"
        "Use heartbeat/status messages to report progress. Progress reports are not requests for permission. ACK/read receipt is not execution; after ACK, claim the task and move to accepted/in_progress unless a real blocker exists.\n"
        "If ambiguity remains, choose the safest reversible option that preserves existing work and continue.\n"
        f"Interrupt the owner only for these escalation categories: {allowed}.\n"
        "A real blocker report must include evidence, attempts made, at least one safe fallback attempted, and the single specific human action required.\n"
        "Continue until the task is complete, decisively CHANGES_REQUIRED with evidence, or genuinely blocked by one of the allowed escalation categories.\n"
        f"[/INNEROS_AUTONOMY_POLICY_V1]"
    )


def enrich_body(body: str, *, target: str, payload: dict[str, Any] | None = None) -> str:
    text = str(body or "").strip()
    if not applies(target, payload) or POLICY_MARKER in text:
        return text
    return f"{text}\n\n{instruction_block()}" if text else instruction_block()


def enrich_payload(payload: dict[str, Any] | None, *, target: str) -> dict[str, Any]:
    out = dict(payload or {})
    if applies(target, out):
        out.setdefault("autonomy_policy", metadata())
        out.setdefault("question_budget", 0)
        out.setdefault("interaction_mode", "autonomous")
    return out


def default_execution_policy(existing: str | None, *, target: str, payload: dict[str, Any] | None = None) -> str | None:
    value = str(existing or "").strip()
    if not applies(target, payload):
        return value or None
    token = "autonomy:no-owner-questions-for-reversible-actions"
    if not value:
        return token
    if token in value:
        return value
    return f"{value};{token}"


def can_interrupt_owner(category: str) -> bool:
    return str(category or "").strip().lower() in ESCALATION_ALLOWLIST
