"""Una sola orden owner → autorizar + claim Cursor (Composer fijado) + aviso."""

from __future__ import annotations

import os
import re
from typing import Any

from inneros_core_runtime import cursor_execution_plane as cep
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime.memory import agent_messages

CORRELATION_RE = re.compile(r"[a-z0-9][a-z0-9_-]{4,120}", re.I)
NOTIFY_OWNER = os.getenv("CURSOR_OPS_NOTIFY_WHATSAPP", "1") == "1"


def _notify_owner(text: str) -> dict[str, Any]:
    if not NOTIFY_OWNER:
        return {"ok": False, "skipped": "CURSOR_OPS_NOTIFY_WHATSAPP=0"}
    try:
        from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

        return send_alert_whatsapp(text, prefix_node=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def owner_order_execute(
    *,
    correlation_id: str | None = None,
    task_id: str | None = None,
    owner_actor: str = "RAFAEL",
    channel: str = "owner_order",
    owner_approved: bool = True,
    deliver_cursor_inbox: bool = True,
) -> dict[str, Any]:
    """Autoriza, claim y deja la tarea lista para ejecución Cursor interactiva."""
    if not owner_approved:
        listed = cor.list_claimable_ops_tasks(limit=5, correlation_id=correlation_id)
        return {
            "ok": False,
            "error": "owner_approval_required",
            "claimable": listed.get("tasks") or [],
            "hint": "Usa owner_approved=true, WhatsApp «procede cursor» + confirmar co_…, o cursor_authorize_ops_task.",
        }

    cep.register_session_heartbeat(source="cursor_ops_orchestrator", role="ops_executor")
    tid = (task_id or "").strip() or None
    corr = (correlation_id or "").strip() or None
    if not tid and not corr:
        listed = cor.list_claimable_ops_tasks(limit=1)
        tasks = listed.get("tasks") or []
        if not tasks:
            return {"ok": False, "error": "no_claimable_task", "listed": listed}
        tid = str(tasks[0].get("task_id") or "")

    if tid:
        cor.authorize_ops_task_for_cursor(tid, owner_actor=owner_actor, channel=channel)
    claim = cor.claim_ops_task(
        task_id=tid,
        correlation_id=corr if not tid else None,
        owner_approved=True,
        owner_actor=owner_actor,
    )
    if not claim.get("ok"):
        return {"ok": False, "stage": "claim", **claim}

    inbox = None
    if deliver_cursor_inbox:
        body = (
            f"OWNER ORDER · claim activo\n"
            f"task_id={claim.get('task_id')}\n"
            f"correlation_id={claim.get('correlation_id')}\n"
            f"model={claim.get('pinned_model')}\n"
            f"worktree={claim.get('worktree') or '(crear si vacío)'}\n"
            f"repo={claim.get('repo')}\n"
            f"branch={claim.get('work_branch')}\n\n"
            f"Objective:\n{(claim.get('objective') or '')[:3500]}"
        )
        inbox = agent_messages.create_agent_message(
            from_agent="notion",
            target_agent="cursor",
            title=f"Ejecutar ops claim · {claim.get('task_id')}",
            body=body,
            correlation_id=str(claim.get("correlation_id") or ""),
            message_type="task",
            payload={
                "task_id": claim.get("task_id"),
                "claim_token": claim.get("claim_token"),
                "owner_order": True,
                "do_not_auto_dispatch": True,
            },
            idempotency_key=f"owner-order-{claim.get('task_id')}-{claim.get('claim_token')}",
        )

    wa = _notify_owner(
        "✅ Cursor OPS autorizado\n"
        f"{claim.get('task_id')}: {claim.get('title', '')[:80]}\n"
        f"Modelo: {claim.get('pinned_model')}\n"
        f"Claim: {claim.get('claim_token', '')[:8]}…\n"
        "Claim listo: abre/ejecuta en sesión Cursor (aún no marca completed hasta evidencia+gate)."
    )

    return {
        "ok": True,
        "stage": "claimed",
        "claim": claim,
        "cursor_inbox": inbox,
        "whatsapp": wa,
        "model_policy": claim.get("model_policy"),
    }


def parse_correlation_from_text(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for token in raw.replace(",", " ").split():
        if len(token) >= 8 and CORRELATION_RE.fullmatch(token):
            return token
    return None
