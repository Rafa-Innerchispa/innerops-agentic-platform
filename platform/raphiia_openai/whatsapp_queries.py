"""Consultas operativas para comandos WhatsApp (pagos, correos, clientes)."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai import mongo_store


def _sort_key_date(value: str | None) -> str:
    return (value or "0000-00-00").replace("/", "-")


def search_client_documents(client_query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    q = re.escape(client_query.strip())
    if not q:
        return []
    db = mongo_store.get_db()
    return list(
        db.contifico_documents.find(
            {"descripcion": {"$regex": q, "$options": "i"}},
            {
                "_id": 0,
                "documento": 1,
                "descripcion": 1,
                "fecha_emision": 1,
                "fecha_vencimiento": 1,
                "total": 1,
                "estado": 1,
                "cobros": 1,
                "tipo_documento": 1,
            },
        )
        .sort("fecha_emision", -1)
        .limit(max(1, min(limit, 10)))
    )


def format_last_payment_text(client_query: str) -> str:
    docs = search_client_documents(client_query, limit=8)
    if not docs:
        return (
            f"*RalfIA · Pagos {client_query}*\n\n"
            f"No encontré documentos Contifico con «{client_query}».\n"
            "Prueba otro nombre o sincroniza Contifico."
        )
    lines = [f"*RalfIA · Pagos / facturas · {client_query}*", ""]
    paid_any = False
    for doc in docs[:5]:
        cobros = doc.get("cobros") or []
        desc = (doc.get("descripcion") or "")[:80].replace("\r", " ")
        lines.append(
            f"📄 {doc.get('documento', '?')} · {doc.get('fecha_emision', '?')} · "
            f"${doc.get('total', '?')} · estado {doc.get('estado', '?')}"
        )
        lines.append(f"   {desc}")
        if cobros:
            paid_any = True
            last = cobros[-1]
            parts = []
            for key in ("fecha", "monto", "valor", "forma_pago", "referencia"):
                if last.get(key) not in (None, ""):
                    parts.append(f"{key}: {last[key]}")
            lines.append(f"   💰 Último cobro: {', '.join(parts) if parts else str(last)[:120]}")
        else:
            lines.append("   ⏳ Sin cobros registrados en Contifico")
        lines.append("")
    if not paid_any:
        lines.append("_Tip: escribe «correo de " + client_query + "» para buscar en bandeja IMAP._")
    return "\n".join(lines).strip()


def search_emails_from_person(name_query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    q = re.escape(name_query.strip())
    if not q:
        return []
    db = mongo_store.get_db()
    return list(
        db.email_messages.find(
            {
                "$or": [
                    {"from_addr": {"$regex": q, "$options": "i"}},
                    {"subject": {"$regex": q, "$options": "i"}},
                ]
            },
            {
                "_id": 0,
                "mail_id": 1,
                "from_addr": 1,
                "subject": 1,
                "importance": 1,
                "received_at": 1,
                "account_address": 1,
                "view_url": 1,
            },
        )
        .sort("received_at", -1)
        .limit(max(1, min(limit, 10)))
    )


def format_emails_from_person_text(name_query: str) -> str:
    items = search_emails_from_person(name_query)
    lines = [f"*RalfIA · Correos de «{name_query}»*", ""]
    if not items:
        lines.append("Sin correos en Mongo con ese remitente/asunto.")
        lines.append("Escribe «revisar correo» para forzar poll IMAP.")
        return "\n".join(lines)
    for msg in items[:5]:
        subj = (msg.get("subject") or "(sin asunto)")[:70]
        frm = (msg.get("from_addr") or "?")[:50]
        imp = msg.get("importance", "?")
        lines.append(f"• [{imp}] {subj}")
        lines.append(f"  De: {frm}")
    return "\n".join(lines)


def format_connection_status_text() -> str:
    from raphiia_openai.notifications.evolution_client import dual_whatsapp_status
    from raphiia_openai.notifications.settings import SWARM_API_BASE
    from raphiia_openai import ralfia_time

    wa = dual_whatsapp_status()
    lines = ["*RalfIA · Conexión Guía / Evolution*", ralfia_time.format_log(), ""]
    for node, info in wa.items():
        conn = "🟢 conectado" if info.get("connected") else "🔴 desconectado"
        api = "🟢 API" if info.get("api_up") else "🔴 API"
        lines.append(f"{node}: {conn} · {api}")
        lines.append(f"  instancia: {info.get('instance', '?')}")
    lines.append("")
    lines.append(f"Swarm correo: {SWARM_API_BASE}")
    lines.append("Webhook inbound: :2002/api/whatsapp/evolution/webhook")
    lines.append("")
    lines.append("Responde en el chat con *RalfIA* (línea Evolution).")
    lines.append("Comandos: estado · correo · pago Riverfront · ayuda")
    return "\n".join(lines)
