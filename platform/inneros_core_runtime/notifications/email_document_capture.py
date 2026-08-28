"""Captura documental desde correo — facturas, cotizaciones, claves SRI.

Extrae claves de acceso (49 dígitos), RUC, montos y metadatos para
conciliar después con Contifico/SRI. No envía nada al SRI automáticamente.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

CAPTURED_COL = "email_captured_documents"

# Clave de acceso SRI Ecuador — 49 dígitos
SRI_ACCESS_KEY_RE = re.compile(r"\b(\d{49})\b")
SRI_ACCESS_KEY_FMT_RE = re.compile(r"\b(\d{2}-\d{3}-\d{13}-\d{13}-\d{13}-\d{1})\b")

RUC_RE = re.compile(r"\b(\d{10}001|\d{13})\b")
AMOUNT_RE = re.compile(
    r"(?:total|valor|amount|importe|monto)[:\s]*(?:USD|US\$|\$)?\s*([\d.,]+)",
    re.I,
)
INVOICE_NUM_RE = re.compile(
    r"(?:factura|invoice|comprobante|documento)\s*(?:n[o°.]?\s*)?[:\s#-]*([A-Z0-9\-]{3,30})",
    re.I,
)

DOC_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    (r"\b(?:factura electr[oó]nica|factura|invoice|comprobante)\b", "factura"),
    (r"\b(?:nota de cr[eé]dito|credit note)\b", "nota_credito"),
    (r"\b(?:retenci[oó]n|withholding)\b", "retencion"),
    (r"\b(?:cotizaci[oó]n|proforma|presupuesto|quote|quotation)\b", "cotizacion"),
    (r"\b(?:orden de compra|purchase order|\bPO\b)\b", "orden_compra"),
    (r"\b(?:gu[ií]a de remisi[oó]n)\b", "guia_remision"),
    (r"\b(?:liquidaci[oó]n de compra)\b", "liquidacion_compra"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_access_key(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _guess_doc_type(blob: str) -> str:
    for pattern, label in DOC_TYPE_HINTS:
        if re.search(pattern, blob, re.I):
            return label
    return "documento"


def extract_document_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """Extrae campos estructurados del cuerpo/asunto del correo."""
    subject = str(doc.get("subject") or "")
    body = str(doc.get("body_text") or doc.get("snippet") or "")
    from_addr = str(doc.get("from_addr") or doc.get("from") or "")
    blob = f"{subject}\n{body}"

    access_keys: list[str] = []
    for match in SRI_ACCESS_KEY_RE.finditer(blob):
        key = _normalize_access_key(match.group(1))
        if len(key) == 49 and key not in access_keys:
            access_keys.append(key)
    for match in SRI_ACCESS_KEY_FMT_RE.finditer(blob):
        key = _normalize_access_key(match.group(1))
        if len(key) == 49 and key not in access_keys:
            access_keys.append(key)

    rucs = list(dict.fromkeys(m.group(1) for m in RUC_RE.finditer(blob)))[:5]
    amounts = []
    for m in AMOUNT_RE.finditer(blob):
        raw = m.group(1).replace(",", "")
        try:
            amounts.append(float(raw))
        except ValueError:
            continue

    inv_match = INVOICE_NUM_RE.search(blob)
    doc_type = _guess_doc_type(blob)

    return {
        "doc_type": doc_type,
        "sri_access_keys": access_keys,
        "ruc_candidates": rucs,
        "amount_candidates": amounts[:5],
        "invoice_number_hint": inv_match.group(1) if inv_match else None,
        "from_addr": from_addr,
        "subject": subject[:240],
        "has_sri_key": bool(access_keys),
        "sri_lookup_ready": bool(access_keys),
        "sri_lookup_note": "Futuro: consultar SRI/Contifico por clave de acceso — no automático aún",
    }


def capture_from_email(
    doc: dict[str, Any],
    *,
    analysis: dict[str, Any] | None = None,
    security: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persiste documento capturado si aplica factura/cotización/SRI."""
    mail_id = str(doc.get("mail_id") or "").strip()
    if not mail_id:
        return {"ok": False, "error": "mail_id_required"}

    if security and security.get("verdict") == "block":
        return {"ok": True, "captured": False, "reason": "blocked_by_security"}

    category = (analysis or {}).get("category") or "general"
    fields = extract_document_fields(doc)
    doc_type = fields["doc_type"]

    capture_categories = {
        "factura", "cotizacion", "sri_fiscal", "pago", "contrato", "transferencia",
    }
    should_capture = (
        category in capture_categories
        or doc_type in ("factura", "cotizacion", "retencion", "nota_credito")
        or fields["has_sri_key"]
        or bool(doc.get("has_attachment"))
    )
    if not should_capture:
        return {"ok": True, "captured": False, "reason": "not_document_email"}

    routing = (analysis or {}).get("routing") or {}
    record = {
        "mail_id": mail_id,
        "account_address": doc.get("account_address"),
        "doc_type": doc_type,
        "category": category,
        "fields": fields,
        "agent_id": routing.get("agent_id"),
        "module": routing.get("module"),
        "status": "pending_review",
        "contifico_linked": False,
        "sri_sync_status": "not_attempted",
        "attachment_count": int(doc.get("attachment_count") or 0),
        "security_verdict": (security or {}).get("verdict"),
        "auto_process_allowed": bool((security or {}).get("auto_process_documents")),
        "received_at": doc.get("received_at"),
        "updated_at": _now(),
        "created_at": _now(),
    }

    db = mongo_store.get_db()
    existing = db[CAPTURED_COL].find_one({"mail_id": mail_id})
    if existing:
        record["created_at"] = existing.get("created_at") or record["created_at"]
        db[CAPTURED_COL].update_one({"mail_id": mail_id}, {"$set": record})
        action = "updated"
    else:
        db[CAPTURED_COL].insert_one(record)
        action = "created"

    ledger_result = None
    try:
        from raphiia_openai.operational import accounting_ledger

        ledger_result = accounting_ledger.promote_email_capture_to_ledger(
            mail_id, create_payable_draft=True
        )
    except Exception as exc:
        ledger_result = {"ok": False, "error": str(exc)[:180]}

    return {
        "ok": True,
        "captured": True,
        "action": action,
        "mail_id": mail_id,
        "doc_type": doc_type,
        "sri_access_keys": fields["sri_access_keys"],
        "ledger": ledger_result,
        "next": "Revisar en ralfia_ledger_documents / accounting_payables",
    }


def list_captured_documents(
    *,
    doc_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if doc_type:
        filt["doc_type"] = doc_type.strip().lower()
    if status:
        filt["status"] = status.strip().lower()
    rows = list(db[CAPTURED_COL].find(filt, {"_id": 0}).sort("received_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(rows), "documents": rows}


def get_capture_summary() -> dict[str, Any]:
    db = mongo_store.get_db()
    col = db[CAPTURED_COL]
    with_sri = col.count_documents({"fields.has_sri_key": True})
    pending = col.count_documents({"status": "pending_review"})
    by_type = {}
    for doc_type in ("factura", "cotizacion", "retencion", "documento"):
        by_type[doc_type] = col.count_documents({"doc_type": doc_type})
    return {
        "ok": True,
        "total": col.count_documents({}),
        "with_sri_key": with_sri,
        "pending_review": pending,
        "by_type": by_type,
        "sri_integration": "planned — clave acceso 49 dígitos lista para lookup",
    }
