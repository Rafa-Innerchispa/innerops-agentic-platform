"""Fan-out de coordinación: todos los agentes ven el mismo hilo OPS (ACK → inicio → entrega → revisión)."""

from __future__ import annotations

import json
from typing import Any

from inneros_core_runtime import agent_identity
from inneros_core_runtime.execution_binding import (
    requires_external_owner_authorization,
    resolve_execution_binding,
)

OBSERVER_AGENTS = ("chatgpt", "cursor")
MAX_BODY = 6000


def _mailbox(task: dict[str, Any]) -> str:
    return agent_identity.canonical_mailbox(
        task.get("assignee") or task.get("preferred_provider") or "",
        default="unknown",
    )


def _owner_ready(task: dict[str, Any]) -> bool:
    return bool(task.get("owner_authorized_at") or task.get("owner_approved"))


def _next_action(task: dict[str, Any], phase: str) -> str:
    if phase == "created":
        if _owner_ready(task):
            return "assignee_claim"
        binding = resolve_execution_binding(task)
        if requires_external_owner_authorization(task, binding):
            return "wait_owner_authorization"
        return "assignee_claim_or_auto_dispatch"
    if phase == "owner_authorized":
        return "assignee_claim"
    if phase in {"claimed", "in_progress"}:
        return "execute_and_heartbeat"
    if phase == "delivered_for_review":
        return "chatgpt_verify_evidence"
    if phase in {"completed", "failed", "blocked"}:
        return "read_final_report"
    return "observe"


def format_ops_report(
    task: dict[str, Any],
    *,
    phase: str,
    actor: str = "system",
    extra: dict[str, Any] | None = None,
) -> str:
    binding = resolve_execution_binding(task)
    ev = task.get("evidence") if isinstance(task.get("evidence"), dict) else {}
    candidate = task.get("candidate_evidence") if isinstance(task.get("candidate_evidence"), dict) else {}
    merged_ev = {**ev, **candidate, **(extra or {})}
    summary = {
        "protocol": "OPS_COORDINATION",
        "version": 1,
        "phase": phase,
        "actor": actor,
        "task_id": task.get("task_id"),
        "correlation_id": task.get("correlation_id"),
        "human_task_id": task.get("human_task_id"),
        "assignee": _mailbox(task),
        "preferred_provider": task.get("preferred_provider"),
        "status": task.get("status"),
        "execution_node": task.get("target_execution_node") or (task.get("payload") or {}).get("execution_node"),
        "repo": task.get("repo"),
        "base_ref": task.get("base_ref"),
        "owner_authorized": _owner_ready(task),
        "requires_owner_spend": requires_external_owner_authorization(task, binding),
        "runner": binding.get("runner"),
        "title": str(task.get("title") or "")[:500],
        "objective": str(task.get("objective") or task.get("title") or "")[:2000],
        "next_action": _next_action(task, phase),
        "evidence_keys": sorted(merged_ev.keys())[:40],
        "commit_sha": merged_ev.get("commit_sha") or task.get("git_baseline_sha"),
        "pr_url": merged_ev.get("pr_url") or merged_ev.get("pull_request_url"),
        "test_exit_code": (merged_ev.get("test_results") or {}).get("exit_code")
        if isinstance(merged_ev.get("test_results"), dict)
        else None,
    }
    lines = [
        f"OPS_COORDINATION v1 · {phase.upper()}",
        f"task_id: {summary['task_id']}",
        f"correlation_id: {summary['correlation_id']}",
        f"assignee: {summary['assignee']} · status: {summary['status']}",
        f"execution_node: {summary['execution_node'] or '—'}",
        f"owner_authorized: {'yes' if summary['owner_authorized'] else 'no'}",
        f"external_spend: {'yes' if summary['requires_owner_spend'] else 'no'}",
        f"next_action: {summary['next_action']}",
        "",
        str(summary["title"]),
        "",
        json.dumps(summary, ensure_ascii=False, indent=2)[:MAX_BODY],
    ]
    return "\n".join(lines)[:MAX_BODY]


def fanout_ops_phase(
    task: dict[str, Any],
    *,
    phase: str,
    actor: str = "system",
    extra: dict[str, Any] | None = None,
    also_notify: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Mensajes duraderos al assignee + observadores (ChatGPT/Cursor). Idempotente por fase."""
    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    assignee = _mailbox(task)
    body = format_ops_report(task, phase=phase, actor=actor, extra=extra)
    subject = f"[OPS/{phase.upper()}] {tid} · {str(task.get('title') or '')[:80]}"
    workflow_id = str(task.get("workflow_id") or f"ops_task:{tid}")
    run_id = str(task.get("run_id") or "")
    corr = str(task.get("correlation_id") or tid)

    from inneros_core_runtime import durable_coordination_spine as spine

    recipients: list[str] = []
    seen: set[str] = set()
    for name in (assignee, *OBSERVER_AGENTS, *also_notify):
        mb = agent_identity.canonical_mailbox(name, default="")
        if not mb or mb in seen:
            continue
        seen.add(mb)
        recipients.append(mb)

    sent: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for recipient in recipients:
        role = "assignee" if recipient == assignee else "observer"
        idem = f"OPS_FANOUT:{tid}:{phase}:{recipient}"
        out = spine.create_durable_message(
            task_id=tid,
            workflow_id=workflow_id,
            run_id=run_id,
            correlation_id=corr,
            sender=str(actor or "inneros").strip().lower(),
            recipient=recipient,
            subject=subject,
            content=body,
            metadata={
                "ops_coordination": True,
                "phase": phase,
                "role": role,
                "assignee": assignee,
                "owner_authorized": _owner_ready(task),
            },
            idempotency_key=idem,
        )
        row = {"recipient": recipient, "message_id": out.get("message_id"), "ok": out.get("ok"), "duplicate": out.get("duplicate")}
        if out.get("ok"):
            sent.append(row)
        else:
            errors.append({**row, "error": out.get("error")})

    return {
        "ok": bool(sent) and not errors,
        "partial": bool(sent) and bool(errors),
        "phase": phase,
        "task_id": tid,
        "sent": sent,
        "errors": errors,
        "recipient_count": len(recipients),
    }