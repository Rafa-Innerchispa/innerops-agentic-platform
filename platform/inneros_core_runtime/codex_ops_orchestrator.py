"""Orden owner única → autorizar + claim Codex ops task."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime import codex_ops_runner as cor


def owner_order_execute(
    *,
    correlation_id: str | None = None,
    task_id: str | None = None,
    owner_actor: str = "RAFAEL",
    channel: str = "owner_order",
    owner_approved: bool = True,
) -> dict[str, Any]:
    if not owner_approved:
        return {"ok": False, "error": "owner_approval_required", "claimable": cor.list_claimable_ops_tasks(limit=5, correlation_id=correlation_id)}
    tid = (task_id or "").strip() or None
    if tid:
        cor.authorize_ops_task_for_codex(tid, owner_actor=owner_actor, channel=channel)
    claim = cor.claim_ops_task(task_id=tid, correlation_id=correlation_id if not tid else None, owner_approved=True, owner_actor=owner_actor)
    return {"ok": bool(claim.get("ok")), "stage": "claimed" if claim.get("ok") else "claim", "claim": claim}
