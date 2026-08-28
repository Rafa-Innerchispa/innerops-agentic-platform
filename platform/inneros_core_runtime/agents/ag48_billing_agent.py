"""AG-48 Billing Agent — facturación draft local (AG-17 path; FAC fiscal gated)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-48_BILLING_AGENT"
FAC_EMIT_ENABLED = False  # AG-17 runtime pendiente — solo borradores AR


def agent_invoice_prepare(
    client_ref: str,
    quote_ref: str = "",
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Borrador factura/cobro — no emite FAC SRI hasta AG-17 operativo."""
    from raphiia_openai.commercial import vero_orchestrator as vero

    if not dry_run and not FAC_EMIT_ENABLED:
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "error": "fac_emit_disabled",
            "note": "AG-17 Contifico emit pendiente. Usar dry_run=true o create_receivable_from_quote vía MCP.",
        }
    result = vero.invoice_client(
        client_ref=client_ref,
        quote_ref=quote_ref or None,
        message=f"Factura draft {client_ref}",
        channel="mcp",
        require_approval=True,
    )
    record_agent_run(AGENT_ID, action="agent_invoice_prepare", summary=f"client={client_ref}", project="pcdoctor")
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, "dry_run": True, "fac_emit": FAC_EMIT_ENABLED, **result}


def agent_billing_status(client_ref: str = "") -> dict[str, Any]:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    open_recv = db["ralfia_receivables"].count_documents({"status": {"$in": ["open", "draft", "pending"]}})
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "fac_emit_enabled": FAC_EMIT_ENABLED,
        "open_receivables_count": open_recv,
        "client_ref": client_ref or None,
        "next": "Implementar AG-17 emit vía Contifico API cuando Rafael apruebe",
    }
