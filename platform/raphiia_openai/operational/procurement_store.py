"""MOD-PROCUREMENT — órdenes de compra vinculadas a party_id y AP."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import COL_PROCUREMENT_ORDERS
from raphiia_openai.operational import party_store

ALLOWED_PO_STATUS = {"draft", "ordered", "partial", "received", "cancelled"}
NON_CANONICAL_PO = ("draft", "promoted")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _pull(payload: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return default


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _new_id(prefix: str) -> str:
    return f"{prefix}_{ObjectId()}"


def _amount(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip().lower()


def _po_dedupe_key(doc: dict[str, Any]) -> str:
    party_id = _norm(_pull(doc, "party_id", "supplier_party_id"))
    ref = _norm(_pull(doc, "reference", "po_number"))
    entity_id = _norm(_pull(doc, "entity_id"))
    if party_id and ref:
        return f"party:{party_id}::ref:{ref}"
    if entity_id and ref:
        return f"entity:{entity_id}::ref:{ref}"
    return ""


def _resolve_supplier(payload: dict[str, Any]) -> tuple[str, str]:
    party_id = _norm(_pull(payload, "party_id", "supplier_party_id"))
    supplier_name = _norm(_pull(payload, "supplier_name"))
    tax_id = _norm(_pull(payload, "tax_id", "ruc"))
    if party_id:
        return party_id, supplier_name
    query = tax_id or supplier_name
    if query:
        match = party_store.resolve_party(query, limit=1, roles=["supplier"]).get("best_match") or {}
        if match:
            return _norm(match.get("party_id")), _norm(match.get("display_name") or supplier_name)
    return party_id, supplier_name


def _calc_lines(line_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    lines: list[dict[str, Any]] = []
    total = 0.0
    for raw in line_items:
        qty = _amount(raw.get("quantity", 1) or 1)
        unit = _amount(raw.get("unit_price", raw.get("price", 0)))
        line_total = round(qty * unit, 2)
        total += line_total
        lines.append({
            "sku": _norm(raw.get("sku")),
            "description": _norm(raw.get("description", raw.get("name"))),
            "quantity": qty,
            "unit_price": unit,
            "line_total": line_total,
            "inventory_item_id": _norm(raw.get("inventory_item_id")),
            "is_equipment": bool(raw.get("is_equipment", False)),
        })
    return lines, round(total, 2)


def _find_reusable_po(dedupe_key: str) -> tuple[str, dict[str, Any]] | None:
    if not dedupe_key:
        return None
    db = _db()
    docs = list(db[COL_PROCUREMENT_ORDERS].find({"dedupe_key": dedupe_key}).sort("updated_at", -1))
    for doc in docs:
        if _norm(doc.get("status")) not in NON_CANONICAL_PO:
            return "canonical", _serialize(doc)
    for doc in docs:
        if _norm(doc.get("status")) == "draft":
            return "draft", _serialize(doc)
    return None


def _ensure_indexes() -> None:
    db = _db()
    for spec in [
        ([("purchase_id", 1)], {"name": "ux_procurement_purchase_id", "unique": True, "sparse": True}),
        ([("draft_id", 1)], {"name": "ux_procurement_draft_id", "unique": True, "sparse": True}),
        ([("dedupe_key", 1)], {"name": "ux_procurement_dedupe", "unique": True, "sparse": True}),
    ]:
        try:
            db[COL_PROCUREMENT_ORDERS].create_index(spec[0], **spec[1])
        except Exception:
            continue


def create_purchase_draft(payload: dict[str, Any]) -> dict[str, Any]:
    party_id, supplier_name = _resolve_supplier(payload)
    line_items, total = _calc_lines(payload.get("line_items") or payload.get("items") or [])
    preview = {
        "party_id": party_id,
        "supplier_name": supplier_name or _norm(_pull(payload, "supplier_name")),
        "tax_id": _norm(_pull(payload, "tax_id", "ruc")),
        "entity_id": _norm(_pull(payload, "entity_id", default="ent_pcdoctor")),
        "reference": _norm(_pull(payload, "reference", "po_number")),
        "total": total or _amount(_pull(payload, "total", "amount")),
    }
    dedupe_key = _po_dedupe_key({**preview, **payload})
    reusable = _find_reusable_po(dedupe_key)
    if reusable:
        reused_from, existing = reusable
        out: dict[str, Any] = {"ok": True, "reused": True, "reused_from": reused_from, "draft_id": existing.get("draft_id"), "purchase_draft": existing}
        if reused_from == "canonical":
            out["purchase_id"] = existing.get("purchase_id")
            out["purchase"] = existing
        return out
    draft_id = _new_id("purchasedraft")
    now = _now_iso()
    doc = {
        **preview,
        "draft_id": draft_id,
        "status": "draft",
        "line_items": line_items,
        "currency": _norm(_pull(payload, "currency", default="USD")),
        "expected_date": _norm(_pull(payload, "expected_date")),
        "payable_id": _norm(_pull(payload, "payable_id")),
        "notes": _norm(_pull(payload, "notes")),
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "dedupe_key": dedupe_key or None,
        "created_at": now,
        "updated_at": now,
    }
    if not doc.get("dedupe_key"):
        doc.pop("dedupe_key", None)
    _db()[COL_PROCUREMENT_ORDERS].insert_one(doc)
    log_ops_action(actor="CHATGPT", action="create_purchase_draft", resource_type="purchase_draft", resource_id=draft_id,
                   summary=f"PO draft {supplier_name or draft_id}", tool_used="create_purchase_draft",
                   metadata={"party_id": party_id, "total": doc["total"]})
    return {"ok": True, "reused": False, "draft_id": draft_id, "purchase_draft": _serialize(doc)}


def upsert_purchase(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "purchase_draft_id", "draft_id"))
    draft = db[COL_PROCUREMENT_ORDERS].find_one({"draft_id": draft_id}) if draft_id else None
    merged = {**(draft or {}), **payload}
    purchase_id = _norm(_pull(merged, "purchase_id")) or _new_id("purchase")
    line_items, total = _calc_lines(merged.get("line_items") or merged.get("items") or [])
    party_id, supplier_name = _resolve_supplier(merged)
    status = _norm(_pull(merged, "status", default=(draft or {}).get("status") or "ordered"))
    if status not in ALLOWED_PO_STATUS:
        status = "ordered"
    doc = {
        "purchase_id": purchase_id,
        "party_id": party_id or _norm((draft or {}).get("party_id")),
        "supplier_name": supplier_name or _norm(_pull(merged, "supplier_name")),
        "tax_id": _norm(_pull(merged, "tax_id")) or _norm((draft or {}).get("tax_id")),
        "entity_id": _norm(_pull(merged, "entity_id")) or _norm((draft or {}).get("entity_id")) or "ent_pcdoctor",
        "reference": _norm(_pull(merged, "reference")) or _norm((draft or {}).get("reference")),
        "status": status,
        "line_items": line_items,
        "total": total or _amount(_pull(merged, "total")),
        "currency": _norm(_pull(merged, "currency", default="USD")),
        "expected_date": _norm(_pull(merged, "expected_date")),
        "payable_id": _norm(_pull(merged, "payable_id")),
        "notes": _norm(_pull(merged, "notes")),
        "dedupe_key": _po_dedupe_key(merged),
        "updated_at": now,
    }
    existing = db[COL_PROCUREMENT_ORDERS].find_one({"purchase_id": purchase_id}) or draft
    created = False
    if not existing or existing.get("status") == "draft":
        if not existing:
            doc["created_at"] = now
            db[COL_PROCUREMENT_ORDERS].insert_one(doc)
            created = True
        else:
            db[COL_PROCUREMENT_ORDERS].update_one({"_id": existing["_id"]}, {"$set": doc})
    else:
        db[COL_PROCUREMENT_ORDERS].update_one({"purchase_id": purchase_id}, {"$set": doc})
    if draft_id:
        db[COL_PROCUREMENT_ORDERS].update_one(
            {"draft_id": draft_id},
            {"$set": {"status": "promoted", "promoted_to_purchase_id": purchase_id, "updated_at": now}, "$unset": {"purchase_id": ""}},
        )
    saved = _serialize(db[COL_PROCUREMENT_ORDERS].find_one({"purchase_id": purchase_id}))
    log_ops_action(actor="CHATGPT", action="upsert_purchase", resource_type="purchase", resource_id=purchase_id,
                   summary=f"PO {saved.get('supplier_name')}", tool_used="upsert_purchase", metadata={"created": created, "status": status})
    return {"ok": True, "created": created, "purchase_id": purchase_id, "purchase": saved}


def list_purchases_open(entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    query: dict[str, Any] = {"status": {"$in": ["ordered", "partial"]}}
    if entity_id:
        query["entity_id"] = _norm(entity_id)
    cursor = _db()[COL_PROCUREMENT_ORDERS].find(query).sort("updated_at", -1).limit(max(1, min(limit, 100)))
    items = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(items), "purchases": items}


_ensure_indexes()
