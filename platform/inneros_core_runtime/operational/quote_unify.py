"""Puente unificado de cotizaciones — ops_quote_drafts canónico."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.constants import COL_OPS_QUOTE_DRAFTS, COL_OPS_QUOTE_LINKS
from raphiia_openai.operational.pcdoctor_store import _serialize, create_quote_draft


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def ensure_quote_link_indexes() -> None:
    for spec in (
        ([("canonical_quote_id", 1)], {"name": "ux_quote_links_canonical", "unique": True}),
        ([("source", 1), ("source_id", 1)], {"name": "ux_quote_links_source", "unique": True}),
    ):
        try:
            _db()[COL_OPS_QUOTE_LINKS].create_index(spec[0], **spec[1])
        except Exception:
            continue


def _contifico_to_payload(doc: dict[str, Any]) -> dict[str, Any]:
    line_items = []
    for ln in doc.get("lineas") or []:
        line_items.append({
            "description": ln.get("descripcion") or ln.get("producto") or "Item",
            "quantity": float(ln.get("cantidad", 1) or 1),
            "unit_price": float(ln.get("precio_unitario", ln.get("precio", 0)) or 0),
            "total": float(ln.get("total", 0) or 0),
        })
    return {
        "display_number": doc.get("ralfia_number") or doc.get("documento"),
        "client_id": str(doc.get("persona_id") or ""),
        "title": doc.get("descripcion") or "Cotizacion Contifico",
        "intro_md": (doc.get("descripcion") or "")[:500],
        "line_items": line_items,
        "subtotal": float(doc.get("subtotal") or 0),
        "tax": float(doc.get("iva") or 0),
        "total": float(doc.get("total") or 0),
        "currency": "USD",
        "entity_id": "ent_pcdoctor",
        "source": "contifico",
        "status": "approved",
    }


def _smart_quoter_to_payload(doc: dict[str, Any]) -> dict[str, Any]:
    items = doc.get("items") or []
    line_items = [
        {
            "description": it.get("name") or "Item",
            "quantity": float(it.get("quantity", 1) or 1),
            "unit_price": float(it.get("price", 0) or 0),
            "total": float(it.get("total", 0) or 0),
        }
        for it in items
    ]
    return {
        "display_number": doc.get("quote_number"),
        "client_id": doc.get("client_id"),
        "client_name": doc.get("client_name"),
        "title": doc.get("description") or doc.get("solution_summary") or "Cotizacion Smart Quoter",
        "intro_md": doc.get("solution_summary") or doc.get("diagnosis") or "",
        "line_items": line_items,
        "total": float(doc.get("total_amount") or 0),
        "subtotal": float(doc.get("total_amount") or 0),
        "currency": "USD",
        "entity_id": doc.get("entity_id") or "ent_innerspark",
        "source": "smart_quoter",
        "status": doc.get("status", "draft"),
        "client_phone": doc.get("contact") if doc.get("contact") and "@" not in str(doc.get("contact")) else "",
        "client_email": doc.get("contact") if doc.get("contact") and "@" in str(doc.get("contact")) else "",
    }


def resolve_canonical_quote(quote_ref: str) -> dict[str, Any]:
    """Resuelve cualquier ref → quote_id canónico ops_quote_drafts + link."""
    ensure_quote_link_indexes()
    db = _db()
    # Ya canónico
    doc = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote_ref})
    if doc:
        return {"ok": True, "canonical_quote_id": doc["quote_id"], "source": "ops_quote_drafts", "quote": _serialize(doc)}
    doc = db[COL_OPS_QUOTE_DRAFTS].find_one({"display_number": quote_ref})
    if doc:
        return {"ok": True, "canonical_quote_id": doc["quote_id"], "source": "ops_quote_drafts", "quote": _serialize(doc)}

    link = db[COL_OPS_QUOTE_LINKS].find_one({"source_id": quote_ref})
    if link:
        doc = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": link["canonical_quote_id"]})
        if doc:
            return {"ok": True, "canonical_quote_id": doc["quote_id"], "source": link["source"], "quote": _serialize(doc), "link": _serialize(link)}

    sq = db["quote_opportunities"].find_one({"quote_number": quote_ref})
    source = "smart_quoter"
    payload = None
    if sq:
        payload = _smart_quoter_to_payload(sq)
        source_id = sq["quote_number"]
    else:
        cot = db["contifico_documents"].find_one({"ralfia_number": quote_ref})
        if not cot:
            cot = db["contifico_documents"].find_one({"documento": quote_ref})
        if cot:
            payload = _contifico_to_payload(cot)
            source_id = cot.get("ralfia_number") or cot.get("documento")
            source = "contifico"
    if not payload:
        return {"ok": False, "error": "quote not found in any source"}

    created = create_quote_draft(payload)
    canonical_id = created.get("quote_id")
    if not canonical_id and created.get("quote_draft"):
        canonical_id = created["quote_draft"].get("quote_id")
    if not canonical_id:
        return {"ok": False, "error": "failed to create canonical quote"}

    link_doc = {
        "canonical_quote_id": canonical_id,
        "source": source,
        "source_id": source_id,
        "display_number": payload.get("display_number"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    db[COL_OPS_QUOTE_LINKS].update_one(
        {"source": source, "source_id": source_id},
        {"$set": link_doc},
        upsert=True,
    )
    doc = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": canonical_id})
    return {
        "ok": True,
        "canonical_quote_id": canonical_id,
        "source": source,
        "synced": True,
        "quote": _serialize(doc),
        "link": link_doc,
    }


def sync_quote_sources(quote_ref: str) -> dict[str, Any]:
    """Alias MCP — unifica ref externa a ops_quote_drafts."""
    return resolve_canonical_quote(quote_ref)
