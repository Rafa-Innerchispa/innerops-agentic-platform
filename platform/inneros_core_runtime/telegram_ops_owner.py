"""Inbound Telegram — OPS auth + conversación RalfIA (paridad WhatsApp)."""

from __future__ import annotations

import os
from typing import Any

from inneros_core_runtime import ops_whatsapp_owner as wa_owner
from inneros_core_runtime.notifications import telegram_client as tg


def _owner_phone() -> str:
    return (
        os.getenv("RALFIA_ALERTS_TO")
        or os.getenv("NOTIFY_WHATSAPP_TO")
        or "593999059000"
    ).strip().lstrip("+")


def _conversation_id(chat_id: str) -> str:
    return f"telegram:{chat_id}"


def ingest_telegram_update(update: dict[str, Any]) -> dict[str, Any]:
    if not update:
        return {"ok": False, "error": "empty_update"}
    cb = update.get("callback_query")
    if isinstance(cb, dict):
        return _handle_callback(cb)
    msg = update.get("message") or update.get("edited_message")
    if isinstance(msg, dict):
        if msg.get("photo"):
            return _handle_photo(msg)
        return _handle_message(msg)
    return {"ok": True, "skipped": "unhandled_update_type"}


def _handle_callback(cb: dict[str, Any]) -> dict[str, Any]:
    data = str(cb.get("data") or "").strip()
    cq_id = str(cb.get("id") or "")
    from_user = cb.get("from") or {}
    chat = (cb.get("message") or {}).get("chat") or {}
    chat_id = str(chat.get("id") or from_user.get("id") or "")
    allowed = (tg.owner_chat_id() or "").strip()
    if allowed and chat_id and chat_id != allowed:
        tg.answer_callback(cq_id, "No autorizado")
        return {"ok": False, "error": "telegram_chat_not_owner"}
    tg.persist_owner_chat_id(chat_id)
    out = wa_owner.handle_owner_reply(data, owner_actor="RAFAEL", phone=None)
    if cq_id:
        tg.answer_callback(cq_id, (out or {}).get("text", "")[:200] if out else "OK")
    if out and out.get("text"):
        tg.send_message(str(out["text"]), chat_id=chat_id, parse_mode="")
    return {"ok": True, "action": "callback", "result": out}


def _handle_natural(chat_id: str, text: str) -> dict[str, Any]:
    phone = _owner_phone()
    conv_id = _conversation_id(chat_id)
    from inneros_core_runtime import whatsapp_commands
    from inneros_core_runtime import whatsapp_identity
    from raphiia_openai.notifications import whatsapp_conversational as wc

    cmd = whatsapp_commands.handle_inbound_command(
        text,
        phone,
        reply=False,
        conversation_id=conv_id,
        node="primary",
    )
    if cmd and cmd.get("text"):
        tg.send_message(str(cmd["text"]), chat_id=chat_id, parse_mode="")
        return {"ok": True, "action": "command", "result": cmd}

    identity = whatsapp_identity.resolve_identity(phone, chat_id=conv_id)
    conv = wc.conversational_reply(
        text,
        sender=phone,
        conversation_id=conv_id,
        identity=identity,
    )
    reply = str(conv.get("text") or "").strip()
    if reply:
        tg.send_message(reply[:4000], chat_id=chat_id, parse_mode="")
        return {"ok": True, "action": "conversational", "source": conv.get("source")}
    return {"ok": True, "skipped": "empty_reply", "conv": conv}


def _handle_photo(msg: dict[str, Any]) -> dict[str, Any]:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    allowed = (tg.owner_chat_id() or "").strip()
    if allowed and chat_id and chat_id != allowed:
        return {"ok": False, "error": "telegram_chat_not_owner"}
    tg.persist_owner_chat_id(chat_id)
    caption = str(msg.get("caption") or "").strip()
    photos = msg.get("photo") or []
    if not photos:
        return {"ok": True, "skipped": "no_photo"}
    file_id = str(photos[-1].get("file_id") or "")
    token = tg._bot_token()
    if not token or not file_id:
        return {"ok": False, "error": "telegram_file_unavailable"}
    import httpx

    meta = httpx.get(
        f"https://api.telegram.org/bot{token}/getFile",
        params={"file_id": file_id},
        timeout=30.0,
    ).json()
    path = ((meta.get("result") or {}).get("file_path") or "").strip()
    if not path:
        return {"ok": False, "error": "telegram_getFile_failed"}
    raw = httpx.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=60.0).content
    tg.send_photo(raw, chat_id=chat_id, caption="Recibido · analizando…", filename="telegram_in.jpg")
    prompt = caption or "Describe esta imagen en contexto operativo (puerta, alarma, servidor)."
    from inneros_core_runtime import whatsapp_identity
    from raphiia_openai.notifications import whatsapp_conversational as wc

    phone = _owner_phone()
    conv_id = _conversation_id(chat_id)
    identity = whatsapp_identity.resolve_identity(phone, chat_id=conv_id)
    conv = wc.conversational_reply(
        prompt,
        sender=phone,
        conversation_id=conv_id,
        identity=identity,
        untrusted_media_context=f"[Imagen Telegram {len(raw)} bytes]",
        media_kind="image",
    )
    if conv.get("text"):
        tg.send_message(str(conv["text"])[:4000], chat_id=chat_id, parse_mode="")
    return {"ok": True, "action": "photo_conversational", "bytes": len(raw)}


def _handle_message(msg: dict[str, Any]) -> dict[str, Any]:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = str(msg.get("text") or "").strip()
    if not text:
        return {"ok": True, "skipped": "empty_text"}
    allowed = (tg.owner_chat_id() or "").strip()
    if text.startswith("/start"):
        tg.persist_owner_chat_id(chat_id)
        tg.send_message(
            "RalfIA conectado por Telegram.\n\n"
            "• Escribe en lenguaje natural (estado, correo, servicios…).\n"
            "• Alertas llegan aquí y en Home Assistant.\n"
            "• OPS: botones o CONFIRMAR <6chars> / CANCELAR <6chars>.\n"
            "• Fotos: envía imagen (puerta, cámara, captura).",
            chat_id=chat_id,
            parse_mode="",
        )
        return {"ok": True, "action": "start_registered", "chat_id": chat_id}
    if allowed and chat_id and chat_id != allowed:
        return {"ok": False, "error": "telegram_chat_not_owner"}
    tg.persist_owner_chat_id(chat_id)

    if text.startswith("/help"):
        from raphiia_openai.whatsapp_commands import HELP_TEXT

        tg.send_message(HELP_TEXT[:4000], chat_id=chat_id, parse_mode="")
        return {"ok": True, "action": "help"}

    out = wa_owner.handle_owner_reply(text, owner_actor="RAFAEL", phone=None)
    if out and out.get("text"):
        tg.send_message(str(out["text"]), chat_id=chat_id, parse_mode="")
        return {"ok": True, "action": "owner_reply", "result": out}

    return _handle_natural(chat_id, text)
