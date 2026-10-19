"""Orden owner única → autorizar + claim ops task para cualquier agente IDE registrado."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime import interactive_ops_runner as ior


def owner_order_execute(
    provider: str,
    *,
    correlation_id: str | None = None,
    task_id: str | None = None,
    owner_actor: str = "RAFAEL",
    channel: str = "owner_order",
    owner_approved: bool = True,
) -> dict[str, Any]:
    prov = ior.normalize_provider(provider)
    if not owner_approved:
        return {
            "ok": False,
            "error": "owner_approval_required",
            "provider": prov,
            "claimable": ior.list_claimable_ops_tasks(provider=prov, limit=5, correlation_id=correlation_id),
        }
    tid = (task_id or "").strip() or None
    if tid:
        from raphiia_openai import mongo_store
        from inneros_core_runtime.coordination_live import OPS_TASKS_COL

        row = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"owner_authorized_at": 1})
        if not (row or {}).get("owner_authorized_at"):
            auth = ior.authorize_ops_task(prov, tid, owner_actor=owner_actor, channel=channel)
            if not auth.get("ok"):
                return {
                    "ok": False,
                    "provider": prov,
                    "stage": "authorize",
                    "error": auth.get("error"),
                    "message": auth.get("message"),
                    "preflight": auth.get("preflight"),
                }
    claim = ior.claim_ops_task(
        prov,
        task_id=tid,
        correlation_id=correlation_id if not tid else None,
        owner_approved=True,
        owner_actor=owner_actor,
    )
    finish = None
    if claim.get("ok") and tid:
        try:
            from inneros_core_runtime.ops_verification_autofinish import try_finish_verification_task

            finish = try_finish_verification_task(
                task_id=tid,
                provider=prov,
                owner_actor=owner_actor,
            )
        except Exception as exc:
            finish = {"ok": False, "error": str(exc)[:200]}
    return {
        "ok": bool(claim.get("ok")),
        "provider": prov,
        "stage": "claimed" if claim.get("ok") else "claim",
        "claim": claim,
        "autofinish": finish,
    }
