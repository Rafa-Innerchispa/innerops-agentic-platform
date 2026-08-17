"""Factura borrador (pre-SRI) — mismo motor documental que cotizaciones."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.constants import COL_OPS_INVOICE_RECORDS, COL_OPS_QUOTE_DRAFTS
from raphiia_openai.operational.document_engine import build_document_html, normalize_tax_rate
from raphiia_openai.operational.pcdoctor_store import _serialize
from raphiia_openai.operational.quote_renderer import build_quote_context, _quote_spec


def _internal_invoice_number(receivable_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = receivable_id.replace("receivable", "")[-6:] or "000001"
    return f"FAC-BORR-{ts}-{suffix.upper()}"


def build_invoice_spec(
    quote_id: str,
    receivable: dict[str, Any],
    *,
    internal_number: str | None = None,
) -> dict[str, Any]:
    ctx = build_quote_context(quote_id)
    if not ctx.get("ok"):
        return ctx
    spec = _quote_spec(ctx)
    inv_num = internal_number or receivable.get("invoice_number") or _internal_invoice_number(
        str(receivable.get("receivable_id") or receivable.get("draft_id") or "")
    )
    spec["document_type"] = "invoice"
    spec["title"] = "Factura (borrador — pendiente autorización SRI)"
    spec["document_number"] = inv_num
    spec["display_number"] = inv_num
    spec["status"] = "ready_for_sri"
    spec["issued_at"] = receivable.get("issue_date") or datetime.now(timezone.utc).isoformat()
    spec["footer_note"] = (
        "Documento preparado en RalfIA. No constituye comprobante fiscal electrónico "
        "hasta emisión autorizada en Contifico/SRI."
    )
    spec["commercial_terms"] = {
        **(spec.get("commercial_terms") or {}),
        "payment_terms": receivable.get("notes") or spec.get("commercial_terms", {}).get("payment_terms", ""),
    }
    return {"ok": True, "spec": spec, "internal_number": inv_num}


def render_invoice_html(quote_id: str, receivable: dict[str, Any]) -> dict[str, Any]:
    built = build_invoice_spec(quote_id, receivable)
    if not built.get("ok"):
        return built
    html_doc = build_document_html(built["spec"])
    return {
        "ok": True,
        "quote_id": quote_id,
        "receivable_id": receivable.get("receivable_id"),
        "internal_number": built["internal_number"],
        "html": html_doc,
        "status": "ready_for_sri",
    }


def save_invoice_record(
    *,
    quote_id: str,
    receivable: dict[str, Any],
    html: str,
    internal_number: str,
    fiscal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = datetime.now(timezone.utc).isoformat()
    record_id = f"invrec_{quote_id[-12:]}_{str(receivable.get('receivable_id',''))[-8:]}"
    doc = {
        "invoice_record_id": record_id,
        "quote_id": quote_id,
        "receivable_id": receivable.get("receivable_id"),
        "draft_id": receivable.get("draft_id"),
        "internal_number": internal_number,
        "client_name": receivable.get("client_name"),
        "tax_id": receivable.get("tax_id"),
        "amount": receivable.get("amount"),
        "currency": receivable.get("currency", "USD"),
        "entity_id": receivable.get("entity_id", "ent_pcdoctor"),
        "status": "ready_for_sri",
        "sri_emit_status": "pending_authorization",
        "html": html[:500000],
        "fiscal_validation": fiscal or {},
        "created_at": now,
        "updated_at": now,
    }
    db[COL_OPS_INVOICE_RECORDS].update_one({"invoice_record_id": record_id}, {"$set": doc}, upsert=True)
    return {"ok": True, "invoice_record_id": record_id, "invoice_record": _serialize(doc)}
