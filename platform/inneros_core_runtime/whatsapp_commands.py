"""Comandos WhatsApp inbound — estado servidor, correos, notificaciones."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store, ralfia_time, whatsapp_identity, whatsapp_service_ops
from raphiia_openai.notifications.email_monitor import trigger_email_poll
from raphiia_openai.notifications.evolution_client import send_whatsapp
from raphiia_openai import whatsapp_queries

UP_STATUSES = frozenset({"up", "unauthorized_alive"})
OPS_READ_COMMANDS = frozenset({"help", "connection", "status", "services", "diagnostic"})

HELP_TEXT = """*RalfIA · Comandos WhatsApp*

Responde con naturalidad (como un agente) o usa comandos:

• *estado* / *servidor* — servicios críticos
• *estado .4* / *estado .5* / *estado de ambos servidores*
• *servicios* — cockpit completo
• *diagnostica MCP en .5* / *logs del Panel en .4* — estado y últimas líneas saneadas
• *guia* / *conexion* — Evolution + Swarm correo
• *correo* — buzones monitoreados
• *correo de [nombre]* — buscar por remitente
• *correo mail_…* — asunto, resumen, acciones y enlace seguro
• *responder mail_…: texto* — prepara respuesta y pide confirmación
• *pago [cliente]* — ej. *pago Riverfront*, *ultimo pago Cafecom*
• *saldo* / *bancos* — cuentas Contífico + saldo
• *saldo pichincha* — saldo de un banco
• *cot cafecom* — COT/FAC Contífico del cliente
• *revisar correo* — forzar IMAP ahora (pide confirmación)
• *notificaciones* — últimas alertas
• *pendientes* / *proyectos* — backlog de ideas y tareas
• *desarrolla 3* — asignar item #3 a agentes (Cursor/Codex/local)
• *local: guardian* — agente local inmediato
• *ayuda* — este menú

*Operaciones:*
• *recupera MCP en .5* — propone recuperación y pide confirmación
• *reinicia el Panel en .4* — operación tipada, nunca shell libre
• *confirmar ABC123* — confirma desde el mismo número y chat (3 minutos)
• `cheque:` / `ap:` / `pagar:` — cuenta por pagar
• `recordatorio:` — recordatorio con fecha
• `PCD-COT-…` — seguimiento cotización"""

# Orden: patrones más específicos primero
_COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^¿?qu[eé]\s+comandos\s+(?:puedes|pod[eé]s)\s+ejecutar\b", re.I), "help"),
    (re.compile(r"^(ayuda|help|comandos|menu|menú)\b", re.I), "help"),
    (re.compile(r"^(?:m[aá]s|otras?)\s+opciones\b|^men[uú]\s+avanzado\b", re.I), "menu_more"),
    (re.compile(r"^(?:solicitud\s+personalizada|otra\s+solicitud)\b", re.I), "custom_prompt"),
    (re.compile(r"^(guia|guía|conexion|conexión|ralf)\b", re.I), "connection"),
    (re.compile(r"^(?:logs?|registros?|diagnostica|diagnosticar|diagn[oó]stico)\s+(.+)$", re.I), "diagnostic"),
    (
        re.compile(
            r"^(?:¿?puedes\s+|¿?podr[ií]as\s+)?(?:revisar|ver|diagnosticar)\s+"
            r"(?:qu[eé]\s+(?:es\s+)?(?:lo\s+)?que\s+pasa|qu[eé]\s+problema\s+(?:hay|tiene))\s+con\s+(.+)$",
            re.I,
        ),
        "diagnostic",
    ),
    (
        re.compile(
            r"^(?:quiero\s+que\s+|¿?puedes\s+|¿?podr[ií]as\s+)?(?:me\s+)?"
            r"(?:digas?|muestres?|revises?)\s+(?:el\s+)?estado\s+(?:de\s+)?(?:los\s+dos\s+)?servidores\b(.*)$",
            re.I,
        ),
        "status",
    ),
    (re.compile(r"^(?:estado|status|servidor|server|health)\b(.*)$", re.I), "status"),
    (re.compile(r"^(?:servicios|services|cockpit)\b(.*)$", re.I), "services"),
    (re.compile(r"^correo\s+de\s+(.+)", re.I), "email_from"),
    (re.compile(r"^(?:ver\s+)?correo\s+(mail_[a-z0-9_-]+)\s*$", re.I), "email_detail"),
    (re.compile(r"^(?:responder|responde)\s+(?:correo\s+)?(mail_[a-z0-9_-]+\s*:\s*.+)$", re.I | re.S), "email_reply"),
    (re.compile(r"^(revisar\s+correo|poll\s+correo|poll)\b", re.I), "poll"),
    (re.compile(r"^(correo|correos|emails?|mail)\b", re.I), "emails"),
    (re.compile(r"^(?:ultimo\s+pago|último\s+pago|pago|pagos)\s+(.+)", re.I), "payment"),
    (re.compile(r"^(?:saldo|bancos?)(?:\s+(.+))?$", re.I), "bank_balance"),
    (re.compile(r"^(?:cot|cotizacion|cotización|contifico)\s+(.+)", re.I), "contifico_client"),
    (re.compile(r"^(?:pendientes|proyectos|backlog|ideas|olvidados?)\b", re.I), "backlog"),
    (re.compile(r"^(?:desarrolla|haz|asigna|ejecuta)\s+(?:el\s+|la\s+|#)?(\d+)\b", re.I), "backlog_dispatch"),
    (re.compile(r"^local:\s*(\w+)(?:\s+(.+))?$", re.I | re.S), "backlog_local"),
    (re.compile(r"^(notificaciones|alertas|avisos)\b", re.I), "notifications"),
]


def _normalize_phone(value: str) -> str:
    digits = "".join(c for c in value if c.isdigit())
    if digits.startswith("0") and len(digits) > 10:
        digits = digits.lstrip("0")
    return digits


def is_authorized_sender(sender: str) -> bool:
    identity = whatsapp_identity.resolve_identity(sender)
    return whatsapp_identity.has_scope(identity, "whatsapp:read")


def parse_maintenance_request(message: str, *, default_node: str = "primary") -> dict[str, str] | None:
    text = (message or "").strip()
    match = re.match(
        r"^(reinicia|reiniciar|recupera|recuperar|inicia|iniciar|arranca|arrancar)\s+(?:el\s+|la\s+)?(.+)$",
        text,
        re.I | re.S,
    )
    if not match:
        return None
    verb = match.group(1).lower()
    service = whatsapp_service_ops.service_from_text(match.group(2))
    if not service:
        return {"error": "service_not_allowlisted"}
    action = "restart" if verb.startswith("rein") else ("start" if verb.startswith(("ini", "arr")) else "recover")
    return {
        "action": action,
        "service": service.service_id,
        "node": whatsapp_service_ops.node_from_text(match.group(2), default=default_node),
    }


def parse_command(message: str) -> tuple[str | None, str]:
    text = (message or "").strip()
    if not text:
        return None, ""
    for pattern, cmd in _COMMAND_PATTERNS:
        m = pattern.search(text)
        if m:
            arg = m.group(1).strip() if m.lastindex else ""
            return cmd, arg
    return None, ""


def detect_command(message: str) -> str | None:
    cmd, _ = parse_command(message)
    return cmd


def _status_icon(health: str) -> str:
    return "🟢" if health in UP_STATUSES else "🔴"


def format_server_status_text() -> str:
    return whatsapp_service_ops.format_status_text()


def format_services_text() -> str:
    # Compatibilidad: nunca construir una segunda fotografía de salud.
    return whatsapp_service_ops.format_status_text()


def format_emails_text() -> str:
    from raphiia_openai.notifications import email_review

    return email_review.format_inbox_text(limit=5)


def format_notifications_text() -> str:
    db = mongo_store.get_db()
    events = list(
        db.ralfia_coordination_log.find(
            {
                "event": {
                    "$in": [
                        "email_alert",
                        "coord_alert",
                        "health_watch",
                        "notify_skip",
                        "email_poll_manual",
                    ]
                }
            },
            {"_id": 0, "agent": 1, "summary": 1, "event": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .limit(8)
    )
    lines = [
        "*RalfIA · Notificaciones recientes*",
        ralfia_time.format_log(),
        "",
    ]
    if not events:
        lines.append("Sin alertas registradas recientemente.")
    else:
        for ev in events:
            ts = (ev.get("created_at") or "")[:16].replace("T", " ")
            lines.append(f"• [{ts}] {ev.get('summary', ev.get('event', ''))[:120]}")
    return "\n".join(lines)


def execute_command(message: str) -> dict[str, Any]:
    """Ejecuta comando según mensaje completo."""
    cmd, arg = parse_command(message)
    if not cmd:
        return {"ok": False, "error": "comando desconocido"}
    if cmd == "help":
        text = (
            "*RalfIA · Menú principal*\n\n"
            "Elige una opción o escribe/habla con tus propias palabras:\n"
            "1. Estado de los servidores\n"
            "2. Revisar correos\n"
            "3. Más opciones\n\n"
            "También puedes decir directamente qué necesitas."
        )
        return {
            "ok": True,
            "command": cmd,
            "text": text,
            "interactive": {
                "kind": "buttons",
                "buttons": [
                    {"id": "menu.status", "label": "Estado"},
                    {"id": "menu.email", "label": "Correos"},
                    {"id": "menu.more", "label": "Más opciones"},
                ],
                "fallback_text": text + "\n\nEscribe *estado*, *correo* o *más opciones*.",
            },
        }
    if cmd == "menu_more":
        text = (
            "*RalfIA · Más opciones*\n\n"
            "1. Ver todos los servicios\n"
            "2. Ver notificaciones\n"
            "3. Solicitud personalizada"
        )
        return {
            "ok": True,
            "command": cmd,
            "text": text,
            "interactive": {
                "kind": "buttons",
                "buttons": [
                    {"id": "menu.services", "label": "Servicios"},
                    {"id": "menu.notifications", "label": "Notificaciones"},
                    {"id": "menu.custom", "label": "Personalizado"},
                ],
                "fallback_text": text + "\n\nEscribe *servicios*, *notificaciones* o *solicitud personalizada*.",
            },
        }
    if cmd == "custom_prompt":
        return {
            "ok": True,
            "command": cmd,
            "text": (
                "Dime por texto o audio qué necesitas. Puedo consultar, diagnosticar, revisar correos, "
                "crear trabajo para un agente o proponer mantenimiento seguro. Si implica un cambio, "
                "primero mostraré la acción y pediré confirmación."
            ),
        }
    if cmd == "connection":
        return {"ok": True, "command": cmd, "text": whatsapp_queries.format_connection_status_text()}
    if cmd == "status":
        lowered = (message or "").lower()
        explicit_node = bool(re.search(r"(?:servidor\s*(?:4|5|\.4|\.5|1\.4|1\.5)\b|(?:\.4|1\.4|192\.168\.1\.4|principal|\.5|1\.5|192\.168\.1\.5|amd|backup)\b)", lowered))
        selected = whatsapp_service_ops.node_from_text(message) if explicit_node else None
        snapshot = whatsapp_service_ops.status_snapshot(selected)
        return {
            "ok": True,
            "command": cmd,
            "node": selected or "all",
            "text": whatsapp_service_ops.format_status_text(selected, snapshot=snapshot),
            "snapshot": snapshot,
            "checked_at": snapshot.get("checked_at"),
            "source": snapshot.get("source"),
            "evidence_ref": snapshot.get("evidence_ref"),
            "tool_call_id": snapshot.get("tool_call_id"),
        }
    if cmd == "services":
        lowered = (message or "").lower()
        explicit_node = bool(re.search(r"(?:servidor\s*(?:4|5|\.4|\.5|1\.4|1\.5)\b|(?:\.4|1\.4|192\.168\.1\.4|principal|\.5|1\.5|192\.168\.1\.5|amd|backup)\b)", lowered))
        selected = whatsapp_service_ops.node_from_text(message) if explicit_node else None
        snapshot = whatsapp_service_ops.status_snapshot(selected)
        return {
            "ok": True,
            "command": cmd,
            "node": selected or "all",
            "text": whatsapp_service_ops.format_status_text(selected, snapshot=snapshot),
            "snapshot": snapshot,
            "checked_at": snapshot.get("checked_at"),
            "source": snapshot.get("source"),
            "evidence_ref": snapshot.get("evidence_ref"),
            "tool_call_id": snapshot.get("tool_call_id"),
        }
    if cmd == "diagnostic":
        spec = whatsapp_service_ops.service_from_text(message)
        if not spec:
            return {"ok": False, "command": cmd, "error": "service_not_allowlisted", "text": "Ese servicio no pertenece al catálogo seguro."}
        node = whatsapp_service_ops.node_from_text(message)
        status = whatsapp_service_ops.service_status(spec.service_id, node)
        logs = whatsapp_service_ops.recent_logs(spec.service_id, node, lines=20)
        icon = "🟢" if status.get("healthy") else "🔴"
        body = logs.get("logs") or "(sin registros disponibles)"
        text = (
            f"*Diagnóstico {spec.label} · servidor {whatsapp_service_ops.NODE_LABELS[node]}*\n"
            f"{icon} {status.get('system_state', 'unknown')} / {status.get('health', 'unknown')}\n\n"
            f"*Últimas líneas saneadas:*\n```{body[-2400:]}```"
        )
        if status.get("healthy"):
            text += "\n\nEl servicio responde ahora; no recomiendo reiniciarlo ni recuperarlo."
        else:
            text += (
                f"\n\nSiguiente acción disponible: *recupera {spec.label} en "
                f"{whatsapp_service_ops.NODE_LABELS[node]}* (pedirá confirmación)."
            )
        return {
            "ok": bool(status.get("ok")),
            "command": cmd,
            "node": node,
            "service": spec.service_id,
            "text": text,
            "checked_at": status.get("checked_at"),
            "source": status.get("source"),
            "evidence_ref": status.get("evidence_ref"),
        }
    if cmd == "emails":
        return {"ok": True, "command": cmd, "text": format_emails_text()}
    if cmd == "email_detail":
        from raphiia_openai.notifications import email_review

        review = email_review.get_review(arg, hydrate=True)
        return {
            "ok": bool(review.get("ok")),
            "command": cmd,
            "text": email_review.format_review_text(review) if review.get("ok") else "No encontré ese correo.",
            "review": review,
        }
    if cmd == "email_reply":
        from raphiia_openai.notifications import email_review

        mail_id, body = re.split(r"\s*:\s*", arg, maxsplit=1)
        prepared = email_review.prepare_reply(mail_id, body)
        return {
            "ok": bool(prepared.get("ok")),
            "command": cmd,
            "text": prepared.get("preview") or f"No pude preparar la respuesta: {prepared.get('error', 'error')}",
            "pending_payload": prepared.get("payload"),
        }
    if cmd == "email_from":
        return {
            "ok": True,
            "command": cmd,
            "text": whatsapp_queries.format_emails_from_person_text(arg),
            "query": arg,
        }
    if cmd == "payment":
        return {
            "ok": True,
            "command": cmd,
            "text": whatsapp_queries.format_last_payment_text(arg),
            "query": arg,
        }
    if cmd == "bank_balance":
        from raphiia_openai import contifico_ledger

        bal = contifico_ledger.get_bank_account_balance(arg or None)
        if not bal.get("ok"):
            return {"ok": False, "command": cmd, "text": f"No encontré banco «{arg}». Prueba *saldo* o *saldo pichincha*."}
        lines = ["*RalfIA · Bancos Contífico*\n"]
        for a in bal.get("accounts") or []:
            lines.append(
                f"• {a.get('nombre')}: ≈${a.get('saldo_calculado')} "
                f"({a.get('movements_count')} movs, nº {a.get('numero') or '—'})"
            )
        return {"ok": True, "command": cmd, "text": "\n".join(lines), "query": arg}
    if cmd == "contifico_client":
        from raphiia_openai import contifico_normalize
        from datetime import datetime, timezone

        year = datetime.now(timezone.utc).year
        summary = contifico_normalize.get_contifico_client_summary(arg, year=year)
        if not summary.get("ok"):
            return {"ok": False, "command": cmd, "text": f"No encontré cliente Contífico «{arg}»."}
        p = summary.get("persona") or {}
        lines = [f"*Contífico · {p.get('nombre')}* ({year})\n"]
        for b in summary.get("by_type") or []:
            if b.get("documents"):
                lines.append(f"• {b['tipo_documento']}: {b['documents']} docs / ${b['total_amount']}")
        return {"ok": True, "command": cmd, "text": "\n".join(lines), "query": arg}
    if cmd == "poll":
        result = trigger_email_poll()
        text = (
            "*RalfIA · Revisión correo*\n\n"
            f"Cuentas: {result.get('accounts', 0)}\n"
            f"Nuevos: {result.get('new_messages', 0)}\n"
            f"Alertas WhatsApp: {result.get('alerts_sent', 0)}"
        )
        if result.get("errors"):
            text += f"\n⚠️ Errores: {len(result['errors'])}"
        if not result.get("ok"):
            text += f"\n❌ {result.get('error', 'Swarm :8100 no respondió')}"
        return {"ok": bool(result.get("ok", True)), "command": cmd, "text": text, "poll": result}
    if cmd == "notifications":
        return {"ok": True, "command": cmd, "text": format_notifications_text()}
    if cmd in ("backlog", "backlog_dispatch", "backlog_local"):
        from raphiia_openai.agents import ag57_backlog_steward as ag57

        if cmd == "backlog":
            result = ag57.handle_backlog_command("pendientes", "wa-cmd")
        elif cmd == "backlog_dispatch":
            result = ag57.handle_backlog_command(f"desarrolla {arg}", "wa-cmd")
        else:
            result = ag57.handle_backlog_command(f"local: {arg}", "wa-cmd")
        if result:
            return result
    return {"ok": False, "command": cmd, "error": "comando desconocido"}


def handle_inbound_command(
    message: str,
    sender: str,
    *,
    is_group: bool = False,
    group_activated: bool = False,
    node: str = "primary",
    reply: bool = True,
    trace: dict[str, Any] | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any] | None:
    """Si el mensaje es un comando conocido, ejecuta y opcionalmente responde por WA."""
    from raphiia_openai import whatsapp_agent_router
    from raphiia_openai.agents import ag57_backlog_steward as ag57

    sender_norm = _normalize_phone(sender)
    backlog_result = ag57.handle_backlog_command(message, sender_norm)
    if backlog_result:
        if reply and backlog_result.get("text") and sender and not is_group:
            backlog_result["auto_reply"] = send_whatsapp(
                backlog_result["text"], number=sender_norm, node=node
            )
        return {**backlog_result, "command": backlog_result.get("command", "backlog")}
    agent_request = whatsapp_agent_router.parse_request(message)
    codex_confirm = re.fullmatch(r"confirmar\s+codex\s+(cj_[a-z0-9_-]+)", (message or "").strip(), re.I)
    identity = whatsapp_identity.resolve_identity(sender, chat_id=conversation_id, is_group=is_group)
    text_lower = (message or "").strip().lower()
    if agent_request or codex_confirm:
        if not whatsapp_identity.is_owner(identity) or not whatsapp_identity.has_scope(identity, "whatsapp:agent_jobs"):
            return {"ok": False, "command": "agent_job", "error": "unauthorized_sender"}
        if codex_confirm:
            from raphiia_openai import codex_whatsapp_jobs
            result = codex_whatsapp_jobs.confirm_job(sender, codex_confirm.group(1))
        else:
            result = whatsapp_agent_router.route_request(message, sender, node=node, trace=trace)
        if reply and result.get("text") and sender and not is_group:
            result["auto_reply"] = send_whatsapp(result["text"], number=_normalize_phone(sender), node=node)
        return {**result, "command": "agent_job"}
    disk_move_confirm = re.fullmatch(r"confirmar\s+(dm_[a-f0-9]+)", text_lower)
    disk_move_cancel = re.fullmatch(r"cancelar\s+(dm_[a-f0-9]+)", text_lower)
    disk_move_confirm2 = re.fullmatch(r"confirmar\s+movimiento\s+(dm_[a-f0-9]+)", text_lower)
    disk_move_cancel2 = re.fullmatch(r"cancelar\s+movimiento\s+(dm_[a-f0-9]+)", text_lower)
    sandbox_confirm = re.fullmatch(r"confirmar\s+sandbox\s+(sm_[a-f0-9]+)", text_lower)
    sandbox_cancel = re.fullmatch(r"cancelar\s+sandbox\s+(sm_[a-f0-9]+)", text_lower)
    if disk_move_confirm or disk_move_cancel or disk_move_confirm2 or disk_move_cancel2:
        from raphiia_openai import disk_steward

        pid = (disk_move_confirm or disk_move_confirm2 or disk_move_cancel or disk_move_cancel2).group(1)
        if disk_move_confirm or disk_move_confirm2:
            result = disk_steward.confirm_move(sender, pid)
        else:
            result = disk_steward.cancel_move(sender, pid)
        if reply and result.get("text") and sender and not is_group:
            result["auto_reply"] = send_whatsapp(result["text"], number=_normalize_phone(sender), node=node)
        return {**result, "command": "disk_steward"}
    if sandbox_confirm or sandbox_cancel:
        from raphiia_openai import sandbox_steward

        pid = (sandbox_confirm or sandbox_cancel).group(1)
        if sandbox_confirm:
            result = sandbox_steward.confirm_delete(sender, pid)
        else:
            result = sandbox_steward.cancel_delete(sender, pid)
        if reply and result.get("text") and sender and not is_group:
            result["auto_reply"] = send_whatsapp(result["text"], number=_normalize_phone(sender), node=node)
        return {**result, "command": "sandbox_steward"}
    from raphiia_openai import whatsapp_admin_jobs
    install_match = re.fullmatch(r"instalar\s+componente\s*:\s*whatsapp-media-runtime", text_lower)
    maintenance = parse_maintenance_request(message, default_node=node)
    confirm_match = re.fullmatch(r"confirmar(?:\s+(?:instalaci[oó]n|operaci[oó]n))?\s+([a-z0-9_-]+)", text_lower)
    cancel_match = re.fullmatch(r"cancelar(?:\s+(?:instalaci[oó]n|operaci[oó]n))?\s+([a-z0-9_-]+)", text_lower)
    if install_match or maintenance or confirm_match or cancel_match:
        if install_match:
            result = whatsapp_admin_jobs.request_install(sender, node=node, chat_id=conversation_id)
        elif maintenance:
            if maintenance.get("error"):
                result = {"ok": False, "error": maintenance["error"], "text": "Ese servicio no pertenece al catálogo seguro."}
            else:
                result = whatsapp_admin_jobs.request_service_action(
                    sender,
                    chat_id=str(conversation_id or sender),
                    service=maintenance["service"],
                    node=maintenance["node"],
                    action=maintenance["action"],
                    trace=trace,
                )
        elif confirm_match:
            result = whatsapp_admin_jobs.confirm_job(sender, confirm_match.group(1), chat_id=conversation_id)
        else:
            result = whatsapp_admin_jobs.cancel_job(sender, cancel_match.group(1), chat_id=conversation_id)
        if reply and result.get("text") and sender and not is_group:
            result["auto_reply"] = send_whatsapp(result["text"], number=_normalize_phone(sender), node=node)
        return {**result, "command": "admin_job"}
    cmd, _ = parse_command(message)
    if not cmd:
        return None
    group_command_allowed = bool(is_group and group_activated and cmd != "diagnostic")
    owner_allowed = whatsapp_identity.is_owner(identity)
    ops_read_allowed = whatsapp_identity.has_scope(identity, "whatsapp:read") and cmd in OPS_READ_COMMANDS
    if not owner_allowed and not ops_read_allowed and not group_command_allowed:
        if reply and sender and not is_group:
            send_whatsapp(
                "Comandos de servidor solo para números autorizados.",
                number=_normalize_phone(sender),
                node=node,
            )
        return {"ok": False, "command": cmd, "error": "unauthorized_sender", "group_mode": is_group}
    result = execute_command(message)
    if cmd == "email_reply" and result.get("ok") and result.get("pending_payload"):
        scope = {
            "sender": _normalize_phone(sender),
            "conversation_id": str(conversation_id or _normalize_phone(sender)),
        }
        mongo_store.get_db()["whatsapp_pending_actions"].update_one(
            {**scope, "status": "pending"},
            {
                "$set": {
                    **scope,
                    "action": "email_reply",
                    "payload": result["pending_payload"],
                    "preview": result.get("text"),
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
    wa_result = None
    if reply and result.get("text"):
        reply_target = sender if not is_group else sender
        if is_group and not group_command_allowed:
            reply_target = None
        if reply_target:
            wa_result = send_whatsapp(result["text"], number=(sender if is_group and group_command_allowed else _normalize_phone(sender)), node=node)
    return {**result, "auto_reply": wa_result, "group_mode": is_group}


def get_whatsapp_commands_help() -> dict[str, Any]:
    return {
        "ok": True,
        "help_text": HELP_TEXT,
        "commands": [name for _, name in _COMMAND_PATTERNS],
        "authorization": "canonical_verified_identity_registry",
        "note": "Las operaciones y diagnósticos sensibles requieren una identidad owner verificada en un chat 1:1.",
    }
