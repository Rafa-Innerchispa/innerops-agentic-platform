"""AG-46 Quote Agent — cotización local PC Doctor (delega AG-16 + MCP store)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-46_QUOTE_AGENT"


def agent_quote_status(client_ref: str = "") -> dict[str, Any]:
    """Estado de cotizaciones recientes para un cliente."""
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if client_ref.strip():
        filt["$or"] = [
            {"client_ref": client_ref.strip()},
            {"client_id": client_ref.strip()},
            {"client_name": {"$regex": client_ref.strip(), "$options": "i"}},
        ]
    cursor = db["ralfia_quote_drafts"].find(filt).sort("updated_at", -1).limit(5)
    items = []
    for doc in cursor:
        items.append({
            "quote_id": str(doc.get("_id", "")),
            "quote_ref": doc.get("quote_ref") or doc.get("reference"),
            "status": doc.get("status"),
            "client_ref": doc.get("client_ref") or doc.get("client_id"),
            "total": doc.get("total"),
        })
    return {"ok": True, "agent_id": AGENT_ID, "count": len(items), "quotes": items}


def agent_quote_prepare(
    client_ref: str,
    title: str = "",
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Prepara borrador cotización — dry_run default hasta Rafael autorice envío."""
    from raphiia_openai.commercial import vero_orchestrator as vero

    result = vero.quote_client(
        client_ref=client_ref,
        message=title or f"Cotización para {client_ref}",
        channel="mcp",
        send_whatsapp=not dry_run,
    )
    record_agent_run(AGENT_ID, action="agent_quote_prepare", summary=f"client={client_ref} dry={dry_run}", project="pcdoctor")
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, "dry_run": dry_run, **result}
