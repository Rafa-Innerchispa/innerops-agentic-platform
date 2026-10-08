"""Parseo payloads Evolution API (webhook messages.upsert)."""

from __future__ import annotations

import json
import re
from typing import Any


_SENSITIVE_RAW_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "base64",
    "directpath",
    "fileencsha256",
    "filesha256",
    "jpegthumbnail",
    "mediakey",
    "thumbnail",
    "url",
}


def sanitize_payload_for_storage(value: Any) -> Any:
    """Remove transport credentials and encrypted media material before Mongo persistence."""
    if isinstance(value, dict):
        return {
            key: sanitize_payload_for_storage(item)
            for key, item in value.items()
            if str(key).replace("_", "").lower() not in _SENSITIVE_RAW_KEYS
        }
    if isinstance(value, list):
        return [sanitize_payload_for_storage(item) for item in value]
    return value


def evolution_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data else {}
    return data if isinstance(data, dict) else {}


def evolution_event(payload: dict[str, Any]) -> str:
    return str(payload.get("event") or payload.get("type") or "").strip().lower()


def should_ignore_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    """Filtra eco outbound y eventos que no son mensajes entrantes."""
    event = evolution_event(payload)
    if event in {"send.message", "connection.update", "qrcode.updated", "presence.update"}:
        return True, f"ignored:{event}"
    data = evolution_data(payload)
    key = data.get("key") or {}
    if key.get("fromMe"):
        return True, "from_me"
    return False, ""


def extract_sender(payload: dict[str, Any]) -> str:
    data = evolution_data(payload)
    if data:
        key = data.get("key") or {}
        remote = str(key.get("remoteJid") or "").strip()
        if remote.endswith("@g.us"):
            return str(key.get("participantAlt") or key.get("participant") or remote).strip()
        if remote:
            return remote
    for key in ("from", "sender", "phone", "number", "participant", "remoteJid"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("from", "sender", "phone", "number", "participant", "remoteJid"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return str(payload.get("sender") or "").strip()


def extract_conversation_id(payload: dict[str, Any]) -> str:
    data = evolution_data(payload)
    if data:
        key = data.get("key") or {}
        if isinstance(key, dict):
            remote = str(key.get("remoteJid") or "").strip()
            if remote:
                return remote
    for key_name in ("conversation_id", "conversationId", "chat_id", "chatId", "remoteJid", "thread_id", "threadId", "id"):
        val = payload.get(key_name)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        for key_name in ("conversation_id", "conversationId", "chat_id", "chatId", "remoteJid", "thread_id", "threadId", "id"):
            val = nested.get(key_name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    sender = extract_sender(payload)
    return sender


def extract_group_name(payload: dict[str, Any]) -> str:
    data = evolution_data(payload)
    if data:
        for key_name in ("groupName", "group_name", "chatName", "chat_name", "subject", "pushName", "push_name", "name"):
            val = data.get(key_name)
            if isinstance(val, str) and val.strip():
                return val.strip()
        msg = data.get("message") or {}
        if isinstance(msg, dict):
            for key_name in ("subject", "title", "pushName", "name"):
                val = msg.get(key_name)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    for key_name in ("groupName", "group_name", "chatName", "chat_name", "subject", "pushName", "push_name", "name"):
        val = payload.get(key_name)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        for key_name in ("groupName", "group_name", "chatName", "chat_name", "subject", "pushName", "push_name", "name"):
            val = nested.get(key_name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _poll_option_to_ops_verb(option_name: str) -> str | None:
    """Mapea texto de opción de encuesta ops → SI / NO."""
    raw = (option_name or "").strip()
    if not raw:
        return None
    lower = raw.casefold().replace("✅", "").replace("❌", "").strip()
    if lower.startswith("no") or "rechazar" in lower or "cancelar" in lower:
        return "NO"
    if (
        lower.startswith("sí")
        or lower.startswith("si")
        or lower == "confirmar"
        or "autorizar" in lower
        or "confirmar" in lower
        or "confirmar acción" in lower
    ):
        return "SI"
    return None


def extract_poll_ops_auth_command(payload: dict[str, Any]) -> str:
    """Voto en encuesta Sí/No de autorización ops → `SI ops_xxx` / `NO ops_xxx`."""
    from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending

    data = evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict):
        message = {}

    poll_id = ""
    selected_names: list[str] = []

    poll_update = message.get("pollUpdateMessage")
    if isinstance(poll_update, dict):
        key = poll_update.get("pollCreationMessageKey") or {}
        if isinstance(key, dict) and key.get("id"):
            poll_id = str(key["id"]).strip()
        vote = poll_update.get("vote") or {}
        if isinstance(vote, dict):
            for item in vote.get("selectedOptions") or []:
                if isinstance(item, str) and item.strip():
                    selected_names.append(item.strip())

    poll_updates = data.get("pollUpdates")
    if not isinstance(poll_updates, list):
        poll_updates = payload.get("pollUpdates") if isinstance(payload.get("pollUpdates"), list) else []
    if isinstance(poll_updates, list) and poll_updates:
        sender = extract_sender(payload)
        sender_digits = "".join(c for c in sender if c.isdigit())
        for entry in poll_updates:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            voters = entry.get("voters") or []
            if not name or not isinstance(voters, list):
                continue
            for voter in voters:
                voter_s = str(voter or "")
                voter_digits = "".join(c for c in voter_s if c.isdigit())
                if sender_digits and voter_digits and (
                    sender_digits.endswith(voter_digits) or voter_digits.endswith(sender_digits)
                ):
                    selected_names.append(name)
                    break

    if not selected_names:
        return ""

    verb = None
    for name in selected_names:
        verb = _poll_option_to_ops_verb(name)
        if verb:
            break
    if not verb:
        return ""

    task_id = ""
    if poll_id:
        doc = ops_pending.find_by_poll_message_id(poll_id)
        if doc:
            task_id = str(doc.get("task_id") or "")
    if not task_id:
        phone = extract_sender(payload)
        latest = ops_pending.latest_pending(phone)
        if latest:
            task_id = str(latest.get("task_id") or "")
    if not task_id:
        return ""
    return f"{verb} {task_id}"


def extract_interactive_action(payload: dict[str, Any]) -> str:
    """Convierte únicamente action IDs internos allowlisted a comandos canónicos."""
    data = evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict):
        return ""
    candidates: list[str] = []
    for container_name, field in (
        ("buttonsResponseMessage", "selectedButtonId"),
        ("templateButtonReplyMessage", "selectedId"),
    ):
        container = message.get(container_name)
        if isinstance(container, dict) and container.get(field):
            candidates.append(str(container[field]))
    list_response = message.get("listResponseMessage")
    if isinstance(list_response, dict):
        selected = list_response.get("singleSelectReply") or {}
        if isinstance(selected, dict) and selected.get("selectedRowId"):
            candidates.append(str(selected["selectedRowId"]))
    interactive = message.get("interactiveResponseMessage") or {}
    if isinstance(interactive, dict):
        native = interactive.get("nativeFlowResponseMessage") or {}
        if isinstance(native, dict) and native.get("paramsJson"):
            try:
                params = json.loads(str(native["paramsJson"]))
                for field in ("id", "selectedId", "selectedRowId"):
                    if isinstance(params, dict) and params.get(field):
                        candidates.append(str(params[field]))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    for candidate in candidates:
        sandbox_match = re.fullmatch(r"sandbox\.(confirm|cancel)\.(sm_[a-f0-9]+)", candidate.strip())
        if sandbox_match:
            verb = "confirmar" if sandbox_match.group(1) == "confirm" else "cancelar"
            return f"{verb} sandbox {sandbox_match.group(2)}"
        match = re.fullmatch(r"maint\.(confirm|cancel)\.([A-Za-z0-9_-]{4,100})", candidate.strip())
        if match:
            verb = "confirmar" if match.group(1) == "confirm" else "cancelar"
            return f"{verb} {match.group(2)}"
        menu_actions = {
            "menu.status": "estado",
            "menu.email": "correo",
            "menu.more": "más opciones",
            "menu.services": "servicios",
            "menu.notifications": "notificaciones",
            "menu.custom": "solicitud personalizada",
        }
        if candidate.strip() in menu_actions:
            return menu_actions[candidate.strip()]
        ops_auth = re.fullmatch(r"ops\.auth\.(yes|no)\.(ops_[a-f0-9]{12})", candidate.strip())
        if ops_auth:
            verb = "SI" if ops_auth.group(1) == "yes" else "NO"
            return f"{verb} {ops_auth.group(2)}"
    return ""


def extract_mentioned_jids(payload: dict[str, Any]) -> list[str]:
    """JIDs mencionados con @ nativo de WhatsApp (grupos)."""
    data = evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict):
        return []
    jids: list[str] = []
    for container in (
        message.get("extendedTextMessage"),
        message.get("messageContextInfo"),
        message,
    ):
        if not isinstance(container, dict):
            continue
        ctx = container.get("contextInfo") if container is not message else container
        if not isinstance(ctx, dict):
            ctx = container
        mentioned = ctx.get("mentionedJid") or ctx.get("mentionedJids") or []
        if isinstance(mentioned, str) and mentioned.strip():
            jids.append(mentioned.strip())
        elif isinstance(mentioned, list):
            jids.extend(str(j).strip() for j in mentioned if str(j).strip())
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for j in jids:
        if j not in seen:
            seen.add(j)
            out.append(j)
    return out


def strip_leading_agent_prefix(text: str) -> str:
    """Quita @ralphiia / @ralfia al inicio (mención textual)."""
    return re.sub(r"^\s*@ralph?i?ia(?=$|[\s,:;\-])(?:[\s,:;\-]+)?", "", text or "", count=1, flags=re.I).strip()


def extract_message(payload: dict[str, Any]) -> str:
    poll_action = extract_poll_ops_auth_command(payload)
    if poll_action:
        return poll_action
    interactive_action = extract_interactive_action(payload)
    if interactive_action:
        return interactive_action
    data = evolution_data(payload)
    if data:
        mobj = data.get("message") or {}
        if isinstance(mobj, dict):
            for key in ("conversation",):
                txt = mobj.get(key)
                if isinstance(txt, str) and txt.strip():
                    return txt.strip()
            ext = mobj.get("extendedTextMessage") or {}
            if isinstance(ext, dict):
                txt = ext.get("text")
                if isinstance(txt, str) and txt.strip():
                    return txt.strip()
            for media_key in ("imageMessage", "videoMessage", "documentMessage", "audioMessage"):
                media = mobj.get(media_key) or {}
                if isinstance(media, dict):
                    cap = media.get("caption")
                    if isinstance(cap, str) and cap.strip():
                        return cap.strip()
    for key in ("message", "text", "body", "content", "caption"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            inner = val.get("conversation") or val.get("text")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("message", "text", "body", "content", "caption"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""



def extract_media(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict): return None
    for kind, key in (("audio", "audioMessage"), ("image", "imageMessage"), ("document", "documentMessage"), ("video", "videoMessage")):
        item = message.get(key)
        if not isinstance(item, dict): continue
        raw_len, raw_seconds = item.get("fileLength") or 0, item.get("seconds") or 0
        return {"kind": kind, "mimetype": str(item.get("mimetype") or "").split(";",1)[0].strip().lower(), "file_length": int(raw_len) if str(raw_len).isdigit() else 0, "seconds": int(raw_seconds) if str(raw_seconds).isdigit() else 0, "caption": str(item.get("caption") or "").strip()[:4000], "file_name": str(item.get("fileName") or "").strip()[:160]}
    return None

def is_group_sender(sender: str) -> bool:
    return sender.endswith("@g.us") or sender.startswith("group:")


def extract_quoted_text(payload: dict[str, Any]) -> str:
    """Return only human-visible text/caption from the quoted WhatsApp message."""
    data = evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict):
        return ""
    containers = []
    extended = message.get("extendedTextMessage")
    if isinstance(extended, dict):
        containers.append(extended.get("contextInfo"))
    message_context = message.get("messageContextInfo")
    if isinstance(message_context, dict):
        containers.append(message_context)
    for context in containers:
        if not isinstance(context, dict):
            continue
        quoted = context.get("quotedMessage")
        if not isinstance(quoted, dict):
            continue
        conversation = quoted.get("conversation")
        if isinstance(conversation, str) and conversation.strip():
            return conversation.strip()[:8000]
        quoted_extended = quoted.get("extendedTextMessage")
        if isinstance(quoted_extended, dict):
            text = quoted_extended.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()[:8000]
        for media_key in ("imageMessage", "videoMessage", "documentMessage", "audioMessage"):
            media = quoted.get(media_key)
            if isinstance(media, dict):
                caption = media.get("caption")
                if isinstance(caption, str) and caption.strip():
                    return caption.strip()[:8000]
    return ""
