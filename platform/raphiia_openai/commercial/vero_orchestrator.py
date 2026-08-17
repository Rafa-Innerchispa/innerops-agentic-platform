"""Vero (AG-38) — orquestadora comercial multicanal.

Punto único de entrada: cotizar, facturar, informe técnico, entrega.
Delega a AG-13 (informe campo), AG-16 (COT), AG-17 (FAC Contifico),
AG-10 (firma SRI), AG-18 (cobros).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action

VERO_AGENT_ID = "AG-38"
VERO_DISPLAY_NAME = "Vero"
VERO_ALIASES = frozenset({"vero", "facturador", "facturadora", "comercial"})

COMMERCIAL_DELEGATES: dict[str, dict[str, str]] = {
    "technical_report": {
        "agent_id": "AG-13",
        "name": "voice_inspection_extractor",
        "role": "Informe técnico de campo / inspección por voz",
    },
    "supervisor_report": {
        "agent_id": "AG-13",
        "name": "supervisor_report",
        "role": "Informe supervisor consolidado (visitas, activos, hallazgos)",
    },
    "quote": {
        "agent_id": "AG-16",
        "name": "quote_calculator",
        "role": "Cotización comercial PCD-COT-*",
    },
    "invoice": {
        "agent_id": "AG-17",
        "name": "contifico_billing_bridge",
        "role": "Facturación fiscal Contifico / SRI",
    },
    "fiscal_sign": {
        "agent_id": "AG-10",
        "name": "fiscal_signer",
        "role": "Firma XML XAdES-BES",
    },
    "collections": {
        "agent_id": "AG-18",
        "name": "collections_tracker",
        "role": "Seguimiento de cobros post-factura",
    },
    "crm": {
        "agent_id": "AG-14",
        "name": "crm_client_onboarder",
        "role": "Alta y validación de clientes",
    },
}

COL_COMMERCIAL_MISSIONS = "ralfia_commercial_missions"

INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("invoice", re.compile(r"\b(factur|factura|fac\b|emitir\s+factura|invoice)\b", re.I)),
    ("quote", re.compile(r"\b(cotiz|presupuesto|propuesta\s+comercial|quote)\b", re.I)),
    (
        "technical_report",
        re.compile(r"\b(informe\s+t[eé]cnico|reporte\s+t[eé]cnico|inspecci[oó]n|diagn[oó]stico\s+t[eé]cnico)\b", re.I),
    ),
    ("deliver", re.compile(r"\b(env[ií]a|manda|whatsapp|entrega)\b.*\b(cotiz|pdf|documento)\b", re.I)),
    ("status", re.compile(r"\b(estado|seguimiento|ticket)\b.*\b(cotiz|factura|pcD-)\b", re.I)),
]

# "avero" incluido solo por errores de voz/STT
VERO_PREFIX_RE = re.compile(
    r"(?:dile\s+a\s+|p[ií]dele\s+a\s+|por\s+favor\s+)?"
    r"(?:vero|avero|facturador[a]?)\s+(?:que\s+)?",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _mission_id() -> str:
    return f"cm_{uuid.uuid4().hex[:16]}"


def _strip_vero_prefix(text: str) -> str:
    return VERO_PREFIX_RE.sub("", text or "", count=1).strip()


def detect_intent(message: str) -> str:
    cleaned = _strip_vero_prefix(message)
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(cleaned):
            return intent
    if VERO_PREFIX_RE.search(message or ""):
        return "quote"
    if re.search(r"\b(vero|facturador)\b", message or "", re.I):
        return "quote"
    return "unknown"


def mentions_vero(message: str) -> bool:
    text = (message or "").lower()
    return bool(VERO_PREFIX_RE.search(message or "")) or any(alias in text for alias in VERO_ALIASES)


def _extract_client_ref(message: str) -> str | None:
    cleaned = _strip_vero_prefix(message)
    patterns = [
        r"(?:cliente|para|a)\s+([A-Za-zÁÉÍÓÚáéíóúÑñ0-9 .&\-]{2,60}?)(?:\s+(?:por|de|con|factur|cotiz|informe)|$|[,.])",
        r"\b(FEMAR|Bellini|Cafecom|Riverfront|ASOPAR)\b",
        r"(PCD-COT[-\d]+|quotedraft_[a-f0-9]+)",
    ]
    for pat in patterns:
        match = re.search(pat, cleaned, re.I)
        if match:
            ref = match.group(1).strip(" .,")
            if ref and ref.lower() not in {"vero", "avero", "facturador", "cliente", "este", "esa"}:
                return ref
    return None


def _extract_quote_ref(message: str) -> str | None:
    cleaned = _strip_vero_prefix(message)
    for pat in (r"(PCD-COT[-\d]+)", r"(quotedraft_[a-f0-9]+)", r"(COT-\d{12,})"):
        match = re.search(pat, cleaned, re.I)
        if match:
            return match.group(1)
    return None


def _extract_amount(message: str) -> float | None:
    match = re.search(r"\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)", message or "")
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _save_mission(doc: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    db[COL_COMMERCIAL_MISSIONS].insert_one(doc)
    return doc


def _resolve_client(client_ref: str) -> dict[str, Any]:
    from raphiia_openai import pcdoctor_store

    return pcdoctor_store.resolve_client(client_ref, limit=5)


def _find_quote_for_client(client_id: str, quote_ref: str | None = None) -> dict[str, Any] | None:
    from raphiia_openai.operational.constants import COL_OPS_QUOTE_DRAFTS

    db = _db()
    if quote_ref:
        doc = db[COL_OPS_QUOTE_DRAFTS].find_one(
            {
                "$or": [
                    {"quote_id": quote_ref},
                    {"display_number": quote_ref},
                    {"dedupe_key": quote_ref},
                ]
            }
        )
        if doc:
            return dict(doc)
    doc = db[COL_OPS_QUOTE_DRAFTS].find_one(
        {"client_id": client_id},
        sort=[("updated_at", -1)],
    )
    return dict(doc) if doc else None


def _wants_duplicate(message: str) -> bool:
    return bool(re.search(r"\b(duplica|duplicar|copia(r)?\s+la\s+cotiz|usa(r)?\s+la\s+cotiz)\b", message or "", re.I))


def _wants_confirm_quote(message: str) -> bool:
    return bool(re.search(
        r"\b(arma(r)?\s+la\s+cotiz|confirmo|con\s+stock|genera(r)?\s+cotiz|listo\s+cotiz)\b",
        message or "",
        re.I,
    ))


def vero_proactive_briefing(
    *,
    message: str,
    client_ref: str,
    entity_id: str = "ent_pcdoctor",
) -> dict[str, Any]:
    """Briefing proactivo: stock, cotizaciones previas, upsell, preguntas."""
    from raphiia_openai.commercial import vero_proactive_advisor

    resolved = _resolve_client(client_ref)
    if not resolved.get("ok") or not resolved.get("matches"):
        return {"ok": False, "error": "client_not_found", "client_ref": client_ref}
    client = resolved["matches"][0]
    briefing = vero_proactive_advisor.build_proactive_briefing(
        message=message,
        client_id=_norm(client.get("client_id")),
        client_name=_norm(client.get("display_name") or client_ref),
    )
    briefing["agent"] = VERO_DISPLAY_NAME
    briefing["client_ref"] = client_ref
    briefing["client_id"] = _norm(client.get("client_id"))
    briefing["reply_text"] = vero_proactive_advisor.format_proactive_reply(briefing)
    return briefing


def quote_client(
    *,
    client_ref: str,
    message: str = "",
    entity_id: str = "ent_pcdoctor",
    channel: str = "mcp",
    quote_ref: str | None = None,
    line_items: list[dict[str, Any]] | None = None,
    send_whatsapp: bool = False,
    phone: str | None = None,
) -> dict[str, Any]:
    """Delega cotización a AG-16 / perfil quoter — modo proactivo."""
    from raphiia_openai.commercial import vero_proactive_advisor

    mission_id = _mission_id()
    resolved = _resolve_client(client_ref)
    if not resolved.get("ok") or not resolved.get("matches"):
        return {
            "ok": False,
            "error": "client_not_found",
            "client_ref": client_ref,
            "mission_id": mission_id,
            "delegate": COMMERCIAL_DELEGATES["quote"],
        }
    client = resolved["matches"][0]
    client_id = _norm(client.get("client_id"))
    client_name = _norm(client.get("display_name") or client_ref)

    briefing = vero_proactive_advisor.build_proactive_briefing(
        message=message,
        client_id=client_id,
        client_name=client_name,
    )

    # Duplicar cotización previa/similar
    if _wants_duplicate(message) and briefing.get("duplicate_candidate"):
        dup_id = briefing["duplicate_candidate"].get("quote_id")
        if dup_id:
            created = vero_proactive_advisor.duplicate_quote_for_client(
                dup_id,
                client_id=client_id,
                client_name=client_name,
                message=message,
                entity_id=entity_id,
            )
            if created.get("ok"):
                quote = created.get("quote_draft") or {}
                result = {
                    "ok": True,
                    "action": "quote_duplicated",
                    "quote_id": quote.get("quote_id"),
                    "display_number": quote.get("display_number"),
                    "total": quote.get("total"),
                    "duplicated_from": dup_id,
                    "proactive": briefing,
                }
                if send_whatsapp and result.get("quote_id"):
                    from raphiia_openai.operational.quote_delivery import send_quote_delivery
                    result["delivery"] = send_quote_delivery(result["quote_id"], channels=["whatsapp"], phone=phone)
                _save_mission({
                    "mission_id": mission_id, "intent": "quote", "status": "completed",
                    "agent": VERO_AGENT_ID, "delegate": COMMERCIAL_DELEGATES["quote"],
                    "client_ref": client_ref, "client_id": client_id, "channel": channel,
                    "message": message[:2000], "result": result,
                    "created_at": _now_iso(), "updated_at": _now_iso(),
                })
                result["mission_id"] = mission_id
                result["agent"] = VERO_DISPLAY_NAME
                result["reply_text"] = (
                    f"Dupliqué `{result.get('display_number')}` desde cotización previa. "
                    f"Total ${result.get('total', 0):,.2f}. Revisa líneas antes de enviar."
                )
                return result

    existing = _find_quote_for_client(client_id, quote_ref) if quote_ref else None

    if existing and quote_ref:
        quote_id = _norm(existing.get("quote_id"))
        result = {
            "ok": True,
            "action": "quote_existing",
            "quote_id": quote_id,
            "display_number": existing.get("display_number"),
            "total": existing.get("total"),
            "status": existing.get("status"),
        }
    else:
        use_lines = line_items
        auto_from_prior = (
            briefing.get("duplicate_candidate")
            and briefing.get("ready_to_quote")
            and not briefing.get("categories")
            and not _wants_confirm_quote(message)
            and not line_items
        )
        if not use_lines and (_wants_confirm_quote(message) or _wants_duplicate(message)):
            use_lines = briefing.get("suggested_line_items") or []
        # Duplicar automáticamente si hay cotización previa del cliente y el mensaje es genérico
        if auto_from_prior and briefing.get("duplicate_candidate"):
            dup_id = briefing["duplicate_candidate"].get("quote_id")
            if dup_id and briefing["duplicate_candidate"].get("source") == "client_prior":
                created = vero_proactive_advisor.duplicate_quote_for_client(
                    dup_id, client_id=client_id, client_name=client_name, message=message, entity_id=entity_id,
                )
                if created.get("ok"):
                    quote = created.get("quote_draft") or {}
                    result = {
                        "ok": True, "action": "quote_duplicated_auto",
                        "quote_id": quote.get("quote_id"), "display_number": quote.get("display_number"),
                        "total": quote.get("total"), "duplicated_from": dup_id, "proactive": briefing,
                        "reply_text": (
                            f"Encontré cotización previa `{quote.get('display_number')}` — la dupliqué como base "
                            f"(${quote.get('total', 0):,.2f}). Dime qué ajustar o confirma envío."
                        ),
                    }
                    _save_mission({
                        "mission_id": mission_id, "intent": "quote", "status": "completed",
                        "agent": VERO_AGENT_ID, "delegate": COMMERCIAL_DELEGATES["quote"],
                        "client_ref": client_ref, "client_id": client_id, "channel": channel,
                        "message": message[:2000], "result": result,
                        "created_at": _now_iso(), "updated_at": _now_iso(),
                    })
                    result["mission_id"] = mission_id
                    result["agent"] = VERO_DISPLAY_NAME
                    return result

        # Modo proactivo: no crear borrador vacío — devolver briefing y preguntas
        if not use_lines and not _extract_amount(message):
            reply = vero_proactive_advisor.format_proactive_reply(briefing)
            _save_mission({
                "mission_id": mission_id,
                "intent": "quote",
                "status": "needs_input",
                "agent": VERO_AGENT_ID,
                "delegate": COMMERCIAL_DELEGATES["quote"],
                "client_ref": client_ref,
                "client_id": client_id,
                "channel": channel,
                "message": message[:2000],
                "proactive_briefing": {
                    "categories": briefing.get("categories"),
                    "questions": briefing.get("proactive_questions"),
                    "stock_count": len(briefing.get("stock") or []),
                },
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
            return {
                "ok": True,
                "action": "proactive_briefing",
                "status": "needs_input",
                "mission_id": mission_id,
                "agent": VERO_DISPLAY_NAME,
                "agent_id": VERO_AGENT_ID,
                "delegate": COMMERCIAL_DELEGATES["quote"],
                "client_id": client_id,
                "proactive": briefing,
                "reply_text": reply,
            }

        from raphiia_openai import pcdoctor_store

        payload: dict[str, Any] = {
            "client_id": client_id,
            "title": f"Cotización {client.get('display_name') or client_ref}",
            "notes": message[:2000] or f"Solicitud vía {channel}",
            "entity_id": entity_id,
            "numbering_namespace": "ralfia",
            "status": "draft",
        }
        if use_lines:
            payload["line_items"] = use_lines
        amount = _extract_amount(message)
        if amount and not use_lines:
            payload["line_items"] = [
                {"description": message[:200] or "Servicio solicitado", "quantity": 1, "unit_price": amount}
            ]
        created = pcdoctor_store.create_quote_draft(payload)
        if not created.get("ok"):
            return {**created, "mission_id": mission_id, "delegate": COMMERCIAL_DELEGATES["quote"]}
        quote = created.get("quote_draft") or {}
        quote_id = _norm(quote.get("quote_id"))
        result = {
            "ok": True,
            "action": "quote_created",
            "quote_id": quote_id,
            "display_number": quote.get("display_number"),
            "total": quote.get("total"),
            "status": quote.get("status"),
            "proactive": briefing if briefing.get("categories") else None,
        }

    if send_whatsapp and result.get("quote_id"):
        from raphiia_openai.operational.quote_delivery import send_quote_delivery

        result["delivery"] = send_quote_delivery(
            result["quote_id"],
            channels=["whatsapp"],
            phone=phone,
        )

    _save_mission(
        {
            "mission_id": mission_id,
            "intent": "quote",
            "status": "completed" if result.get("ok") else "failed",
            "agent": VERO_AGENT_ID,
            "delegate": COMMERCIAL_DELEGATES["quote"],
            "client_ref": client_ref,
            "client_id": client_id,
            "channel": channel,
            "message": message[:2000],
            "result": result,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    )
    log_ops_action(
        actor=VERO_AGENT_ID,
        action="quote_client",
        resource_type="commercial_mission",
        resource_id=mission_id,
        summary=f"Vero cotización {client_ref}",
        tool_used="quote_client",
        metadata={"quote_id": result.get("quote_id"), "channel": channel},
    )
    return {
        "ok": True,
        "mission_id": mission_id,
        "agent": VERO_DISPLAY_NAME,
        "agent_id": VERO_AGENT_ID,
        "delegate": COMMERCIAL_DELEGATES["quote"],
        **result,
    }


def invoice_client(
    *,
    client_ref: str,
    quote_ref: str | None = None,
    entity_id: str = "ent_pcdoctor",
    channel: str = "mcp",
    require_approval: bool = True,
    approved_by: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    """Delega facturación a AG-17. Crea AR; emisión Contifico con gate de aprobación."""
    from raphiia_openai.operational import accounting_store

    mission_id = _mission_id()
    resolved = _resolve_client(client_ref)
    if not resolved.get("ok") or not resolved.get("matches"):
        return {
            "ok": False,
            "error": "client_not_found",
            "client_ref": client_ref,
            "mission_id": mission_id,
            "delegate": COMMERCIAL_DELEGATES["invoice"],
        }
    client = resolved["matches"][0]
    client_id = _norm(client.get("client_id"))

    try:
        from raphiia_openai.agents import ag17_contifico_bridge_agent as ag17_fiscal

        fiscal = ag17_fiscal.validate_client_fiscal(client)
        if not fiscal.get("ok"):
            return {
                "ok": False,
                "error": "fiscal_validation_failed",
                "fiscal": fiscal,
                "client_ref": client_ref,
                "client_id": client_id,
                "mission_id": mission_id,
                "delegate": COMMERCIAL_DELEGATES["invoice"],
            }
    except Exception:
        fiscal = None

    quote_ref = quote_ref or _extract_quote_ref(message)
    quote_doc = _find_quote_for_client(client_id, quote_ref)
    if not quote_doc:
        return {
            "ok": False,
            "error": "quote_not_found",
            "client_ref": client_ref,
            "client_id": client_id,
            "detail": "Necesito una cotización aprobada (PCD-COT-* o quotedraft_*) antes de facturar.",
            "mission_id": mission_id,
            "delegate": COMMERCIAL_DELEGATES["invoice"],
        }
    quote_id = _norm(quote_doc.get("quote_id"))
    quote_status = str(quote_doc.get("status", "")).lower()

    from raphiia_openai.operational import billing_pipeline

    if require_approval and not approved_by:
        if quote_status not in ("approved", "sent", "accepted"):
            return {
                "ok": False,
                "error": "quote_approval_required",
                "quote_id": quote_id,
                "status": quote_status,
                "mission_id": mission_id,
                "delegate": COMMERCIAL_DELEGATES["invoice"],
                "detail": "Aprueba la cotización y confirma con approved_by='RAFAEL' para generar factura borrador + AR.",
            }
        emit_result: dict[str, Any] = {
            "ok": False,
            "status": "pending_approval",
            "phase": "quote_ready",
            "message": "Cotización lista. Confirma con approved_by='RAFAEL' para factura borrador + contabilidad.",
        }
        return {
            "ok": False,
            "mission_id": mission_id,
            "agent": VERO_AGENT_ID,
            "delegate": COMMERCIAL_DELEGATES["invoice"],
            "quote_id": quote_id,
            "display_number": quote_doc.get("display_number"),
            "approval_required": True,
            "fiscal": fiscal,
            "pending_emit": emit_result,
        }

    prep = billing_pipeline.prepare_invoice_from_quote(
        quote_id,
        approved_by=approved_by or "RAFAEL",
        auto_approve=quote_status not in ("approved", "sent", "accepted"),
        entity_id=entity_id,
    )
    if not prep.get("ok"):
        return {**prep, "mission_id": mission_id, "delegate": COMMERCIAL_DELEGATES["invoice"]}

    receivable_id = prep.get("receivable_id")
    emit_result = emit_contifico_invoice(
        receivable_id or "",
        quote_id=quote_id,
        entity_id=entity_id,
        approved_by=approved_by or "RAFAEL",
    )

    _save_mission(
        {
            "mission_id": mission_id,
            "intent": "invoice",
            "status": "completed" if prep.get("ok") else "blocked",
            "agent": VERO_AGENT_ID,
            "delegate": COMMERCIAL_DELEGATES["invoice"],
            "client_ref": client_ref,
            "client_id": client_id,
            "quote_id": quote_id,
            "receivable_id": receivable_id,
            "invoice_record_id": prep.get("invoice_record_id"),
            "channel": channel,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    )
    log_ops_action(
        actor=VERO_AGENT_ID,
        action="invoice_client",
        resource_type="commercial_mission",
        resource_id=mission_id,
        summary=f"Vero facturación {client_ref}",
        tool_used="invoice_client",
        metadata={"quote_id": quote_id, "receivable_id": receivable_id, "channel": channel},
    )
    return {
        "ok": True,
        "mission_id": mission_id,
        "agent": VERO_DISPLAY_NAME,
        "agent_id": VERO_AGENT_ID,
        "delegate": COMMERCIAL_DELEGATES["invoice"],
        "quote_id": quote_id,
        "display_number": quote_doc.get("display_number"),
        "receivable_id": receivable_id,
        "billing_pipeline": prep,
        "fiscal": prep.get("fiscal_validation") or fiscal,
        "sri_emit": emit_result,
        "document_status": prep.get("document_status"),
        "internal_number": prep.get("internal_number"),
    }


def emit_contifico_invoice(
    receivable_id: str,
    *,
    quote_id: str | None = None,
    entity_id: str = "ent_pcdoctor",
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Emisión FAC Contifico — requiere CONTIFICO_WRITE_ENABLED=1 y aprobación."""
    write_enabled = os.getenv("CONTIFICO_WRITE_ENABLED", "0").strip().lower() in ("1", "true", "yes")
    if not approved_by:
        return {
            "ok": False,
            "status": "pending_approval",
            "error": "approval_required",
            "receivable_id": receivable_id,
            "delegate": COMMERCIAL_DELEGATES["invoice"],
            "next_step": "Confirma con approved_by='RAFAEL' vía vero_dispatch o invoice_client",
        }
    if not write_enabled:
        from raphiia_openai import mongo_store
        from raphiia_openai.operational.constants import COL_OPS_INVOICE_RECORDS

        inv = mongo_store.get_db()[COL_OPS_INVOICE_RECORDS].find_one({"receivable_id": receivable_id})
        return {
            "ok": True,
            "status": "ready_for_sri",
            "phase": "document_prepared",
            "receivable_id": receivable_id,
            "quote_id": quote_id,
            "approved_by": approved_by,
            "invoice_record_id": (inv or {}).get("invoice_record_id"),
            "internal_number": (inv or {}).get("internal_number"),
            "delegate": COMMERCIAL_DELEGATES["invoice"],
            "detail": (
                "Factura borrador + AR en contabilidad listos. "
                "Emisión Contifico/SRI pendiente autorización legal (CONTIFICO_WRITE_ENABLED)."
            ),
        }
    return {
        "ok": False,
        "status": "not_implemented",
        "error": "contifico_emit_stub",
        "receivable_id": receivable_id,
        "approved_by": approved_by,
        "detail": "Write habilitado pero POST documento pendiente de cablear en AG-17.",
    }


def technical_report_client(
    *,
    client_ref: str,
    message: str = "",
    site_id: str | None = None,
    visit_id: str | None = None,
    channel: str = "mcp",
    report_type: str = "supervisor",
) -> dict[str, Any]:
    """Delega informe técnico a AG-13 / generate_supervisor_report."""
    from raphiia_openai import pcdoctor_store
    from raphiia_openai.operational.constants import COL_OPS_TECHNICAL_REPORTS
    from raphiia_openai.operational.document_numbering import reserve_document_number

    mission_id = _mission_id()
    resolved = _resolve_client(client_ref)
    if not resolved.get("ok") or not resolved.get("matches"):
        return {
            "ok": False,
            "error": "client_not_found",
            "client_ref": client_ref,
            "mission_id": mission_id,
            "delegate": COMMERCIAL_DELEGATES["supervisor_report"],
        }
    client = resolved["matches"][0]
    client_id = _norm(client.get("client_id"))
    numbering = reserve_document_number("technical_report")
    report = pcdoctor_store.generate_supervisor_report(client_id, site_id=site_id, visit_id=visit_id)
    if not report.get("ok"):
        return {**report, "mission_id": mission_id}

    report_id = _norm(report.get("report_id"))
    _db()[COL_OPS_TECHNICAL_REPORTS].update_one(
        {"report_id": report_id},
        {
            "$set": {
                "display_number": numbering.get("display_number"),
                "numbering_namespace": "ralfia",
                "orchestrator": VERO_AGENT_ID,
                "delegate": COMMERCIAL_DELEGATES["supervisor_report"],
                "channel": channel,
                "request_message": message[:2000],
            }
        },
    )

    _save_mission(
        {
            "mission_id": mission_id,
            "intent": "technical_report",
            "status": "completed",
            "agent": VERO_AGENT_ID,
            "delegate": COMMERCIAL_DELEGATES["supervisor_report"],
            "client_ref": client_ref,
            "client_id": client_id,
            "report_id": report_id,
            "display_number": numbering.get("display_number"),
            "channel": channel,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    )
    log_ops_action(
        actor=VERO_AGENT_ID,
        action="technical_report_client",
        resource_type="commercial_mission",
        resource_id=mission_id,
        summary=f"Vero informe técnico {client_ref}",
        tool_used="technical_report_client",
        metadata={"report_id": report_id, "channel": channel},
    )
    return {
        "ok": True,
        "mission_id": mission_id,
        "agent": VERO_DISPLAY_NAME,
        "agent_id": VERO_AGENT_ID,
        "delegate": COMMERCIAL_DELEGATES["supervisor_report"],
        "report_id": report_id,
        "display_number": numbering.get("display_number"),
        "report_preview": (report.get("report_markdown") or "")[:500],
    }


def vero_dispatch(
    message: str,
    *,
    channel: str = "mcp",
    entity_id: str = "ent_pcdoctor",
    require_approval: bool = True,
    approved_by: str | None = None,
    client_ref: str | None = None,
    quote_ref: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    """Dispatcher NL multicanal — punto único 'dile a Vero que…'."""
    intent = detect_intent(message)
    client_ref = client_ref or _extract_client_ref(message) or ""
    quote_ref = quote_ref or _extract_quote_ref(message)

    if not client_ref and intent in {"quote", "invoice", "technical_report"}:
        return {
            "ok": False,
            "error": "client_ref_required",
            "intent": intent,
            "agent": VERO_DISPLAY_NAME,
            "detail": "Indica el cliente: ej. 'dile a Vero que cotice a FEMAR'",
            "examples": [
                "dile a Vero que cotice a FEMAR puertas ZKTeco",
                "dile a Vero que facture a Cafecom la cotización PCD-COT-2026-08-002",
                "dile a Vero que haga informe técnico de Bellini",
            ],
        }

    if intent == "invoice":
        return invoice_client(
            client_ref=client_ref,
            quote_ref=quote_ref,
            entity_id=entity_id,
            channel=channel,
            require_approval=require_approval,
            approved_by=approved_by,
            message=message,
        )
    if intent == "technical_report":
        return technical_report_client(
            client_ref=client_ref,
            message=message,
            channel=channel,
        )
    if intent == "deliver":
        if not quote_ref:
            quote_ref = _extract_quote_ref(message)
        if quote_ref:
            from raphiia_openai.operational.quote_delivery import send_quote_delivery

            delivery = send_quote_delivery(quote_ref, channels=["whatsapp"], phone=phone)
            return {
                "ok": delivery.get("ok", False),
                "intent": "deliver",
                "agent": VERO_DISPLAY_NAME,
                "delivery": delivery,
            }
        return {"ok": False, "error": "quote_ref_required_for_delivery", "intent": "deliver"}

    if intent == "status" and quote_ref:
        from raphiia_openai.operational.quote_delivery import get_delivery_by_ticket

        return {
            "ok": True,
            "intent": "status",
            "agent": VERO_DISPLAY_NAME,
            "tracking": get_delivery_by_ticket(quote_ref),
        }

    return quote_client(
        client_ref=client_ref,
        message=message,
        entity_id=entity_id,
        channel=channel,
        quote_ref=quote_ref,
        send_whatsapp=bool(re.search(r"\b(whatsapp|env[ií]a|manda)\b", message, re.I)),
        phone=phone,
    )


def get_commercial_mission(mission_id: str) -> dict[str, Any]:
    doc = _db()[COL_COMMERCIAL_MISSIONS].find_one({"mission_id": mission_id})
    if not doc:
        return {"ok": False, "error": "mission_not_found", "mission_id": mission_id}
    out = dict(doc)
    out.pop("_id", None)
    return {"ok": True, "mission": out}


def list_commercial_missions(*, client_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if client_id:
        query["client_id"] = client_id
    cursor = _db()[COL_COMMERCIAL_MISSIONS].find(query).sort("created_at", -1).limit(max(1, min(limit, 100)))
    items = []
    for doc in cursor:
        row = dict(doc)
        row.pop("_id", None)
        items.append(row)
    return {"ok": True, "count": len(items), "missions": items}
