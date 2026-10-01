"""Digest operativo de correo para el owner — acciones concretas, no spam."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-59_EMAIL_DIGEST"
ACTIONS_COL = "ralfia_email_actions"
DIGEST_COL = "ralfia_email_owner_digest"
REPORT_ID = "latest"

HIGH_VALUE_TYPES = frozenset(
    {
        "factura",
        "nota_credito",
        "retencion",
        "estado_cuenta",
        "comprobante_pago",
        "cotizacion_propuesta",
        "lead_cliente",
        "hackathon_funding_credits",
        "servicio_vencimiento",
        "soporte_incidente",
        "contrato_legal",
        "calendario_evento",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _format_fields(fields: dict[str, Any] | None) -> str:
    if not fields:
        return ""
    bits: list[str] = []
    if fields.get("invoice_number"):
        bits.append(f"N° {fields['invoice_number']}")
    if fields.get("total_candidates"):
        bits.append(f"totales {fields['total_candidates'][:3]}")
    if fields.get("ruc_candidates"):
        bits.append(f"RUC {fields['ruc_candidates'][:2]}")
    if fields.get("sri_access_keys"):
        bits.append("clave SRI presente")
    return " · ".join(bits)


def _load_action_rows(*, hours: int, limit: int) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    since = (_now() - timedelta(hours=max(1, hours))).isoformat()
    filt: dict[str, Any] = {
        "status": {"$in": ["pending", "confirmed"]},
        "updated_at": {"$gte": since},
        "priority": {"$in": ["high", "normal"]},
        "document_type": {"$nin": ["spam_newsletter", "fyi"]},
    }
    rows = list(db[ACTIONS_COL].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(10, min(limit, 200))))
    if rows:
        return rows
    # Fallback: high-value pending sin filtro temporal estricto
    filt2: dict[str, Any] = {
        "status": "pending",
        "priority": "high",
        "$or": [
            {"document_type": {"$in": list(HIGH_VALUE_TYPES)}},
            {"category": {"$in": ["factura", "extracto", "pago", "sri_fiscal", "cotizacion", "incidente"]}},
        ],
    }
    return list(db[ACTIONS_COL].find(filt2, {"_id": 0}).sort("updated_at", -1).limit(max(10, min(limit, 80))))


def generate_email_owner_digest(*, hours: int = 24, limit: int = 40) -> dict[str, Any]:
    rows = _load_action_rows(hours=hours, limit=limit)
    by_type = Counter(str(r.get("document_type") or r.get("category") or "?") for r in rows)
    by_agent = Counter(str(r.get("agent_id") or "?") for r in rows)

    lines: list[str] = []
    for row in rows[:25]:
        doc_type = row.get("document_type") or row.get("category") or "?"
        agent = row.get("agent_id") or "?"
        subject = (row.get("subject") or row.get("mail_id") or "")[:72]
        steps = row.get("suggested_actions") or []
        step = steps[0] if steps else (row.get("next_step") or "Revisar")
        extra = _format_fields(row.get("extracted_fields"))
        gate = " [requiere OK humano]" if row.get("requires_human_approval") else ""
        lines.append(f"- **{doc_type}** · {agent}{gate}\n  {subject}\n  → {step}" + (f"\n  {extra}" if extra else ""))

    open_email_ops = mongo_store.get_db()["ralfia_ops_tasks"].count_documents(
        {"status": "queued", "title": {"$regex": r"^\[Correo/"}}
    )

    report_text = (
        f"# Digest correo operativo — {ralfia_time.format_log()}\n\n"
        f"Ventana: {hours}h · ítems accionables: {len(rows)}\n"
        f"Ops correo aún en cola: {open_email_ops}\n\n"
        f"## Por tipo\n"
        + "\n".join(f"- {k}: {v}" for k, v in by_type.most_common(12))
        + f"\n\n## Por agente\n"
        + "\n".join(f"- {k}: {v}" for k, v in by_agent.most_common(10))
        + f"\n\n## Qué hacer\n"
        + ("\n".join(lines) if lines else "- Sin ítems high/normal recientes; revisar bandeja IMAP.")
    )

    result: dict[str, Any] = {
        "ok": True,
        "agent_id": AGENT_ID,
        "hours": hours,
        "item_count": len(rows),
        "by_document_type": dict(by_type.most_common(20)),
        "by_agent": dict(by_agent.most_common(15)),
        "open_email_ops_queued": open_email_ops,
        "report_text": report_text,
        "items": rows[:30],
        "generated_at": _now().isoformat(),
    }

    mongo_store.get_db()[DIGEST_COL].update_one(
        {"_id": REPORT_ID},
        {"$set": {**result, "updated_at": _now().isoformat()}},
        upsert=True,
    )
    record_agent_run(
        AGENT_ID,
        action="email_owner_digest",
        summary=f"items={len(rows)} queued_email_ops={open_email_ops}",
        project="ralfia-email",
        mirror_feed=True,
    )
    return result


def deliver_email_owner_digest(*, hours: int = 24, limit: int = 40, whatsapp: bool = True) -> dict[str, Any]:
    digest = generate_email_owner_digest(hours=hours, limit=limit)
    delivered = False
    if whatsapp:
        try:
            from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
            from raphiia_openai import whatsapp_identity

            text = digest.get("report_text", "")[:3500]
            for number in whatsapp_identity.notification_destinations()[:1]:
                if send_alert_whatsapp(text, number=number).get("ok"):
                    delivered = True
        except Exception as exc:
            digest["whatsapp_error"] = str(exc)[:180]
    digest["whatsapp_delivered"] = delivered
    return digest
