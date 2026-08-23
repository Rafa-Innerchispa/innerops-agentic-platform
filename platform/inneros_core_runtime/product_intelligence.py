"""RalfIA Product Intelligence Pipeline.

One grouped capability stages source-grounded products and requires human
approval before writing canonical inventory items or supplier offers.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational import inventory_store
from raphiia_openai.operational.constants import COL_INVENTORY_ITEMS, COL_INVENTORY_OFFERS

SOURCES_COL = "product_source_documents"
DRAFTS_COL = "product_extraction_drafts"
ACTIONS = frozenset({"ingest_source", "stage_extraction", "approve", "search", "get_draft"})

_CAPABILITY_ALIASES = {
    "qr": ("qr", "qrcode", "qr_code"),
    "face": ("face", "facial", "rostro"),
    "fingerprint": ("fingerprint", "huella", "finger"),
    "rfid": ("rfid", "card", "tarjeta"),
    "pin": ("pin", "password", "clave"),
    "wiegand": ("wiegand",),
    "rs485": ("rs485", "rs_485"),
    "tcp_ip": ("tcp_ip", "tcpip", "ethernet"),
    "sdk": ("sdk",),
    "api": ("api", "rest_api"),
    "outdoor": ("outdoor", "exterior", "ip65", "ip66"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _key_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(value).lower())


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(_norm(item) for item in values if _norm(item)))


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = _norm(value).lower()
    if normalized in {"yes", "true", "1", "si", "sí", "supported"}:
        return True
    if normalized in {"no", "false", "0", "unsupported"}:
        return False
    return None


def normalize_product(payload: dict[str, Any]) -> dict[str, Any]:
    brand = _norm(payload.get("brand") or payload.get("manufacturer"))
    model = _norm(payload.get("model"))
    part_number = _norm(payload.get("part_number") or payload.get("sku"))
    if not brand or not model:
        return {"ok": False, "error": "brand_and_model_required", "input": payload}

    raw_caps = payload.get("capabilities") or {}
    search_blob = " ".join(
        [
            _norm(payload.get("description")),
            " ".join(_list(payload.get("features"))),
            " ".join(_list(payload.get("protocols"))),
        ]
    ).lower()
    capabilities: dict[str, bool | None] = {}
    for canonical, aliases in _CAPABILITY_ALIASES.items():
        explicit = next((_bool(raw_caps.get(alias)) for alias in aliases if alias in raw_caps), None)
        capabilities[canonical] = explicit if explicit is not None else any(alias in search_blob for alias in aliases)

    seed = "|".join((_key_part(brand), _key_part(model), _key_part(part_number)))
    product_key = f"prod_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"
    try:
        confidence = max(0.0, min(float(payload.get("confidence", 0.0)), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "ok": True,
        "product_key": product_key,
        "brand": brand,
        "model": model,
        "part_number": part_number,
        "name": _norm(payload.get("name")) or f"{brand} {model}",
        "category": _norm(payload.get("category")) or "catalog",
        "description": _norm(payload.get("description")),
        "capabilities": capabilities,
        "protocols": _list(payload.get("protocols")),
        "software_compatibility": _list(payload.get("software_compatibility")),
        "controller_compatibility": _list(payload.get("controller_compatibility")),
        "environment": _norm(payload.get("environment")),
        "specifications": payload.get("specifications") or {},
        "confidence": confidence,
        "offers": payload.get("offers") or [],
    }


def _source_id(payload: dict[str, Any]) -> str:
    supplied_hash = _key_part(payload.get("sha256"))
    if supplied_hash:
        return f"src_{supplied_hash[:24]}"
    seed = "|".join(
        _norm(payload.get(key))
        for key in ("source_ref", "file_name", "supplier_party_id", "supplier_name", "document_date")
    )
    return f"src_{hashlib.sha256(seed.encode()).hexdigest()[:24]}"


def ingest_source(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    source_id = _source_id(payload)
    existing = db[SOURCES_COL].find_one({"source_id": source_id}, {"_id": 0})
    if existing:
        return {"ok": True, "created": False, "idempotent": True, "source": existing}
    doc = {
        "source_id": source_id,
        "source_ref": _norm(payload.get("source_ref")),
        "file_name": _norm(payload.get("file_name")),
        "mime_type": _norm(payload.get("mime_type")),
        "sha256": _norm(payload.get("sha256")),
        "supplier_party_id": _norm(payload.get("supplier_party_id")),
        "supplier_name": _norm(payload.get("supplier_name")),
        "document_date": _norm(payload.get("document_date")),
        "pages": int(payload.get("pages") or 0),
        "status": "ingested",
        "metadata": payload.get("metadata") or {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    db[SOURCES_COL].insert_one(doc)
    return {"ok": True, "created": True, "idempotent": False, "source": doc}


def stage_extraction(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    source_id = _norm(payload.get("source_id"))
    if not source_id or not db[SOURCES_COL].find_one({"source_id": source_id}):
        return {"ok": False, "error": "source_not_found"}
    normalized = [normalize_product(item) for item in payload.get("products") or []]
    errors = [item for item in normalized if not item.get("ok")]
    products = [item for item in normalized if item.get("ok")]
    if not products:
        return {"ok": False, "error": "no_valid_products", "product_errors": errors}
    signature = "|".join(sorted(item["product_key"] for item in products))
    draft_id = f"productdraft_{hashlib.sha256(f'{source_id}|{signature}'.encode()).hexdigest()[:20]}"
    existing = db[DRAFTS_COL].find_one({"draft_id": draft_id}, {"_id": 0})
    if existing:
        return {"ok": True, "created": False, "idempotent": True, "draft": existing}
    draft = {
        "draft_id": draft_id,
        "source_id": source_id,
        "status": "pending_review",
        "products": products,
        "product_errors": errors,
        "created_by": _norm(payload.get("created_by")) or "chatgpt",
        "created_at": _now(),
        "updated_at": _now(),
    }
    db[DRAFTS_COL].insert_one(draft)
    return {"ok": True, "created": True, "idempotent": False, "draft": draft}


def approve(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    draft_id = _norm(payload.get("draft_id"))
    approved_by = _norm(payload.get("approved_by"))
    if not approved_by:
        return {"ok": False, "error": "approved_by_required"}
    draft = db[DRAFTS_COL].find_one({"draft_id": draft_id}, {"_id": 0})
    if not draft:
        return {"ok": False, "error": "draft_not_found"}
    if draft.get("status") == "approved":
        return {"ok": True, "idempotent": True, "draft_id": draft_id, "results": draft.get("results") or []}
    if draft.get("status") != "pending_review":
        return {"ok": False, "error": "draft_not_pending_review", "status": draft.get("status")}

    source = db[SOURCES_COL].find_one({"source_id": draft["source_id"]}, {"_id": 0}) or {}
    selected = set(_list(payload.get("product_keys")))
    results = []
    for product in draft.get("products") or []:
        if selected and product["product_key"] not in selected:
            continue
        item_result = inventory_store.upsert_inventory_item(
            {
                "product_key": product["product_key"],
                "sku": product["part_number"] or product["product_key"],
                "name": product["name"],
                "brand": product["brand"],
                "model": product["model"],
                "part_number": product["part_number"],
                "category": product["category"],
                "long_description": product["description"],
                "capabilities": product["capabilities"],
                "protocols": product["protocols"],
                "software_compatibility": product["software_compatibility"],
                "controller_compatibility": product["controller_compatibility"],
                "environment": product["environment"],
                "specifications": product["specifications"],
                "source_confidence": product["confidence"],
                "source": "product_intelligence",
                "source_doc": source.get("source_ref") or source.get("file_name") or source.get("source_id"),
            }
        )
        offer_results = []
        for offer in product.get("offers") or []:
            offer_results.append(
                inventory_store.upsert_inventory_offer(
                    {
                        **offer,
                        "item_id": item_result["item_id"],
                        "source_doc": offer.get("source_doc")
                        or source.get("source_ref")
                        or source.get("file_name")
                        or source.get("source_id"),
                        "effective_at": offer.get("effective_at") or source.get("document_date"),
                    }
                )
            )
        results.append({"product_key": product["product_key"], "item": item_result, "offers": offer_results})

    db[DRAFTS_COL].update_one(
        {"draft_id": draft_id, "status": "pending_review"},
        {
            "$set": {
                "status": "approved",
                "approved_by": approved_by,
                "approved_at": _now(),
                "updated_at": _now(),
                "results": results,
            }
        },
    )
    return {"ok": True, "idempotent": False, "draft_id": draft_id, "results": results}


def search(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    query: dict[str, Any] = {}
    text = _norm(payload.get("query"))
    if text:
        escaped = inventory_store.accent_insensitive_regex(text)
        query["$or"] = [
            {"name": {"$regex": escaped, "$options": "i"}},
            {"brand": {"$regex": escaped, "$options": "i"}},
            {"model": {"$regex": escaped, "$options": "i"}},
            {"category": {"$regex": escaped, "$options": "i"}},
            {"description": {"$regex": escaped, "$options": "i"}},
            {"sku": {"$regex": escaped, "$options": "i"}},
        ]
    for capability in _list(payload.get("required_capabilities")):
        canonical = _key_part(capability)
        canonical = {"facial": "face", "huella": "fingerprint", "tarjeta": "rfid", "tcpip": "tcp_ip"}.get(
            canonical, canonical
        )
        query[f"capabilities.{canonical}"] = True
    software = _norm(payload.get("software"))
    if software:
        query["software_compatibility"] = {"$regex": re.escape(software), "$options": "i"}

    limit = max(1, min(int(payload.get("limit") or 20), 100))
    items = list(db[COL_INVENTORY_ITEMS].find(query, {"_id": 0}).sort("name", 1).limit(limit))
    max_price = payload.get("max_price")
    for item in items:
        offer_query: dict[str, Any] = {"item_id": item.get("item_id"), "status": "active"}
        if max_price is not None:
            offer_query["price"] = {"$lte": float(max_price)}
        offers = list(db[COL_INVENTORY_OFFERS].find(offer_query, {"_id": 0}).sort([("price", 1), ("effective_at", -1)]))
        item["offers"] = offers
        item["best_offer"] = offers[0] if offers else None
    if max_price is not None:
        items = [item for item in items if item["offers"]]
    return {"ok": True, "count": len(items), "items": items, "filter": query}


def product_intelligence(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    action_n = _norm(action).lower()
    data = payload or {}
    if action_n not in ACTIONS:
        return {"ok": False, "error": "invalid_action", "available": sorted(ACTIONS)}
    if action_n == "ingest_source":
        return ingest_source(data)
    if action_n == "stage_extraction":
        return stage_extraction(data)
    if action_n == "approve":
        return approve(data)
    if action_n == "search":
        return search(data)
    draft = mongo_store.get_db()[DRAFTS_COL].find_one({"draft_id": _norm(data.get("draft_id"))}, {"_id": 0})
    return {"ok": bool(draft), "draft": draft, "error": None if draft else "draft_not_found"}
