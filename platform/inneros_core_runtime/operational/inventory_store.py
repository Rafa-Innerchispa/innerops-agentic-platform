"""MOD-INVENTORY — items y movimientos de stock."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import COL_INVENTORY_ITEMS, COL_INVENTORY_MOVEMENTS, COL_INVENTORY_OFFERS, COL_PROCUREMENT_ORDERS

ALLOWED_MOVEMENT_TYPES = {"in", "out", "adjust"}


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


def _qty(value: Any) -> float:
    try:
        return round(float(value or 0), 3)
    except (TypeError, ValueError):
        return 0.0


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip().lower()


_ACCENT_GROUPS: dict[str, str] = {
    "a": "aàáâãäå",
    "e": "eèéêë",
    "i": "iìíîï",
    "o": "oòóôõö",
    "u": "uùúûü",
    "n": "nñ",
    "c": "cç",
}


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def accent_insensitive_regex(text: str) -> str:
    """Regex que coincide con texto acentuado o sin acentos (p. ej. camara → Cámara)."""
    parts: list[str] = []
    for ch in text:
        base = _strip_accents(ch).lower()
        group = _ACCENT_GROUPS.get(base)
        if group:
            parts.append(f"[{re.escape(group)}]")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def inventory_catalog_stats() -> dict[str, Any]:
    db = _db()
    local_products = db["ralfia_local_product_catalog"].count_documents({"_kind": {"$ne": "meta"}})
    inventory_total = db[COL_INVENTORY_ITEMS].count_documents({})
    return {
        "catalog_source": "local_merged",
        "total_items": inventory_total,
        "total_offers": db[COL_INVENTORY_OFFERS].count_documents({}),
        "local_products_total": local_products,
        "catalog_total_items": inventory_total + local_products,
    }


def _ensure_indexes() -> None:
    db = _db()
    for collection, specs in [
        (COL_INVENTORY_ITEMS, [
            ([("item_id", 1)], {"name": "ux_inventory_item_id", "unique": True, "sparse": True}),
            ([("sku", 1), ("entity_id", 1)], {"name": "ux_inventory_sku_entity", "unique": True, "sparse": True}),
        ]),
        (COL_INVENTORY_OFFERS, [
            ([("offer_id", 1)], {"name": "ux_inventory_offer_id", "unique": True, "sparse": True}),
            ([("item_id", 1), ("party_id", 1)], {"name": "ix_inventory_offer_item_party"}),
            ([("sku", 1), ("party_id", 1)], {"name": "ix_inventory_offer_sku_party", "sparse": True}),
        ]),
        (COL_INVENTORY_MOVEMENTS, [
            ([("movement_id", 1)], {"name": "ux_inventory_movement_id", "unique": True, "sparse": True}),
            ([("item_id", 1)], {"name": "ix_inventory_movement_item"}),
        ]),
    ]:
        for keys, kwargs in specs:
            try:
                db[collection].create_index(keys, **kwargs)
            except Exception:
                continue


def upsert_inventory_item(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    sku = _norm(_pull(payload, "sku"))
    entity_id = _norm(_pull(payload, "entity_id", default="ent_pcdoctor"))
    item_id = _norm(_pull(payload, "item_id"))
    product_key = _norm(_pull(payload, "product_key"))
    existing = None
    if item_id:
        existing = db[COL_INVENTORY_ITEMS].find_one({"item_id": item_id})
    if not existing and sku:
        existing = db[COL_INVENTORY_ITEMS].find_one({"sku": sku, "entity_id": entity_id})
    if not existing and product_key:
        existing = db[COL_INVENTORY_ITEMS].find_one({"product_key": product_key, "entity_id": entity_id})
    item_id = item_id or _norm((existing or {}).get("item_id")) or _new_id("invitem")
    doc = {
        "item_id": item_id,
        "sku": sku or _norm((existing or {}).get("sku")),
        "name": _norm(_pull(payload, "name", "description")) or _norm((existing or {}).get("name")),
        "brand": _norm(_pull(payload, "brand")) or _norm((existing or {}).get("brand")),
        "model": _norm(_pull(payload, "model")) or _norm((existing or {}).get("model")),
        "part_number": _norm(_pull(payload, "part_number")) or _norm((existing or {}).get("part_number")),
        "product_key": product_key or _norm((existing or {}).get("product_key")),
        "source": _norm(_pull(payload, "source")) or _norm((existing or {}).get("source")),
        "source_doc": _norm(_pull(payload, "source_doc")) or _norm((existing or {}).get("source_doc")),
        "entity_id": entity_id,
        "category": _norm(_pull(payload, "category")) or _norm((existing or {}).get("category")),
        "description": _norm(_pull(payload, "long_description", "description")) or _norm((existing or {}).get("description")),
        "capabilities": payload.get("capabilities", (existing or {}).get("capabilities") or {}),
        "protocols": payload.get("protocols", (existing or {}).get("protocols") or []),
        "software_compatibility": payload.get(
            "software_compatibility", (existing or {}).get("software_compatibility") or []
        ),
        "controller_compatibility": payload.get(
            "controller_compatibility", (existing or {}).get("controller_compatibility") or []
        ),
        "environment": _norm(_pull(payload, "environment")) or _norm((existing or {}).get("environment")),
        "specifications": payload.get("specifications", (existing or {}).get("specifications") or {}),
        "source_confidence": _qty(
            _pull(payload, "source_confidence", default=(existing or {}).get("source_confidence") or 0)
        ),
        "unit": _norm(_pull(payload, "unit", default="unit")),
        "qty_on_hand": _qty(_pull(payload, "qty_on_hand")) if "qty_on_hand" in payload else _qty((existing or {}).get("qty_on_hand")),
        "reorder_level": _qty(_pull(payload, "reorder_level", default=(existing or {}).get("reorder_level") or 0)),
        "location": _norm(_pull(payload, "location")) or _norm((existing or {}).get("location")),
        "party_id": _norm(_pull(payload, "party_id", "supplier_party_id")) or _norm((existing or {}).get("party_id")),
        "is_equipment": bool(payload.get("is_equipment", (existing or {}).get("is_equipment"))),
        "asset_id": _norm(_pull(payload, "asset_id")) or _norm((existing or {}).get("asset_id")),
        "updated_at": now,
    }
    created = False
    if not existing:
        doc["created_at"] = now
        db[COL_INVENTORY_ITEMS].insert_one(doc)
        created = True
    else:
        db[COL_INVENTORY_ITEMS].update_one({"_id": existing["_id"]}, {"$set": doc})
    saved = _serialize(db[COL_INVENTORY_ITEMS].find_one({"item_id": item_id}))
    log_ops_action(actor="CHATGPT", action="upsert_inventory_item", resource_type="inventory_item", resource_id=item_id,
                   summary=f"Item {saved.get('sku') or saved.get('name')}", tool_used="upsert_inventory_item", metadata={"created": created})
    return {"ok": True, "created": created, "item_id": item_id, "item": saved}


def record_inventory_movement(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    item_id = _norm(_pull(payload, "item_id"))
    sku = _norm(_pull(payload, "sku"))
    entity_id = _norm(_pull(payload, "entity_id", default="ent_pcdoctor"))
    item = db[COL_INVENTORY_ITEMS].find_one({"item_id": item_id}) if item_id else None
    if not item and sku:
        item = db[COL_INVENTORY_ITEMS].find_one({"sku": sku, "entity_id": entity_id})
    if not item:
        item_res = upsert_inventory_item({
            "sku": sku or _new_id("sku"),
            "name": _norm(_pull(payload, "name", "description", default="Item")),
            "entity_id": entity_id,
            "qty_on_hand": 0,
        })
        item = db[COL_INVENTORY_ITEMS].find_one({"item_id": item_res["item_id"]})
    item_id = _norm(item.get("item_id"))
    movement_type = _norm(_pull(payload, "movement_type", "type", default="in"))
    if movement_type not in ALLOWED_MOVEMENT_TYPES:
        movement_type = "in"
    qty = _qty(_pull(payload, "quantity", "qty"))
    if qty <= 0:
        return {"ok": False, "error": "quantity must be > 0"}
    current = _qty(item.get("qty_on_hand"))
    if movement_type == "in":
        new_qty = round(current + qty, 3)
    elif movement_type == "out":
        new_qty = round(max(0, current - qty), 3)
    else:
        new_qty = qty
    movement_id = _new_id("invmov")
    movement = {
        "movement_id": movement_id,
        "item_id": item_id,
        "sku": _norm(item.get("sku")),
        "entity_id": entity_id,
        "movement_type": movement_type,
        "quantity": qty,
        "qty_before": current,
        "qty_after": new_qty,
        "purchase_id": _norm(_pull(payload, "purchase_id")),
        "payable_id": _norm(_pull(payload, "payable_id")),
        "reference": _norm(_pull(payload, "reference")),
        "notes": _norm(_pull(payload, "notes")),
        "recorded_by": _norm(_pull(payload, "recorded_by", default="CHATGPT")),
        "created_at": now,
    }
    db[COL_INVENTORY_MOVEMENTS].insert_one(movement)
    db[COL_INVENTORY_ITEMS].update_one({"item_id": item_id}, {"$set": {"qty_on_hand": new_qty, "updated_at": now}})
    saved_item = _serialize(db[COL_INVENTORY_ITEMS].find_one({"item_id": item_id}))
    log_ops_action(actor="CHATGPT", action="record_inventory_movement", resource_type="inventory_movement", resource_id=movement_id,
                   summary=f"{movement_type} {qty} {saved_item.get('sku')}", tool_used="record_inventory_movement",
                   metadata={"item_id": item_id, "qty_after": new_qty})
    return {"ok": True, "movement_id": movement_id, "movement": _serialize(movement), "item": saved_item}


def receive_goods(payload: dict[str, Any]) -> dict[str, Any]:
    """Recibe mercadería desde purchase_id o líneas manuales."""
    purchase_id = _norm(_pull(payload, "purchase_id"))
    lines = payload.get("line_items") or []
    if purchase_id:
        po = _db()[COL_PROCUREMENT_ORDERS].find_one({"purchase_id": purchase_id})
        if po:
            lines = po.get("line_items") or []
    results = []
    for line in lines:
        sku = _norm(line.get("sku")) or _normalize_key(line.get("description"))
        res = record_inventory_movement({
            "sku": sku,
            "name": _norm(line.get("description")),
            "entity_id": _norm(_pull(payload, "entity_id", default=line.get("entity_id") or "ent_pcdoctor")),
            "quantity": line.get("quantity", 1),
            "movement_type": "in",
            "purchase_id": purchase_id,
            "payable_id": _norm(_pull(payload, "payable_id")),
            "notes": _norm(_pull(payload, "notes", default="receive_goods")),
        })
        results.append(res)
    if purchase_id and results and all(r.get("ok") for r in results):
        _db()[COL_PROCUREMENT_ORDERS].update_one({"purchase_id": purchase_id}, {"$set": {"status": "received", "updated_at": _now_iso()}})
    return {"ok": True, "count": len(results), "movements": results, "purchase_id": purchase_id}


def list_inventory(entity_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if entity_id:
        query["entity_id"] = _norm(entity_id)
    cursor = _db()[COL_INVENTORY_ITEMS].find(query).sort("name", 1).limit(max(1, min(limit, 200)))
    items = [_serialize(doc) for doc in cursor]
    low_stock = [i for i in items if _qty(i.get("qty_on_hand")) <= _qty(i.get("reorder_level"))]
    return {"ok": True, "count": len(items), "low_stock_count": len(low_stock), "items": items, "low_stock": low_stock}


def _offer_hash_seed(payload: dict[str, Any], item_id: str, party_id: str) -> str:
    return "|".join([
        item_id,
        party_id,
        _norm(_pull(payload, "price", default="0")),
        _norm(_pull(payload, "currency", default="USD")).upper(),
        _norm(_pull(payload, "source_doc", "source_url", default="")),
        _norm(_pull(payload, "effective_at", default="")),
    ])


def upsert_inventory_offer(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    item_id = _norm(_pull(payload, "item_id"))
    sku = _norm(_pull(payload, "sku"))
    entity_id = _norm(_pull(payload, "entity_id", default="ent_pcdoctor"))
    item = db[COL_INVENTORY_ITEMS].find_one({"item_id": item_id}) if item_id else None
    if not item and sku:
        item = db[COL_INVENTORY_ITEMS].find_one({"sku": sku, "entity_id": entity_id})
    if not item:
        item_res = upsert_inventory_item({
            "item_id": item_id or "",
            "sku": sku or _norm(_pull(payload, "source_sku")) or _norm(_pull(payload, "name", "description", default="item")),
            "name": _norm(_pull(payload, "item_name", "name", "description", default="Item")),
            "entity_id": entity_id,
            "category": _norm(_pull(payload, "category", default="catalog")),
            "unit": _norm(_pull(payload, "unit", default="license")),
            "qty_on_hand": payload.get("qty_on_hand", 0),
            "reorder_level": payload.get("reorder_level", 0),
        })
        item_id = item_res["item_id"]
        item = db[COL_INVENTORY_ITEMS].find_one({"item_id": item_id})
    item_id = _norm(item.get("item_id"))
    party_id = _norm(_pull(payload, "party_id", "supplier_party_id"))
    party_name = _norm(_pull(payload, "party_name", "supplier_name"))
    if not item_id:
        return {"ok": False, "error": "item_id required"}
    if not party_id and not party_name:
        return {"ok": False, "error": "party_id or party_name required"}
    seed = _offer_hash_seed(payload, item_id, party_id or party_name)
    offer_id = _norm(_pull(payload, "offer_id")) or f"invoffer_{hashlib.sha1(seed.encode()).hexdigest()[:20]}"
    doc = {
        "offer_id": offer_id,
        "item_id": item_id,
        "sku": _norm(item.get("sku")),
        "item_name": _norm(item.get("name")),
        "entity_id": entity_id,
        "party_id": party_id,
        "party_name": party_name,
        "price": _qty(_pull(payload, "price", default=0)),
        "currency": _norm(_pull(payload, "currency", default="USD")).upper(),
        "stock": _qty(_pull(payload, "stock", default=0)),
        "lead_time_days": int(_pull(payload, "lead_time_days", default=0) or 0),
        "warranty_months": int(_pull(payload, "warranty_months", default=0) or 0),
        "source_url": _norm(_pull(payload, "source_url")),
        "source_doc": _norm(_pull(payload, "source_doc")),
        "status": _norm(_pull(payload, "status", default="active")) or "active",
        "effective_at": _norm(_pull(payload, "effective_at")),
        "expires_at": _norm(_pull(payload, "expires_at")),
        "notes": _norm(_pull(payload, "notes")),
        "terms": _norm(_pull(payload, "terms")),
        "updated_at": now,
    }
    existing = db[COL_INVENTORY_OFFERS].find_one({"offer_id": offer_id})
    if not existing:
        doc["created_at"] = now
        db[COL_INVENTORY_OFFERS].insert_one(doc)
        created = True
    else:
        db[COL_INVENTORY_OFFERS].update_one({"_id": existing["_id"]}, {"$set": doc})
        created = False
    saved = _serialize(db[COL_INVENTORY_OFFERS].find_one({"offer_id": offer_id}))
    log_ops_action(actor="CHATGPT", action="upsert_inventory_offer", resource_type="inventory_offer", resource_id=offer_id,
                   summary=f"Offer {saved.get('sku') or saved.get('item_name')} @ {saved.get('party_name') or saved.get('party_id')}",
                   tool_used="upsert_inventory_offer", metadata={"created": created, "item_id": item_id, "party_id": party_id})
    return {"ok": True, "created": created, "offer_id": offer_id, "offer": saved}


def list_inventory_offers(item_id: str | None = None, supplier_party_id: str | None = None, query: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = _db()
    filt: dict[str, Any] = {}
    if item_id:
        filt["item_id"] = _norm(item_id)
    if supplier_party_id:
        filt["party_id"] = _norm(supplier_party_id)
    if query:
        q = accent_insensitive_regex(_norm(query))
        filt["$or"] = [
            {"sku": {"$regex": q, "$options": "i"}},
            {"item_name": {"$regex": q, "$options": "i"}},
            {"party_name": {"$regex": q, "$options": "i"}},
            {"notes": {"$regex": q, "$options": "i"}},
        ]
    cursor = db[COL_INVENTORY_OFFERS].find(filt).sort([("price", 1), ("updated_at", -1)]).limit(max(1, min(limit, 200)))
    offers = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(offers), "offers": offers, "filter": filt}


def search_inventory_catalog(query: str, limit: int = 20) -> dict[str, Any]:
    db = _db()
    raw = _norm(query)
    if not raw:
        return {"ok": True, "count": 0, "items": []}
    variants = [raw]
    if raw.endswith("s") and len(raw) > 3:
        variants.append(raw[:-1])
    patterns = list(dict.fromkeys(accent_insensitive_regex(v) for v in variants))
    or_clauses: list[dict[str, Any]] = []
    for pattern in patterns:
        or_clauses.extend([
            {"sku": {"$regex": pattern, "$options": "i"}},
            {"name": {"$regex": pattern, "$options": "i"}},
            {"description": {"$regex": pattern, "$options": "i"}},
            {"category": {"$regex": pattern, "$options": "i"}},
            {"brand": {"$regex": pattern, "$options": "i"}},
            {"model": {"$regex": pattern, "$options": "i"}},
        ])
    cursor = db[COL_INVENTORY_ITEMS].find({"$or": or_clauses}).sort("name", 1).limit(max(1, min(limit, 100)))
    items = []
    for item in cursor:
        item_ser = _serialize(item)
        offers = list(db[COL_INVENTORY_OFFERS].find({"item_id": item_ser.get("item_id")}).sort([("price", 1), ("updated_at", -1)]))
        offers_ser = [_serialize(doc) for doc in offers]
        item_ser["offers"] = offers_ser
        item_ser["best_offer"] = offers_ser[0] if offers_ser else None
        items.append(item_ser)
    return {"ok": True, "count": len(items), "items": items}


_ensure_indexes()
