"""Pipeline comercial: cotización → aprobación → factura borrador → contabilidad (AR)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-17_BILLING_PIPELINE"
APPROVED_STATUSES = frozenset({"approved", "sent", "accepted"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approve_quote(quote_id: str, *, approved_by: str = "RAFAEL") -> dict[str, Any]:
    from raphiia_openai import pcdoctor_store

    result = pcdoctor_store.update_quote_draft({
        "quote_id": quote_id,
        "status": "approved",
        "approved_by": approved_by,
        "approved_at": _now(),
    })
    record_agent_run(AGENT_ID, action="approve_quote", summary=quote_id, project="pcdoctor")
    return result


def prepare_invoice_from_quote(
    quote_id: str,
    *,
    approved_by: str = "RAFAEL",
    auto_approve: bool = False,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """
    Flujo completo sin emisión SRI:
    1. Cotización aprobada
    2. Validación fiscal cliente
    3. AR (receivable) en contabilidad
    4. Documento HTML factura borrador
    5. Registro ops_invoice_records_internal (ready_for_sri)
    """
    from raphiia_openai import mongo_store, pcdoctor_store
    from raphiia_openai.agents import ag17_contifico_bridge_agent as ag17
    from raphiia_openai.operational import accounting_store, invoice_renderer
    from raphiia_openai.operational.constants import COL_OPS_QUOTE_DRAFTS

    db = mongo_store.get_db()
    quote = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote_id})
    if not quote:
        return {"ok": False, "error": "quote_not_found", "quote_id": quote_id}

    status = str(quote.get("status", "")).lower()
    if status not in APPROVED_STATUSES:
        if auto_approve:
            apr = approve_quote(quote_id, approved_by=approved_by)
            if not apr.get("ok"):
                return apr
            quote = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote_id}) or quote
        else:
            return {
                "ok": False,
                "error": "quote_not_approved",
                "quote_id": quote_id,
                "status": status,
                "detail": "Aprueba la cotización antes de facturar (approve_quote o auto_approve=true).",
            }

    client_id = quote.get("client_id")
    resolved = pcdoctor_store.resolve_client(client_id or quote.get("client_name", ""), limit=1)
    client = (resolved.get("matches") or [{}])[0] if resolved.get("ok") else {}
    fiscal = ag17.validate_client_fiscal(client) if client else {"ok": False, "error": "client_missing"}
    if not fiscal.get("ok"):
        return {
            "ok": False,
            "error": "fiscal_validation_failed",
            "quote_id": quote_id,
            "fiscal": fiscal,
        }

    ar = accounting_store.create_receivable_from_quote(quote_id, entity_id=entity_id)
    if not ar.get("ok"):
        return {**ar, "phase": "create_receivable"}

    receivable_draft = ar.get("receivable_draft") or ar.get("receivable") or {}
    draft_id = receivable_draft.get("draft_id")
    issue_date = _now()[:10]

    promoted = accounting_store.upsert_receivable({
        "receivable_draft_id": draft_id,
        "status": "pending",
        "issue_date": issue_date,
        "tax_id": fiscal.get("tax_id") or client.get("tax_id"),
        "invoice_number": invoice_renderer._internal_invoice_number(str(draft_id or quote_id)),
        "notes": f"Factura borrador desde cotización {quote.get('display_number') or quote_id}",
        "source": "billing_pipeline",
    })
    if not promoted.get("ok"):
        return {**promoted, "phase": "upsert_receivable"}

    receivable = promoted.get("receivable") or {}
    rendered = invoice_renderer.render_invoice_html(quote_id, receivable)
    if not rendered.get("ok"):
        return {**rendered, "phase": "render_invoice", "receivable": receivable}

    saved = invoice_renderer.save_invoice_record(
        quote_id=quote_id,
        receivable=receivable,
        html=rendered.get("html", ""),
        internal_number=rendered.get("internal_number", ""),
        fiscal=fiscal,
    )

    record_agent_run(
        AGENT_ID,
        action="prepare_invoice",
        summary=f"{quote_id} -> {receivable.get('receivable_id')}",
        project="pcdoctor",
    )

    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "quote_id": quote_id,
        "quote_status": "approved",
        "fiscal_validation": fiscal,
        "receivable_id": receivable.get("receivable_id"),
        "receivable": receivable,
        "invoice_record_id": saved.get("invoice_record_id"),
        "internal_number": rendered.get("internal_number"),
        "document_status": "ready_for_sri",
        "sri_emit": {
            "enabled": ag17.FAC_EMIT_ENABLED,
            "status": "pending_authorization",
            "note": "Documento listo. Emisión Contifico/SRI requiere autorización legal.",
        },
        "accounting": {
            "receivable_status": receivable.get("status"),
            "amount": receivable.get("amount"),
            "next_steps": [
                "record_collection cuando el cliente pague",
                "list_receivables_open para CxC",
                "accounting_summary para consolidado",
                "emit_contifico_invoice cuando SRI autorice",
            ],
        },
        "html_preview_chars": len(rendered.get("html") or ""),
    }


def get_invoice_record(invoice_record_id: str) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    from raphiia_openai.operational.constants import COL_OPS_INVOICE_RECORDS
    from raphiia_openai.operational.pcdoctor_store import _serialize

    doc = mongo_store.get_db()[COL_OPS_INVOICE_RECORDS].find_one({"invoice_record_id": invoice_record_id})
    if not doc:
        return {"ok": False, "error": "invoice_record_not_found"}
    out = _serialize(doc)
    out.pop("html", None)
    out["has_html"] = bool(doc.get("html"))
    return {"ok": True, **out}
