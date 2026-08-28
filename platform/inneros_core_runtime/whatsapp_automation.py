"""Procesamiento WhatsApp: inbound webhooks, palabras reservadas y recordatorios."""
from __future__ import annotations
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from raphiia_openai import mongo_store
from raphiia_openai.notifications.evolution_client import send_whatsapp, send_whatsapp_interactive
from raphiia_openai import whatsapp_evolution_parse as evo

INBOUND_COL = "whatsapp_inbound_events"
REMINDER_COL = "whatsapp_reminders"
QUOTE_TICKET_RE = re.compile(r"PCD-COT-\d{6}-[A-F0-9]{4}", re.I)
GROUP_AGENT_PREFIX_RE = re.compile(r"^\s*@ralph?i?ia(?=$|[\s,:;\-])(?:[\s,:;\-]+)?(.*)$", re.I | re.S)
QUOTEOPS_CREATE_RE = re.compile(
    r"^\s*(?:nueva\s+)?(?:cotizar|cotizaci[oó]n)\s*(?::|\-)?\s*(.+)$",
    re.I | re.S,
)
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "message", "body", "content", "conversation"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""
def _extract_message(payload: dict[str, Any]) -> str:
    return evo.extract_message(payload)
def _extract_sender(payload: dict[str, Any]) -> str:
    return evo.extract_sender(payload)
def _is_group(sender: str, conversation_id: str | None = None) -> bool:
    if conversation_id and conversation_id.endswith("@g.us"):
        return True
    return evo.is_group_sender(sender)
def _parse_due_at(text: str) -> tuple[str | None, str | None]:
    lower = text.lower().strip()
    now = datetime.now(timezone.utc)
    iso = re.search(r"(\d{4}-\d{2}-\d{2}[ t]\d{1,2}:\d{2})", lower)
    if iso:
        raw = iso.group(1).replace("t", " ").strip()
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat(), None
        except Exception:
            pass
    m = re.search(r"mañana(?:\s+a\s+las\s+(\d{1,2}:\d{2}))?", lower)
    if m:
        hhmm = m.group(1) or "09:00"
        try:
            hour, minute = [int(x) for x in hhmm.split(":", 1)]
            dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return dt.isoformat(), None
        except Exception:
            return None, f"No pude interpretar hora: {hhmm}"
    m = re.search(r"hoy(?:\s+a\s+las\s+(\d{1,2}:\d{2}))?", lower)
    if m:
        hhmm = m.group(1) or "09:00"
        try:
            hour, minute = [int(x) for x in hhmm.split(":", 1)]
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt < now:
                dt = dt + timedelta(days=1)
            return dt.isoformat(), None
        except Exception:
            return None, f"No pude interpretar hora: {hhmm}"
    return None, "due_at no detectado"
def _detect_node(payload: dict[str, Any]) -> str:
    from raphiia_openai.notifications.evolution_client import resolve_inbound_node

    return resolve_inbound_node(payload)

def _message_id(payload: dict[str, Any]) -> str:
    data=evo.evolution_data(payload); key=data.get("key") if isinstance(data,dict) else {}
    value=str((key or {}).get("id") or payload.get("event_id") or "").strip()
    if value: return value[:160]
    stable=f"{evo.extract_sender(payload)}\n{evo.extract_message(payload)}\n{evo.evolution_event(payload)}"
    return f"derived-{hashlib.sha256(stable.encode()).hexdigest()[:24]}"


def _normalize_phone(sender: str) -> str:
    return "".join(c for c in sender if c.isdigit())


def _sync_group_registry(payload: dict[str, Any], conversation_id: str, entity_id: str | None = None) -> None:
    if not conversation_id.endswith("@g.us"):
        return
    try:
        from raphiia_openai import whatsapp_contacts

        group_name = evo.extract_group_name(payload)
        labels: list[str] = []
        if entity_id:
            labels.append(entity_id)
        whatsapp_contacts.save_whatsapp_group(
            {
                "group_jid": conversation_id,
                "name": group_name or conversation_id,
                "alias": group_name or "",
                "entity_ids": [entity_id] if entity_id else [],
                "labels": labels,
                "notes": "auto-synced from inbound event",
                "source": "whatsapp_inbound",
            }
        )
    except Exception:
        pass


def _conversation_id(payload: dict[str, Any], sender: str) -> str:
    conv = evo.extract_conversation_id(payload)
    return conv or sender


def _canonical_conversation_id(
    conversation_id: str, *, is_group: bool, identity: dict[str, Any]
) -> str:
    if not is_group and identity.get("authenticated") and "owner" in set(identity.get("roles") or []):
        return f"owner:{identity.get('principal_id')}:whatsapp"
    return conversation_id


def _normalized_jid(value: str) -> str:
    raw = (value or "").strip().lower()
    digits = "".join(char for char in raw if char.isdigit())
    return digits or raw


def _agent_jids() -> set[str]:
    raw = os.getenv("WHATSAPP_AGENT_JIDS") or os.getenv("WHATSAPP_AGENT_NUMBERS") or ""
    jids = {_normalized_jid(value) for value in raw.split(",") if value.strip()}
    # JIDs de los chips Evolution (bots), no del móvil personal de Rafael
    try:
        from raphiia_openai import mongo_store

        for row in mongo_store.get_db()["ralfia_whatsapp_identities"].find(
            {"roles": {"$in": ["service_principal"]}, "status": "verified"},
            {"e164": 1},
        ):
            e164 = str(row.get("e164") or "").lstrip("+")
            if e164:
                jids.add(_normalized_jid(f"{e164}@s.whatsapp.net"))
    except Exception:
        pass
    return jids


def _quoted_agent_message(payload: dict[str, Any]) -> bool:
    if payload.get("quoted_agent") is True:
        return True
    data = evo.evolution_data(payload)
    message = data.get("message") if isinstance(data, dict) else None
    extended = message.get("extendedTextMessage") if isinstance(message, dict) else None
    context = extended.get("contextInfo") if isinstance(extended, dict) else None
    if not isinstance(context, dict) or not context.get("quotedMessage"):
        return False
    participant = str(context.get("participant") or context.get("remoteJid") or "").strip()
    known_jids = _agent_jids()
    return bool(participant and known_jids and _normalized_jid(participant) in known_jids)


def _activate_group_message(payload: dict[str, Any], message: str) -> tuple[bool, str, str]:
    text = (message or "").strip()
    if not text and not evo.extract_mentioned_jids(payload):
        return False, text, "empty"
    # @ nativo WhatsApp (mentionedJid)
    mentioned = evo.extract_mentioned_jids(payload)
    agent_jids = _agent_jids()
    if mentioned and agent_jids:
        for jid in mentioned:
            if _normalized_jid(jid) in agent_jids:
                clean = evo.strip_leading_agent_prefix(text) or text
                return True, clean, "mention:native_jid"
    # @ralphiia / @ralfia textual
    mention = GROUP_AGENT_PREFIX_RE.match(text)
    if mention:
        return True, (mention.group(1) or "").strip() or text, "mention:ralphiIA"
    if _quoted_agent_message(payload):
        return True, text, "quoted_agent_reply"
    # Imagen/audio/documento con caption vacío pero mención implícita vía quote
    if not text and _quoted_agent_message(payload):
        return True, text, "quoted_agent_media"
    return False, text, "ignored"


def _whatsapp_reply_audio_enabled() -> bool:
    return os.getenv("WHATSAPP_REPLY_AUDIO", "1") == "1"


def _send_whatsapp_reply(
    text: str,
    *,
    number: str,
    node: str,
    reply_audio: bool = False,
) -> dict[str, Any]:
    """Texto + nota de voz opcional (misma voz que voz.pcdoctor.ai)."""
    from raphiia_openai.notifications.evolution_client import send_whatsapp, send_whatsapp_audio

    wa = send_whatsapp(text, number=number, node=node)
    audio_wa = None
    if reply_audio and _whatsapp_reply_audio_enabled() and text.strip():
        try:
            audio_wa = send_whatsapp_audio(text, number=number, node=node)
        except Exception:
            audio_wa = {"ok": False, "status": "audio_skipped"}
    return {"text": wa, "audio": audio_wa}


def _event_id(payload: dict[str, Any], conversation_id: str, message: str) -> str:
    data = evo.evolution_data(payload)
    key = data.get("key") if isinstance(data, dict) else None
    raw = str((key or {}).get("id") or payload.get("event_id") or "").strip()
    if raw:
        return raw[:160]
    digest = hashlib.sha256(f"{conversation_id}\n{message}".encode("utf-8")).hexdigest()
    return f"wa-{digest[:32]}"


def _start_quoteops_from_whatsapp(
    payload: dict[str, Any],
    message: str,
    *,
    sender: str,
    conversation_id: str,
) -> dict[str, Any] | None:
    match = QUOTEOPS_CREATE_RE.match(message or "")
    if not match:
        return None
    request_text = match.group(1).strip()
    if not request_text:
        return {"ok": False, "error": "quote_request_empty"}

    customer_name = ""
    customer_match = re.match(r"^([^:\n]{2,120})\s*:\s*(.+)$", request_text, re.S)
    if customer_match:
        customer_name = customer_match.group(1).strip()
        request_text = customer_match.group(2).strip()

    from raphiia_openai import quoteops_mcp_bridge

    channel_event_id = _event_id(payload, conversation_id, message)
    result = quoteops_mcp_bridge.call(
        "quoteops_start_or_continue_mission",
        {
            "idempotency_key": f"whatsapp-quote-{channel_event_id}"[:120],
            "language": "es",
            "source_channel": "whatsapp",
            "channel_event_id": channel_event_id,
            "sender_id": sender,
            "customer_name": customer_name,
            "message": request_text,
            "attachments": [],
        },
    )
    return result


def _handle_quote_ticket_inbound(message: str, sender: str, is_group: bool, node: str) -> dict[str, Any] | None:
    match = QUOTE_TICKET_RE.search(message)
    if not match:
        return None
    ticket_id = match.group(0).upper()
    from raphiia_openai.operational.quote_delivery import get_delivery_by_ticket, update_delivery_status

    delivery = get_delivery_by_ticket(ticket_id)
    if not delivery.get("ok"):
        if not is_group and sender:
            send_whatsapp(
                f"No encontramos la referencia `{ticket_id}`. Verifica el número o contacta a PC Doctor.",
                number=_normalize_phone(sender),
                node=node,
            )
        return {"ok": False, "ticket_id": ticket_id, "error": "ticket not found"}
    lower = message.lower()
    if re.search(r"\b(aprob|acepto|aceptamos|confirmo|ok\b|sí\b|si\b|de acuerdo)\b", lower):
        status, label = "accepted", "Aceptada"
    elif re.search(r"\b(rechaz|no quiero|cancel|anul)\b", lower):
        status, label = "rejected", "Rechazada"
    else:
        status, label = "follow_up", "En seguimiento"
    updated = update_delivery_status(ticket_id, status, detail=message[:500])
    reply = (
        f"*PC Doctor · Cotización*\n\n"
        f"Recibimos tu mensaje sobre `{ticket_id}`.\n"
        f"Estado: *{label}*\n\n"
        f"Gracias — un asesor te contactará si hace falta."
    )
    wa_result = None
    if not is_group and sender:
        wa_result = send_whatsapp(reply, number=_normalize_phone(sender), node=node)
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "status": status,
        "delivery": updated.get("delivery"),
        "auto_reply": wa_result,
    }


def ingest_inbound_event(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import whatsapp_message_ledger

    node = _detect_node(payload)
    instance = str(payload.get("instance") or payload.get("whatsappInstance") or payload.get("id") or "")
    db = mongo_store.get_db()
    message_id = _message_id(payload)
    existing = db[INBOUND_COL].find_one({"trace.message_id": message_id}, {"raw": 0})
    if existing:
        existing["_id"] = str(existing.get("_id"))
        return {"ok": True, "event": existing, "action": "duplicate_event", "idempotent": True}
    classification = whatsapp_message_ledger.classify_inbound(payload)
    ledger = whatsapp_message_ledger.record_inbound(classification, node=node, instance=instance)
    if not classification.get("should_route"):
        return {
            "ok": True,
            "skipped": True,
            "reason": classification.get("reason"),
            "actor_type": classification.get("actor_type"),
            "ledger": ledger,
        }
    sender = _extract_sender(payload)
    raw_message = _extract_message(payload)
    message = raw_message
    conversation_id = _conversation_id(payload, sender)
    is_group = _is_group(sender, conversation_id)
    from raphiia_openai import whatsapp_identity

    identity = whatsapp_identity.resolve_identity(sender, chat_id=conversation_id, is_group=is_group)
    canonical_conversation_id = _canonical_conversation_id(
        conversation_id, is_group=is_group, identity=identity
    )
    now = _now()
    media_result = None
    try:
        from raphiia_openai.whatsapp_media import process_media
        media_result = process_media(payload, node=node)
    except Exception as exc:
        media_result = {"ok": False, "status": "error", "processing_status": "unavailable", "processing_error": str(exc)}
    correlation_id=f"wa-{hashlib.sha256(f'{message_id}:{conversation_id}'.encode()).hexdigest()[:20]}"
    media_id=(f"media-{str(media_result.get('checksum'))[:20]}" if isinstance(media_result,dict) and media_result.get("checksum") else None)
    trace={"message_id":message_id,"media_id":media_id,"correlation_id":correlation_id,"conversation_ref":f"whatsapp:{hashlib.sha256(canonical_conversation_id.encode()).hexdigest()[:12]}","related_project":"raphiia-openai","node":node}
    group_active = True
    activation_reason = "direct"
    if is_group:
        group_active, clean_message, activation_reason = _activate_group_message(payload, message)
        message = clean_message
    event = {
        "received_at": now,
        "sender": sender,
        "conversation_id": conversation_id,
        "canonical_conversation_id": canonical_conversation_id,
        "is_group": is_group,
        "group_activation": activation_reason if is_group else "direct",
        "raw_message": raw_message,
        "effective_message": message,
        "message": message,
        "node": node,
        "instance": payload.get("instance") or payload.get("whatsappInstance") or payload.get("id") or "",
        "event_type": evo.evolution_event(payload) or payload.get("type") or "message",
        "actor_type": classification.get("actor_type"),
        "routing_reason": classification.get("reason"),
        "ledger_id": ledger.get("ledger_id"),
        "trace": trace,
        "identity": {
            "authenticated": bool(identity.get("authenticated")),
            "principal_id": identity.get("principal_id"),
            "roles": identity.get("roles") or [],
            "sender_hash": identity.get("sender_hash"),
            "reason": identity.get("reason"),
        },
        "raw": evo.sanitize_payload_for_storage(payload),
    }
    if media_result and media_result.get("status") != "not_media":
        event["media"] = {k: v for k, v in media_result.items() if k != "path"}
    inserted = db[INBOUND_COL].insert_one(event)
    event_out = {**event, "_id": str(inserted.inserted_id)}
    if is_group:
        _sync_group_registry(payload, conversation_id, entity_id=payload.get("entity_id"))
    if is_group and not group_active:
        return {"ok": True, "event": event_out, "action": "group_ignored", "group_activation": activation_reason}
    lowered = message.lower().strip()
    from raphiia_openai import quoteops_iess_bridge, whatsapp_commands

    iess_action = quoteops_iess_bridge.parse_iess_action(message)
    sender_authorized = bool(sender and whatsapp_identity.is_owner(identity))
    quote_request = bool(QUOTEOPS_CREATE_RE.match(message or ""))
    if quote_request and not sender_authorized and not (is_group and group_active):
        return {"ok": True, "event": event_out, "action": "sensitive_action_ignored"}
    if quote_request:
        quote_result = _start_quoteops_from_whatsapp(
            payload,
            message,
            sender=sender,
            conversation_id=conversation_id,
        ) or {"ok": False, "error": "quote_request_not_processed"}
        mission_id = str(quote_result.get("mission_id") or "")
        if quote_result.get("ok") and mission_id:
            reply = (
                "*PC Doctor · QuoteOps*\n\n"
                "La misión de cotización fue creada correctamente.\n"
                f"Referencia: `{mission_id}`\n\n"
                "Puedes continuarla desde QuoteOps o ChatGPT."
            )
        else:
            reply = (
                "No pude iniciar la cotización en este momento. "
                "El evento quedó registrado para revisión."
            )
        reply_dest = conversation_id if is_group else _normalize_phone(sender)
        wa_result = send_whatsapp(reply, number=reply_dest, node=node) if reply_dest else None
        return {
            "ok": bool(quote_result.get("ok")),
            "event": event_out,
            "action": "quoteops_mission_started" if mission_id else "quoteops_mission_error",
            "quoteops": quote_result,
            "auto_reply": wa_result,
        }
    if iess_action and not sender_authorized:
        return {"ok": True, "event": event_out, "action": "sensitive_action_ignored"}
    if iess_action:
        action_name, action_id = iess_action
        result = quoteops_iess_bridge.apply_iess_action(action_name, action_id, sender=sender)
        reply = quoteops_iess_bridge.format_action_reply(action_name, result)
        reply_dest = conversation_id if is_group else _normalize_phone(sender)
        wa_result = send_whatsapp(reply, number=reply_dest, node=node) if reply_dest else None
        return {"ok": True, "event": event_out, "iess_action": result, "auto_reply": wa_result}
    if quoteops_iess_bridge.is_iess_payment_image(payload, message) and sender_authorized:
        result = quoteops_iess_bridge.preview_iess_payment(payload, sender=sender, node=node)
        reply = str(result.get("reply") or "Identifiqué un comprobante IESS, pero necesito una imagen más nítida.")
        reply_dest = conversation_id if is_group else _normalize_phone(sender)
        wa_result = send_whatsapp(reply, number=reply_dest, node=node) if reply_dest else None
        return {"ok": True, "event": event_out, "iess_payment": result, "auto_reply": wa_result}
    reminder_prefixes = ("recordatorio:", "reminder:")
    note_prefixes = ("nota:", "note:")
    if any(lowered.startswith(prefix) for prefix in reminder_prefixes):
        body = message.split(":", 1)[1].strip() if ":" in message else message
        due_at, parse_error = _parse_due_at(body)
        reminder = {
            "reminder_id": f"rem_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "created_at": now,
            "updated_at": now,
            "status": "pending" if due_at else "needs_time",
            "source": "whatsapp_inbound",
            "source_event": event,
            "sender": sender,
            "is_group": is_group,
            "body": body,
            "due_at": due_at,
            "parse_error": parse_error,
            "target_number": sender if not is_group else "",
            "entity_id": payload.get("entity_id") or "",
        }
        db[REMINDER_COL].insert_one(reminder)
        return {"ok": True, "event": event_out, "reminder": {**reminder}}
    if any(lowered.startswith(prefix) for prefix in note_prefixes):
        return {"ok": True, "event": event_out, "note_created": True}
    quote_result = _handle_quote_ticket_inbound(message, sender, is_group, node)
    if quote_result is not None:
        return {"ok": True, "event": event_out, "quote_tracking": quote_result}
    accounting_prefixes = ("cheque:", "ap:", "pagar:")
    if any(lowered.startswith(prefix) for prefix in accounting_prefixes):
        from raphiia_openai.operational import accounting_store

        payable = accounting_store.create_payable_from_whatsapp(
            message,
            entity_id=str(payload.get("entity_id") or "ent_pcdoctor"),
        )
        return {"ok": True, "event": event_out, "accounting": payable}
    if re.search(r"\b(recordar|avisar|al\s+dia\s+siguiente)\b", lowered):
        return {"ok": True, "event": event_out, "hint": "possible_reminder"}
    # Only user-authored text or an authorized sender's audio transcript may
    # reach command/agent routing. OCR and vision output remain context-only.
    from raphiia_openai import whatsapp_daily_memory

    transcript_text = ""
    media_processing_error = ""
    if isinstance(media_result, dict):
        transcript = media_result.get("transcript") or {}
        if isinstance(transcript, dict):
            transcript_text = str(transcript.get("text") or "").strip()
        if not transcript_text and str(media_result.get("kind") or "").lower() == "audio":
            media_processing_error = str(
                media_result.get("processing_error")
                or (media_result.get("transcript") or {}).get("error")
                or ""
            ).strip()
    agent_message = message.strip() or transcript_text
    conversation_message = agent_message
    if message.strip() and transcript_text and transcript_text not in message:
        conversation_message = f"{message.strip()}\n\nTranscripción del audio: {transcript_text}"
    image_context = whatsapp_daily_memory.untrusted_image_context(media_result)
    media_kind = str(media_result.get("kind") or "").lower() if isinstance(media_result, dict) else ""
    if image_context and not conversation_message:
        conversation_message = "Te envío esta imagen para que la tengas en cuenta en la conversación."
    cmd_result = whatsapp_commands.handle_inbound_command(
        agent_message,
        sender,
        is_group=is_group,
        group_activated=group_active if is_group else False,
        node=node,
        # This function owns delivery so each command gets exactly one reply.
        reply=False,
        trace=trace,
        conversation_id=conversation_id,
    )
    if cmd_result is not None:
        auto_reply = None
        reply_text = (cmd_result.get("text") or "").strip() if isinstance(cmd_result, dict) else ""
        reply_dest = conversation_id if is_group else _normalize_phone(sender)
        if reply_text and reply_dest:
            interactive = cmd_result.get("interactive") if isinstance(cmd_result, dict) else None
            if isinstance(interactive, dict) and interactive.get("kind") == "buttons":
                auto_reply = send_whatsapp_interactive(
                    reply_text,
                    interactive.get("buttons") or [],
                    number=reply_dest,
                    node=node,
                    fallback_text=str(interactive.get("fallback_text") or reply_text),
                )
            else:
                auto_reply = send_whatsapp(reply_text, number=reply_dest, node=node)
        return {
            "ok": True,
            "event": event_out,
            "whatsapp_command": cmd_result,
            "group_mode": is_group,
            "auto_reply": auto_reply,
        }
    if is_group and group_active and conversation_message.strip():
        from raphiia_openai import whatsapp_conversational

        conv = whatsapp_conversational.conversational_reply(
            conversation_message,
            sender=sender,
            conversation_id=canonical_conversation_id,
            is_group=True,
            entity_id=payload.get("entity_id"),
            untrusted_media_context=image_context,
            media_kind=media_kind,
            identity=identity,
        )
        wa = None
        if conv.get("text"):
            wa = _send_whatsapp_reply(
                conv["text"],
                number=conversation_id,
                node=node,
                reply_audio=(media_kind == "audio"),
            )
        return {
            "ok": True,
            "event": event_out,
            "action": "group_conversational_capture",
            "conversation": conv,
            "group_mode": True,
            "auto_reply": wa,
        }
    if not is_group and sender and not conversation_message.strip() and str(media_kind or "").lower() == "audio":
        if whatsapp_identity.is_owner(identity):
            hint = (
                "Recibí tu nota de voz, pero no pude transcribirla ahora (Whisper no disponible). "
                "Intenta de nuevo en unos segundos o escríbeme por texto."
            )
            if media_processing_error:
                hint += f"\n\nDetalle técnico: {media_processing_error[:120]}"
            wa = _send_whatsapp_reply(
                hint,
                number=_normalize_phone(sender),
                node=node,
                reply_audio=False,
            )
            return {"ok": True, "event": event_out, "action": "audio_transcription_failed", "auto_reply": wa}
    if not is_group and sender and conversation_message.strip() and whatsapp_identity.is_owner(identity):
        from raphiia_openai import whatsapp_conversational

        conv = whatsapp_conversational.conversational_reply(
            conversation_message,
            sender=sender,
            conversation_id=canonical_conversation_id,
            is_group=False,
            entity_id=payload.get("entity_id"),
            untrusted_media_context=image_context,
            media_kind=media_kind,
            identity=identity,
        )
        try:
            conv["daily_memory"] = whatsapp_daily_memory.record_exchange(
                conversation_id=canonical_conversation_id,
                user_text=conversation_message,
                assistant_text=conv.get("text"),
                trace=trace,
                media=media_result,
                entity_id=payload.get("entity_id"),
                timestamp=now,
            )
        except Exception as exc:
            # Memory must never make the WhatsApp reply unavailable.
            conv["daily_memory"] = {"ok": False, "error": "memory_bridge_unavailable", "detail": str(exc)[:180]}
        wa = None
        if conv.get("text"):
            wa = _send_whatsapp_reply(
                conv["text"],
                number=_normalize_phone(sender),
                node=node,
                reply_audio=(media_kind == "audio"),
            )
        return {"ok": True, "event": event_out, "action": "conversational_reply", "conversation": conv, "auto_reply": wa}
    return {"ok": True, "event": event_out, "action": "captured"}
def create_reminder(*, body: str, due_at: str | None, target_number: str | None = None, entity_id: str | None = None, source: str = "manual") -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now()
    reminder = {
        "reminder_id": f"rem_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "created_at": now,
        "updated_at": now,
        "status": "pending",
        "source": source,
        "body": body.strip(),
        "due_at": due_at,
        "target_number": (target_number or "").strip(),
        "entity_id": (entity_id or "").strip(),
    }
    db[REMINDER_COL].insert_one(reminder)
    return {"ok": True, "reminder": reminder}
def list_reminders(limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    items = list(db[REMINDER_COL].find({}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(items), "reminders": items}
def run_due_reminders() -> dict[str, Any]:
    db = mongo_store.get_db()
    now = datetime.now(timezone.utc)
    sent = 0
    items = list(db[REMINDER_COL].find({"status": "pending", "due_at": {"$ne": None}}, {"_id": 0}))
    for item in items:
        due_at = item.get("due_at")
        if not due_at:
            continue
        try:
            dt = datetime.fromisoformat(due_at)
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt > now:
            continue
        target = item.get("target_number") or ""
        if not target:
            db[REMINDER_COL].update_one({"reminder_id": item.get("reminder_id")}, {"$set": {"status": "needs_target", "updated_at": _now()}})
            continue
        body = f"⏰ Recordatorio RalfIA\n{item.get('body', '')}"
        res = send_whatsapp(body, number=target)
        patch = {"updated_at": _now(), "last_result": res}
        patch["status"] = "sent" if res.get("ok") else "error"
        if res.get("ok"):
            patch["sent_at"] = _now()
            sent += 1
        db[REMINDER_COL].update_one({"reminder_id": item.get("reminder_id")}, {"$set": patch})
    return {"ok": True, "sent": sent}
