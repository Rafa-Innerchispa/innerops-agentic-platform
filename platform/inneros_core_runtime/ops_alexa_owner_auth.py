"""Decisiones del propietario vía Alexa (Atlas Control).

Atlas Control conserva Voice ID + PIN nativo de Amazon y el anuncio sin
micrófono abierto. Este módulo solo consume el registro único compartido con
Telegram: la primera decisión válida gana de forma atómica.
"""

from __future__ import annotations

from typing import Any

from inneros_core_runtime import ops_owner_decision_registry as decisions
from inneros_core_runtime import ops_whatsapp_owner as shared_executor
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store


def apply_alexa_decision(
    *,
    task_id: str,
    nonce: str,
    decision: str,
    owner_actor: str = "RAFAEL",
) -> dict[str, Any]:
    """Aplica una decisión validada por Atlas Control al ejecutor existente."""
    tid = (task_id or "").strip()
    consumed = decisions.consume_decision(
        task_id=tid, nonce=nonce, decision=decision, channel="alexa", owner_actor=owner_actor,
    )
    if not consumed.get("ok"):
        decided_by = str(consumed.get("decided_by") or "otro canal")
        return {
            "ok": False,
            "error": consumed.get("error") or "decision_already_resolved",
            "text": f"`{tid}` ya fue resuelta por *{decided_by}*. Respuesta Alexa rechazada.",
            "task_id": tid,
        }
    if decision != "approve":
        from inneros_core_runtime import durable_coordination_spine

        out = durable_coordination_spine.signal_task_workflow(tid, "cancel", "owner_rejected_alexa")
        return {"ok": bool(out.get("ok")), "task_id": tid, "decision": "cancel", "channel": "alexa"}
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    short = tid.replace("ops_", "")[:6]
    return shared_executor.handle_owner_reply(
        f"SI {short}", owner_actor=owner_actor, phone=None,
    ) or {"ok": False, "task_id": tid}
