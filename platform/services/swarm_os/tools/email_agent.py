"""Clasificación de importancia y alertas WhatsApp."""

from __future__ import annotations

import re
from typing import Any

from tools.email_filter_rules import match_always_important, match_junk


def keyword_importance(subject: str, snippet: str, keywords: list[str]) -> str | None:
    text = f"{subject} {snippet}".lower()
    for kw in keywords:
        if kw.lower() in text:
            return "alta"
    return None


def classify_importance(
    subject: str,
    snippet: str,
    from_addr: str,
    keywords: list[str],
    *,
    trusted_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Reglas: confiable → junk → keywords → urgent → Ollama."""
    always, always_reason = match_always_important(
        subject, snippet, from_addr, extra_keywords=keywords, extra_domains=trusted_domains
    )
    if always:
        return {"importance": "alta", "reason": always_reason, "source": "trusted_rules"}

    junk, junk_reason = match_junk(subject, snippet, from_addr)
    if junk:
        return {"importance": "baja", "reason": f"filtro spam ({junk_reason})", "source": "rules"}

    kw_hit = keyword_importance(subject, snippet, keywords)
    if kw_hit:
        return {"importance": kw_hit, "reason": "palabra clave", "source": "rules"}

    urgent = re.search(
        r"urgente|asap|inmediat|vencid|factura|pago|deuda|reclamo|falla|caído|caido",
        f"{subject} {snippet}",
        re.I,
    )
    if urgent:
        return {"importance": "alta", "reason": urgent.group(0), "source": "rules"}

    from tools.ollama_chat import ollama_available, ollama_chat

    if not ollama_available():
        return {"importance": "baja", "reason": "sin clasificador — no alertar", "source": "default"}

    try:
        raw = ollama_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Clasificas correos para PC Doctor Ecuador (ventas, compras, SRI, bancos, clientes). "
                        "Responde SOLO: alta, normal o baja. "
                        "Alta = dinero, SRI, banco, cliente, cotización, compra/venta, depósito, contrato, falla. "
                        "Baja = marketing, redes sociales, newsletters."
                    ),
                },
                {
                    "role": "user",
                    "content": f"De: {from_addr}\nAsunto: {subject}\n{texto_resumen(snippet)}",
                },
            ],
            temperature=0.1,
            timeout=60,
        )
        level = raw.strip().lower().split()[0] if raw else "normal"
        if level not in {"alta", "normal", "baja"}:
            level = "normal"
        return {"importance": level, "reason": "análisis IA", "source": "ollama"}
    except Exception as e:
        return {"importance": "normal", "reason": str(e), "source": "error"}


def texto_resumen(snippet: str) -> str:
    return snippet[:500] if snippet else "(sin cuerpo)"


def suggest_routing(subject: str, snippet: str, from_addr: str) -> dict[str, str]:
    """Sugerencia de destino interno — sin ejecutar acción automática aún."""
    text = f"{subject} {snippet} {from_addr}".lower()
    rules: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
        (("credits", "créditos", "grants", "fondos", "startup", "grinder", "activate", "founders hub", "sponsorship"), "VINCULAR_CREDITOS", "administracion", "credit_applications"),
        (("factura", "comprobante", "nota de crédito", "nota de credito", "autorización sri", "autorizacion sri"), "REGISTRAR_FACTURA", "contabilidad", "ops_invoice_records_internal"),
        (("retención", "retencion", "sri", "ruc", "declaración", "declaracion"), "TRAMITE_SRI", "contabilidad", "ops_invoice_records_internal"),
        (("transferencia", "depósito", "deposito", "extracto", "pago recibido", "cobro"), "REGISTRAR_PAGO", "contabilidad", "ops_invoice_records_internal"),
        (("cotiz", "proforma", "presupuesto", "quote"), "CREAR_COTIZACION", "ventas", "ops_quote_drafts"),
        (("compra", "pedido", "proveedor", "orden de compra"), "REGISTRAR_COMPRA", "compras", "ops_invoice_records_internal"),
        (("reclamo", "garantía", "garantia", "falla", "soporte"), "CREAR_TICKET", "soporte", "ops_tasks_followup"),
        (("visita", "instal", "técnico", "tecnico", "campo"), "AGENDAR_VISITA", "operaciones", "ops_field_visits"),
        (("contrato", "licitación", "licitacion"), "REVISAR_CONTRATO", "legal/comercial", "ops_tasks_followup"),
    )
    for keys, action, area, collection in rules:
        if any(k in text for k in keys):
            return {
                "suggested_action": action,
                "route_area": area,
                "route_collection": collection,
                "action_note": f"→ {area}: {action.replace('_', ' ').title()}",
            }
    return {
        "suggested_action": "REVISAR_MANUAL",
        "route_area": "bandeja",
        "route_collection": "email_messages",
        "action_note": "→ Revisar y clasificar manualmente",
    }


def format_whatsapp_alert(
    account: str,
    subject: str,
    from_addr: str,
    importance: str,
    reason: str,
    *,
    mail_id: str = "",
    view_url: str = "",
    suggested_action: str = "",
    route_area: str = "",
) -> str:
    lines = [
        f"📧 Ralphi IA — correo {importance.upper()}",
        f"Cuenta: {account}",
        f"De: {from_addr}",
        f"Asunto: {subject}",
        f"Motivo: {reason}",
    ]
    if suggested_action and route_area:
        lines.append(f"📋 Acción sugerida: {suggested_action.replace('_', ' ')} → {route_area}")
    if suggested_action == "VINCULAR_CREDITOS":
        lines.append("🔗 Dashboard de Fondos: https://sworn-profusely-alongside.ngrok-free.dev/funding/ui")
    elif mail_id and view_url:
        lines.append(f"🔗 Abrir: {view_url}?mail={mail_id}")
    elif mail_id:
        lines.append(f"ID: {mail_id}")
    return "\n".join(lines)
