"""Inbound Telegram — OPS auth + conversación RalfIA (paridad WhatsApp)."""

from __future__ import annotations

import os
import re
from typing import Any

from inneros_core_runtime import ops_whatsapp_owner as wa_owner
from inneros_core_runtime.notifications import telegram_client as tg

_OPS_AUTH_RE = re.compile(
    r"^(?:SI|SÍ|NO|OK|AUTORIZO|RECHAZO|CANCELAR|CONFIRMAR)\b|^ops\.auth\.(yes|no)\.",
    re.I,
)
_EXPLICIT_CMD_RE = re.compile(
    r"^(?:estado|status|servidor|diagnostica|correo|correos|poll|ayuda|help|notificaciones|pendientes)\b",
    re.I,
)


def _owner_phone() -> str:
    return (
        os.getenv("RALFIA_ALERTS_TO")
        or os.getenv("NOTIFY_WHATSAPP_TO")
        or "593999059000"
    ).strip().lstrip("+")


def _conversation_id(chat_id: str) -> str:
    return f"telegram:{chat_id}"


def _reply(chat_id: str, text: str, *, voice: bool | None = None) -> dict[str, Any]:
    from inneros_core_runtime.notifications.telegram_owner_channel import deliver_owner_message

    out = deliver_owner_message(text, chat_id=chat_id, reply_voice=voice, inline_ops_task_id=None)
    out["chat_id"] = chat_id
    return out


def _download_telegram_file(file_id: str) -> bytes:
    token = tg._bot_token()
    if not token or not file_id:
        return b""
    import httpx

    meta = httpx.get(
        f"https://api.telegram.org/bot{token}/getFile",
        params={"file_id": file_id},
        timeout=30.0,
    ).json()
    path = ((meta.get("result") or {}).get("file_path") or "").strip()
    if not path:
        return b""
    return httpx.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=90.0).content


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
        if msg.get("voice") or msg.get("audio"):
            return _handle_voice(msg)
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
    out = wa_owner.handle_owner_reply(data, owner_actor="RAFAEL", phone=_owner_phone())
    if cq_id:
        tg.answer_callback(cq_id, (out or {}).get("text", "")[:200] if out else "OK")
    if out and out.get("text"):
        _reply(chat_id, str(out["text"]), voice=False)
    return {"ok": True, "action": "callback", "result": out}


def _handle_natural(chat_id: str, text: str) -> dict[str, Any]:
    phone = _owner_phone()
    conv_id = _conversation_id(chat_id)
    from inneros_core_runtime import whatsapp_commands
    from inneros_core_runtime import whatsapp_identity
    from raphiia_openai.notifications import whatsapp_conversational as wc

    if _EXPLICIT_CMD_RE.match(text.strip()):
        cmd = whatsapp_commands.handle_inbound_command(
            text, phone, reply=False, conversation_id=conv_id, node="primary",
        )
        if cmd and cmd.get("text"):
            _reply(chat_id, str(cmd["text"]), voice=False)
            return {"ok": True, "action": "command", "result": cmd}

    identity = whatsapp_identity.resolve_identity(phone, chat_id=conv_id)
    conv = wc.conversational_reply(
        text, sender=phone, conversation_id=conv_id, identity=identity, channel="telegram",
    )
    reply = str(conv.get("text") or "").strip()
    if reply:
        voice = os.getenv("TELEGRAM_REPLY_VOICE", "1").strip().lower() in {"1", "true", "yes", "on"}
        voice = voice and conv.get("source") not in {"help", "command"}
        _reply(chat_id, reply[:4000], voice=voice)
        return {"ok": True, "action": "conversational", "source": conv.get("source"), "route": conv.get("route")}
    return {"ok": True, "skipped": "empty_reply", "conv": conv}


def _handle_voice(msg: dict[str, Any]) -> dict[str, Any]:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    allowed = (tg.owner_chat_id() or "").strip()
    if allowed and chat_id and chat_id != allowed:
        return {"ok": False, "error": "telegram_chat_not_owner"}
    tg.persist_owner_chat_id(chat_id)
    voice_obj = msg.get("voice") or msg.get("audio") or {}
    raw = _download_telegram_file(str(voice_obj.get("file_id") or ""))
    if not raw:
        tg.send_message("No pude descargar el audio.", chat_id=chat_id, parse_mode="")
        return {"ok": False, "error": "voice_download_failed"}
    import tempfile
    from pathlib import Path

    from inneros_core_runtime import whatsapp_media

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(raw)
        path = tmp.name
    try:
        tr = whatsapp_media.transcribe_routed(whatsapp_media.normalize_audio(path))
        transcript = str((tr or {}).get("text") or "").strip()
    except Exception as exc:
        tg.send_message(f"No pude transcribir ({type(exc).__name__}).", chat_id=chat_id, parse_mode="")
        return {"ok": False, "error": "transcription_failed"}
    finally:
        Path(path).unlink(missing_ok=True)
    if not transcript:
        tg.send_message("Audio vacío; repite por favor.", chat_id=chat_id, parse_mode="")
        return {"ok": True, "action": "voice_empty"}
    tg.send_message(f"🎙 {transcript[:500]}", chat_id=chat_id, parse_mode="")
    return _handle_natural(chat_id, transcript) | {"transcript": transcript}


def _handle_photo(msg: dict[str, Any]) -> dict[str, Any]:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    allowed = (tg.owner_chat_id() or "").strip()
    if allowed and chat_id and chat_id != allowed:
        return {"ok": False, "error": "telegram_chat_not_owner"}
    tg.persist_owner_chat_id(chat_id)
    photos = msg.get("photo") or []
    if not photos:
        return {"ok": True, "skipped": "no_photo"}
    raw = _download_telegram_file(str(photos[-1].get("file_id") or ""))
    if not raw:
        return {"ok": False, "error": "telegram_file_unavailable"}
    caption = str(msg.get("caption") or "").strip()
    tg.send_photo(raw, chat_id=chat_id, caption="Analizando…", filename="in.jpg")
    from inneros_core_runtime import whatsapp_identity
    from raphiia_openai.notifications import whatsapp_conversational as wc

    phone = _owner_phone()
    conv_id = _conversation_id(chat_id)
    identity = whatsapp_identity.resolve_identity(phone, chat_id=conv_id)
    conv = wc.conversational_reply(
        caption or "Describe esta imagen en contexto operativo.",
        sender=phone,
        conversation_id=conv_id,
        identity=identity,
        untrusted_media_context=f"[Imagen Telegram {len(raw)} bytes]",
        media_kind="image",
        channel="telegram",
    )
    if conv.get("text"):
        _reply(chat_id, str(conv["text"])[:4000], voice=False)
    return {"ok": True, "action": "photo_conversational"}


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
            "RalfIA por Telegram — habla natural: servidor, correo, clientes.\n"
            "Alertas aquí + Home Assistant. Voz: nota de voz → respuesta texto+audio.",
            chat_id=chat_id,
            parse_mode="",
        )
        return {"ok": True, "action": "start_registered"}
    if allowed and chat_id and chat_id != allowed:
        return {"ok": False, "error": "telegram_chat_not_owner"}
    tg.persist_owner_chat_id(chat_id)
    if text.startswith("/help"):
        from raphiia_openai.whatsapp_commands import HELP_TEXT

        tg.send_message(HELP_TEXT[:4000], chat_id=chat_id, parse_mode="")
        return {"ok": True, "action": "help"}
    if _OPS_AUTH_RE.match(text):
        out = wa_owner.handle_owner_reply(text, owner_actor="RAFAEL", phone=_owner_phone())
        if out and out.get("text"):
            _reply(chat_id, str(out["text"]), voice=False)
            return {"ok": True, "action": "owner_reply", "result": out}
    return _handle_natural(chat_id, text)
