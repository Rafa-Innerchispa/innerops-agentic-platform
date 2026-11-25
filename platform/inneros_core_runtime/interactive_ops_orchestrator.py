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
    auth = None
    if tid:
        auth = ior.authorize_ops_task(prov, tid, owner_actor=owner_actor, channel=channel)
        try:
            from inneros_core_runtime import ops_execution_node_routing as oenr

            oenr.stamp_routing_on_task(tid, provider=prov)
        except Exception:
            pass
    defer_peer = False
    if tid:
        from raphiia_openai import mongo_store
        from inneros_core_runtime.coordination_live import OPS_TASKS_COL

        task_row = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
        try:
            from inneros_core_runtime import ops_execution_node_routing as oenr

            allowed, reason, target = oenr.should_claim_on_this_node(task_row, prov)
            here = __import__(
                "inneros_core_runtime.cursor_headless_lanes", fromlist=["node_role"]
            ).node_role()
            if not allowed and target != here:
                defer_peer = True
                try:
                    from inneros_core_runtime.notifications import inneros_owner_lifecycle as life

                    task_row = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or task_row
                    life.notify_lifecycle(
                        task_row,
                        event="authorized_pending_peer",
                        detail=oenr.describe_routing(task_row, event="authorized_pending_peer"),
                        force=True,
                    )
                except Exception:
                    pass
                return {
                    "ok": True,
                    "provider": prov,
                    "stage": "authorized_pending_peer",
                    "target_node": target,
                    "routing_reason": reason,
                    "authorize": auth,
                    "claim": {"ok": False, "skipped": "deferred_to_peer", "target_node": target},
                }
        except Exception:
            pass
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
