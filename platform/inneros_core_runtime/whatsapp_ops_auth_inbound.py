"""Entrada rápida: autorización ops desde webhook (poll, botones, texto)."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai import whatsapp_evolution_parse as evo
from raphiia_openai import whatsapp_identity
from raphiia_openai.notifications.evolution_client import send_whatsapp

_APPLIED_COL = "ops_whatsapp_auth_inbound_applied"
_OPS_CMD = re.compile(
    r"^(?:SI|SÍ|NO|AUTORIZO|OK|CONFIRMAR|CANCELAR|RECHAZO|ops\.auth\.)",
    re.I,
)


def _norm_phone(sender: str) -> str:
    return "".join(c for c in str(sender or "") if c.isdigit())


def _message_id(payload: dict[str, Any]) -> str:
    data = evo.evolution_data(payload)
    key = data.get("key") or {} if isinstance(data, dict) else {}
    return str(key.get("id") or payload.get("event_id") or "")[:160]


def _command_from_payload(payload: dict[str, Any]) -> str:
    cmd = (evo.extract_message(payload) or "").strip()
    if cmd:
        return cmd
    return (evo.extract_poll_ops_auth_command(payload) or "").strip()


def _is_ops_auth_payload(payload: dict[str, Any], cmd: str) -> bool:
    if cmd and _OPS_CMD.match(cmd):
        return True
    data = evo.evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, dict) and message.get("pollUpdateMessage"):
        return True
    if isinstance(message, dict) and (
        message.get("buttonsResponseMessage") or message.get("listResponseMessage")
    ):
        selected = evo.extract_interactive_action(payload)
        if selected and selected.upper().startswith(("SI ", "NO ", "SÍ ")):
            return True
        if selected and selected.lower().startswith("ops.auth."):
            return True
    return False


def try_process_owner_ops_auth(payload: dict[str, Any], *, node: str = "primary") -> dict[str, Any] | None:
    """Procesa autorización ops y responde por WA. Idempotente por message_id del voto/tap."""
    cmd = _command_from_payload(payload)
    if not _is_ops_auth_payload(payload, cmd):
        return None

    mid = _message_id(payload)
    if mid:
        from raphiia_openai import mongo_store

        if mongo_store.get_db()[_APPLIED_COL].find_one({"message_id": mid}, {"_id": 1}):
            return {"ok": True, "action": "ops_owner_auth_duplicate", "message_id": mid}

    sender = evo.extract_sender(payload)
    conversation_id = evo.extract_conversation_id(payload) or sender
    is_group = evo.is_group_sender(sender) or str(conversation_id).endswith("@g.us")
    if is_group:
        return None

    identity = whatsapp_identity.resolve_identity(sender, chat_id=conversation_id, is_group=False)
    if not whatsapp_identity.is_owner(identity) or not whatsapp_identity.has_scope(
        identity, "whatsapp:agent_jobs"
    ):
        return {"ok": False, "action": "ops_owner_auth", "error": "unauthorized_sender"}

    if not cmd:
        return {
            "ok": False,
            "action": "ops_owner_auth_unparsed",
            "message_id": mid,
            "hint": "poll_vote_not_decoded_yet",
        }

    from inneros_core_runtime import ops_whatsapp_owner as ops_wa

    phone = _norm_phone(sender)
    out = ops_wa.handle_owner_reply(cmd, phone=phone)
    if out is None:
        return None

    auto_reply = None
    reply_text = (out.get("text") or "").strip()
    if reply_text and phone:
        auto_reply = send_whatsapp(reply_text, number=phone, node=node)

    if mid and out.get("ok"):
        from raphiia_openai import mongo_store

        mongo_store.get_db()[_APPLIED_COL].update_one(
            {"message_id": mid},
            {
                "$set": {
                    "message_id": mid,
                    "task_id": out.get("task_id"),
                    "command": cmd[:120],
                    "action": out.get("action"),
                }
            },
            upsert=True,
        )

    return {
        "ok": bool(out.get("ok")),
        "action": "ops_owner_auth_fast",
        "whatsapp_command": {**out, "command": "ops_owner_auth"},
        "auto_reply": auto_reply,
        "message_id": mid,
    }
