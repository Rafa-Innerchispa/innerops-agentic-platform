"""AG-17 Contifico Bridge — validación fiscal + factura borrador + AR (emisión SRI gated)."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-17_CONTIFICO_BRIDGE"
FAC_EMIT_ENABLED = False
SRI_EMIT_STATUS = "pending_authorization"


def validate_ecuador_tax_id(value: str) -> dict[str, Any]:
    """Valida RUC (13 dígitos, termina 001) o cédula (10 dígitos)."""
    from raphiia_openai import sri_validation

    norm = sri_validation.normalize_tax_id(value or "")
    clean = norm.get("input") or ""
    if norm.get("type") == "cedula" and len(clean) == 10:
        return {"ok": True, "type": "cedula", "tax_id": clean, "normalized": norm}
    if norm.get("type") == "ruc" and len(clean) == 13:
        if not clean.endswith("001"):
            return {"ok": False, "error": "ruc_must_end_001", "tax_id": clean}
        lookup = sri_validation.lookup_ruc(clean)
        active = str(lookup.get("status", "")).upper() in ("ACTIVO", "OK", "ACTIVE")
        return {
            "ok": bool(active or lookup.get("name")),
            "type": "ruc",
            "tax_id": clean,
            "lookup": lookup,
            "normalized": norm,
        }
    return {"ok": False, "error": "invalid_format", "detail": "RUC 13 dígitos o cédula 10", "normalized": norm}


def validate_client_fiscal(client: dict[str, Any]) -> dict[str, Any]:
    tax_id = (
        client.get("tax_id")
        or client.get("ruc")
        or client.get("cedula")
        or client.get("identification")
        or ""
    )
    if not str(tax_id).strip():
        return {"ok": False, "error": "tax_id_missing", "client_id": client.get("client_id")}
    return validate_ecuador_tax_id(str(tax_id))


def extract_quote_id(message: str) -> str | None:
    for pat in (r"(quotedraft_[a-f0-9]+)", r"(PCD-COT[-\d]+)"):
        m = re.search(pat, message or "", re.I)
        if m:
            return m.group(1)
    return None


def approve_quote_for_billing(quote_id: str, *, approved_by: str = "RAFAEL") -> dict[str, Any]:
    from raphiia_openai.operational import billing_pipeline

    result = billing_pipeline.approve_quote(quote_id, approved_by=approved_by)
    return {**result, "agent_id": AGENT_ID}


def prepare_invoice_from_quote(
    quote_id: str,
    *,
    approved_by: str = "RAFAEL",
    auto_approve: bool = False,
) -> dict[str, Any]:
    from raphiia_openai.operational import billing_pipeline

    result = billing_pipeline.prepare_invoice_from_quote(
        quote_id,
        approved_by=approved_by,
        auto_approve=auto_approve,
    )
    return {**result, "agent_id": AGENT_ID, "fac_emit_enabled": FAC_EMIT_ENABLED}


def run_contifico_invoice(
    client_ref: str,
    *,
    message: str = "",
    require_approval: bool = True,
    approved_by: str | None = None,
    auto_approve_quote: bool = False,
) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator

    quote_id = extract_quote_id(message) or extract_quote_id(client_ref)
    if quote_id:
        return prepare_invoice_from_quote(
            quote_id,
            approved_by=approved_by or "RAFAEL",
            auto_approve=auto_approve_quote or bool(approved_by),
        )

    resolved = vero_orchestrator._resolve_client(client_ref)
    if not resolved.get("ok") or not resolved.get("matches"):
        return {"ok": False, "agent_id": AGENT_ID, "error": "client_not_found", "client_ref": client_ref}

    client = resolved["matches"][0]
    fiscal = validate_client_fiscal(client)
    if not fiscal.get("ok"):
        record_agent_run(AGENT_ID, action="fiscal_reject", summary=str(fiscal.get("error")), project="pcdoctor")
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "error": "fiscal_validation_failed",
            "fiscal": fiscal,
            "client_ref": client_ref,
            "note": "Corrija RUC/cédula. O pase quote_id (quotedraft_* / PCD-COT-*) para facturar desde cotización.",
        }

    result = vero_orchestrator.invoice_client(
        client_ref=client_ref,
        message=message,
        require_approval=require_approval,
        approved_by=approved_by,
        channel="mcp",
    )
    record_agent_run(AGENT_ID, action="invoice_draft", summary=f"ok={result.get('ok')}", project="pcdoctor")
    return {
        **result,
        "agent_id": AGENT_ID,
        "fiscal_validation": fiscal,
        "fac_emit_enabled": FAC_EMIT_ENABLED,
        "sri_status": SRI_EMIT_STATUS,
    }


def extract_tax_id_from_message(message: str) -> str | None:
    m = re.search(r"\b(\d{10}|\d{13})\b", message or "")
    return m.group(1) if m else None
