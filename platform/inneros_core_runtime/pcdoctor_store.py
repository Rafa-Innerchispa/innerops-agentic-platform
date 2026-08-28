"""PC Doctor operational store for clients, sites, assets, visits and quotes."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bson import ObjectId

from raphiia_openai import local_model_router, mongo_store
from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import (
    COL_OPS_CLIENTS,
    COL_OPS_EQUIPMENT_ASSETS,
    COL_OPS_FIELD_VISIT_EVENTS,
    COL_OPS_FIELD_VISITS,
    COL_OPS_QUOTE_DRAFTS,
    COL_OPS_SITES,
    COL_OPS_TECHNICAL_REPORTS,
)

MEDIA_ROOT = Path(os.getenv("PCDOCTOR_MEDIA_ROOT", "/home/rlopez/data/media/pcdoctor"))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

CLIENT_FIELDS = ("display_name", "legal_name", "trade_name", "tax_id", "phone", "email", "city", "address")
SITE_FIELDS = ("client_id", "name", "address")
ASSET_FIELDS = ("client_id", "site_id", "category")
VISIT_FIELDS = ("client_id", "site_id", "visit_type")

CLIENT_SEARCH_FIELDS = ("client_id", "display_name", "legal_name", "trade_name", "tax_id", "phone", "email", "notes", "tags")
SITE_SEARCH_FIELDS = ("site_id", "client_id", "name", "address", "site_code", "access_notes", "security_notes", "tags")
ASSET_SEARCH_FIELDS = (
    "asset_id",
    "client_id",
    "site_id",
    "asset_tag",
    "category",
    "subtype",
    "brand",
    "model",
    "serial_number",
    "mac_address",
    "ip_address",
    "hostname",
    "location_text",
    "zone",
    "notes",
    "tags",
)
VISIT_SEARCH_FIELDS = ("visit_id", "client_id", "site_id", "visit_type", "summary", "findings", "recommendations", "next_steps", "tags")
QUOTE_SEARCH_FIELDS = ("quote_id", "client_id", "site_id", "visit_id", "title", "status", "notes")

ALLOWED_VISIT_TYPES = {
    "inspection",
    "maintenance",
    "repair",
    "installation",
    "commissioning",
    "audit",
    "troubleshooting",
    "follow_up",
    "quotation",
    "delivery",
}

ALLOWED_CLIENT_STATUS = {"lead", "temporary", "active", "inactive", "archived", "draft"}
ALLOWED_SITE_STATUS = {"draft", "active", "paused", "closed"}
ALLOWED_ASSET_STATUS = {"planned", "installed", "active", "faulty", "maintenance", "removed", "retired", "draft"}
ALLOWED_VISIT_STATUS = {"draft", "in_progress", "waiting_parts", "waiting_client", "completed", "cancelled"}
ALLOWED_QUOTE_STATUS = {"draft", "ready_for_review", "approved", "rejected", "sent", "cancelled"}


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip().lower()


def _signature(*parts: Any) -> str:
    cleaned = [_normalize_key(part) for part in parts if _normalize_key(part)]
    return "::".join(cleaned)


def _client_dedupe_key(doc: dict[str, Any]) -> str:
    tax_id = _norm(_pull(doc, "tax_id", "ruc", "id_number"))
    phone_digits = _norm_digits(_pull(doc, "phone", "whatsapp", "contact_phone"))
    email = _normalize_key(_pull(doc, "email", "contact_email"))
    display_name = _normalize_key(_pull(doc, "display_name", "legal_name", "trade_name", "name"))
    city = _normalize_key(_pull(doc, "city"))
    if tax_id:
        return f"tax_id:{tax_id}"
    if phone_digits:
        return f"phone:{phone_digits}"
    if email:
        return f"email:{email}"
    if display_name:
        return f"name:{display_name}:{city}"
    return ""


def _site_dedupe_key(doc: dict[str, Any]) -> str:
    client_id = _norm(_pull(doc, "client_id", "client_ref"))
    site_code = _normalize_key(_pull(doc, "site_code"))
    name = _normalize_key(_pull(doc, "name", "site_name"))
    address = _normalize_key(_pull(doc, "address"))
    if client_id and site_code:
        return f"client:{client_id}::code:{site_code}"
    if client_id and name:
        return f"client:{client_id}::name:{name}::addr:{address}"
    if name:
        return f"name:{name}::addr:{address}"
    return ""


def _asset_dedupe_key(doc: dict[str, Any]) -> str:
    serial = _normalize_key(_pull(doc, "serial_number"))
    asset_tag = _normalize_key(_pull(doc, "asset_tag"))
    mac = _normalize_key(_pull(doc, "mac_address"))
    client_id = _norm(_pull(doc, "client_id", "client_ref"))
    site_id = _norm(_pull(doc, "site_id", "site_ref"))
    location = _normalize_key(_pull(doc, "location_text"))
    model = _normalize_key(_pull(doc, "model"))
    if serial:
        return f"serial:{serial}"
    if asset_tag:
        return f"tag:{asset_tag}"
    if mac:
        return f"mac:{mac}"
    if client_id and site_id and model:
        return f"client:{client_id}::site:{site_id}::model:{model}::loc:{location}"
    return ""


def _visit_dedupe_key(doc: dict[str, Any]) -> str:
    visit_type = _normalize_key(_pull(doc, "visit_type"))
    client_id = _norm(_pull(doc, "client_id", "client_ref"))
    site_id = _norm(_pull(doc, "site_id", "site_ref"))
    scheduled_at = _normalize_key(_pull(doc, "scheduled_at"))
    started_at = _normalize_key(_pull(doc, "started_at"))
    if client_id and site_id and visit_type and (scheduled_at or started_at):
        return f"client:{client_id}::site:{site_id}::type:{visit_type}::when:{scheduled_at or started_at}"
    return ""


def _quote_dedupe_key(doc: dict[str, Any]) -> str:
    client_id = _norm(_pull(doc, "client_id", "client_ref"))
    site_id = _norm(_pull(doc, "site_id", "site_ref"))
    visit_id = _norm(_pull(doc, "visit_id", "visit_ref"))
    title = _normalize_key(_pull(doc, "title"))
    if visit_id:
        return f"visit:{visit_id}"
    if client_id and site_id and title:
        return f"client:{client_id}::site:{site_id}::title:{title}"
    if client_id and title:
        return f"client:{client_id}::title:{title}"
    return ""


COL_LEGACY_CLIENTS = "clients"
LEGACY_CLIENT_SEARCH_FIELDS = ("client_id", "name", "ruc", "email", "address", "city", "notas")
NON_CANONICAL_STATUSES = ("draft", "promoted")


def _legacy_client_to_match(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "_source": "clients_legacy",
        "client_id": _norm(doc.get("client_id")),
        "display_name": _norm(doc.get("name")),
        "legal_name": _norm(doc.get("name")),
        "trade_name": _norm(doc.get("name")),
        "tax_id": _norm(doc.get("ruc") or doc.get("tax_id")),
        "email": _norm(doc.get("email")),
        "phone": _norm(doc.get("phone")),
        "city": _norm(doc.get("city")),
        "address": _norm(doc.get("address")),
        "status": _norm(doc.get("estado") or "active"),
        "notes": _norm(doc.get("notas")),
    }


def _merge_client_matches(*groups: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for doc in group:
            key = _norm(doc.get("client_id")) or f"legacy:{doc.get('_source')}:{doc.get('display_name')}:{doc.get('tax_id')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(doc)
            if len(merged) >= limit:
                return merged
    return merged


def _find_reusable_by_dedupe(collection: str, dedupe_key: str) -> tuple[str, dict[str, Any]] | None:
    if not dedupe_key:
        return None
    db = _db()
    draft = db[collection].find_one({"dedupe_key": dedupe_key, "status": "draft"})
    if draft:
        return "draft", _serialize(draft)
    canonical = db[collection].find_one(
        {"dedupe_key": dedupe_key, "status": {"$nin": list(NON_CANONICAL_STATUSES)}}
    )
    if canonical:
        return "canonical", _serialize(canonical)
    return None


def _ensure_pcdoctor_indexes() -> None:
    db = _db()
    specs = [
        (COL_OPS_CLIENTS, [("client_id", 1)], {"name": "ux_ops_clients_client_id", "unique": True, "sparse": True}),
        (COL_OPS_CLIENTS, [("tax_id", 1)], {"name": "ux_ops_clients_tax_id", "unique": True, "sparse": True, "partialFilterExpression": {"tax_id": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_CLIENTS, [("phone_digits", 1)], {"name": "ux_ops_clients_phone_digits", "unique": True, "sparse": True, "partialFilterExpression": {"phone_digits": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_CLIENTS, [("dedupe_key", 1)], {"name": "ux_ops_clients_dedupe_key", "unique": True, "sparse": True, "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_SITES, [("site_id", 1)], {"name": "ux_ops_sites_site_id", "unique": True, "sparse": True}),
        (COL_OPS_SITES, [("client_id", 1), ("site_code", 1)], {"name": "ux_ops_sites_client_site_code", "unique": True, "sparse": True, "partialFilterExpression": {"client_id": {"$type": "string", "$ne": ""}, "site_code": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_SITES, [("dedupe_key", 1)], {"name": "ux_ops_sites_dedupe_key", "unique": True, "sparse": True, "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_EQUIPMENT_ASSETS, [("asset_id", 1)], {"name": "ux_ops_assets_asset_id", "unique": True, "sparse": True}),
        (COL_OPS_EQUIPMENT_ASSETS, [("serial_number", 1)], {"name": "ux_ops_assets_serial_number", "unique": True, "sparse": True, "partialFilterExpression": {"serial_number": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_EQUIPMENT_ASSETS, [("asset_tag", 1)], {"name": "ux_ops_assets_asset_tag", "unique": True, "sparse": True, "partialFilterExpression": {"asset_tag": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_EQUIPMENT_ASSETS, [("dedupe_key", 1)], {"name": "ux_ops_assets_dedupe_key", "unique": True, "sparse": True, "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_FIELD_VISITS, [("visit_id", 1)], {"name": "ux_ops_visits_visit_id", "unique": True, "sparse": True}),
        (COL_OPS_FIELD_VISITS, [("draft_id", 1)], {"name": "ux_ops_visits_draft_id", "unique": True, "sparse": True, "partialFilterExpression": {"draft_id": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_FIELD_VISITS, [("dedupe_key", 1)], {"name": "ux_ops_visits_dedupe_key", "unique": True, "sparse": True, "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}}}),
        (COL_OPS_QUOTE_DRAFTS, [("quote_id", 1)], {"name": "ux_ops_quotes_quote_id", "unique": True, "sparse": True}),
        (COL_OPS_QUOTE_DRAFTS, [("dedupe_key", 1)], {"name": "ux_ops_quotes_dedupe_key", "unique": True, "sparse": True, "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}}}),
    ]
    for collection, keys, kwargs in specs:
        try:
            db[collection].create_index(keys, **kwargs)
        except Exception:
            # Best effort: if historical duplicates already exist, keep runtime alive.
            continue


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _new_id(prefix: str) -> str:
    return f"{prefix}_{ObjectId()}"


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _pull(payload: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return default


def _confidence_from_missing(missing: list[str]) -> float:
    total = 6.0
    score = max(0.25, (total - len(missing)) / total)
    return round(min(score, 0.99), 2)


def _search_many(collection: str, fields: tuple[str, ...], identifier: str, limit: int = 10) -> list[dict[str, Any]]:
    db = _db()
    raw = _norm(identifier)
    if not raw:
        return []
    digits = _norm_digits(raw)
    or_filters = [{field: {"$regex": re.escape(raw), "$options": "i"}} for field in fields]
    if digits:
        for field in ("phone", "phone_digits", "whatsapp", "whatsapp_digits", "tax_id", "serial_number", "mac_address", "ip_address"):
            or_filters.append({field: {"$regex": re.escape(digits), "$options": "i"}})
    cursor = db[collection].find({"$or": or_filters}).limit(max(1, min(limit, 50)))
    return [_serialize(doc) for doc in cursor]


def _collection_find_one(collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
    doc = _db()[collection].find_one(query)
    return _serialize(doc) if doc else None


def _upsert(collection: str, query: dict[str, Any], doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    db = _db()
    now = _now_iso()
    payload = {k: v for k, v in doc.items() if v not in (None, "")}
    payload["updated_at"] = now
    existing = db[collection].find_one(query)
    if existing:
        db[collection].update_one({"_id": existing["_id"]}, {"$set": payload})
        return _serialize(db[collection].find_one({"_id": existing["_id"]})), False
    payload.setdefault("created_at", now)
    result = db[collection].insert_one(payload)
    payload["_id"] = result.inserted_id
    return _serialize(payload), True


def _missing(doc: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [field for field in fields if not _norm(doc.get(field))]


def _choose_client_query(doc: dict[str, Any]) -> dict[str, Any]:
    if _norm(doc.get("client_id")):
        return {"client_id": _norm(doc["client_id"])}
    tax_id = _norm(doc.get("tax_id"))
    if tax_id:
        return {"tax_id": tax_id}
    display_name = _norm(doc.get("display_name"))
    if display_name:
        return {"display_name": {"$regex": re.escape(display_name), "$options": "i"}}
    return {"client_id": doc.get("client_id") or _new_id("client")}


def _choose_site_query(doc: dict[str, Any]) -> dict[str, Any]:
    if _norm(doc.get("site_id")):
        return {"site_id": _norm(doc["site_id"])}
    client_id = _norm(doc.get("client_id"))
    name = _norm(doc.get("name"))
    if client_id and name:
        return {"client_id": client_id, "name": {"$regex": re.escape(name), "$options": "i"}}
    return {"site_id": doc.get("site_id") or _new_id("site")}


def _choose_asset_query(doc: dict[str, Any]) -> dict[str, Any]:
    if _norm(doc.get("asset_id")):
        return {"asset_id": _norm(doc["asset_id"])}
    serial = _norm(doc.get("serial_number"))
    if serial:
        return {"serial_number": serial}
    asset_tag = _norm(doc.get("asset_tag"))
    if asset_tag:
        return {"asset_tag": asset_tag}
    return {"asset_id": doc.get("asset_id") or _new_id("asset")}


def _write_media(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    media_id = _new_id("media")
    source = _norm(_pull(payload, "source", default="chatgpt"))
    image_base64 = _norm(_pull(payload, "image_base64"))
    image_url = _norm(_pull(payload, "image_url"))
    file_path = _norm(_pull(payload, "file_path", "path"))
    caption = _norm(_pull(payload, "caption", "prompt"))
    mime_type = _norm(_pull(payload, "mime_type", default="image/png"))
    out_path = MEDIA_ROOT / f"{media_id}.bin"
    bytes_len = 0
    if image_base64:
        data = base64.b64decode(image_base64.split(",", 1)[-1])
        out_path.write_bytes(data)
        bytes_len = len(data)
    elif file_path:
        src = Path(file_path)
        if src.is_file():
            out_path = MEDIA_ROOT / f"{media_id}{src.suffix or '.bin'}"
            shutil.copyfile(src, out_path)
            bytes_len = out_path.stat().st_size
        else:
            out_path = Path(file_path)
    elif image_url:
        parsed = urlparse(image_url)
        out_path = Path(image_url) if parsed.scheme else MEDIA_ROOT / f"{media_id}.url"
    else:
        out_path = MEDIA_ROOT / f"{media_id}.txt"
        out_path.write_text(caption or "media attachment", encoding="utf-8")
        bytes_len = out_path.stat().st_size
    return {
        "media_id": media_id,
        "media_uri": str(out_path),
        "source": source,
        "mime_type": mime_type,
        "caption": caption,
        "ocr_text": _norm(_pull(payload, "ocr_text")),
        "created_at": now,
        "bytes": bytes_len,
        "image_url": image_url,
    }


def create_client_draft(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    phone_digits = _norm_digits(_pull(payload, "phone", "whatsapp", "contact_phone"))
    email_norm = _normalize_key(_pull(payload, "email", "contact_email"))
    preview = {
        "display_name": _norm(_pull(payload, "display_name", "legal_name", "trade_name", "name")),
        "legal_name": _norm(_pull(payload, "legal_name", "display_name", "trade_name", "name")),
        "trade_name": _norm(_pull(payload, "trade_name", "display_name", "legal_name", "name")),
        "tax_id": _norm(_pull(payload, "tax_id", "ruc", "id_number")),
        "phone": _norm(_pull(payload, "phone", "whatsapp", "contact_phone")),
        "phone_digits": phone_digits,
        "email": _norm(_pull(payload, "email", "contact_email")),
        "email_norm": email_norm,
        "city": _norm(_pull(payload, "city")),
    }
    dedupe_key = _client_dedupe_key(preview)
    reusable = _find_reusable_by_dedupe(COL_OPS_CLIENTS, dedupe_key)
    if reusable:
        reused_from, existing = reusable
        missing = _missing(existing, CLIENT_FIELDS)
        confidence = _confidence_from_missing(missing)
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "client_draft": existing,
            "missing_fields": missing,
            "confidence": confidence,
        }
        if reused_from == "canonical":
            out["client_id"] = existing.get("client_id")
            out["client"] = existing
        return out
    draft_id = _new_id("clientdraft")
    doc = {
        **preview,
        "draft_id": draft_id,
        "address": _norm(_pull(payload, "address")),
        "sector": _norm(_pull(payload, "sector")),
        "status": "draft",
        "priority": _norm(_pull(payload, "priority", default="normal")),
        "primary_contact_ids": payload.get("primary_contact_ids") or [],
        "entity_ids": payload.get("entity_ids") or [],
        "notes": _norm(_pull(payload, "notes", "source_note")),
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "dedupe_key": dedupe_key,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    missing = _missing(doc, CLIENT_FIELDS)
    doc["missing_fields"] = missing
    doc["confidence"] = _confidence_from_missing(missing)
    db[COL_OPS_CLIENTS].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_client_draft",
        resource_type="client_draft",
        resource_id=draft_id,
        summary=f"Client draft {doc['display_name'] or draft_id}",
        tool_used="create_client_draft",
        metadata={"missing_fields": missing, "confidence": doc["confidence"], "dedupe_key": dedupe_key},
    )
    return {"ok": True, "reused": False, "draft_id": draft_id, "client_draft": _serialize(doc), "missing_fields": missing, "confidence": doc["confidence"]}


def upsert_client(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "client_draft_id", "draft_id"))
    draft = _collection_find_one(COL_OPS_CLIENTS, {"draft_id": draft_id}) if draft_id else None
    merged = {**(draft or {}), **payload}
    client_id = _norm(_pull(merged, "client_id")) or _new_id("client")
    tax_id = _norm(_pull(merged, "tax_id", "ruc", "id_number"))
    phone_digits = _norm_digits(_pull(merged, "phone", "whatsapp", "contact_phone"))
    email_norm = _normalize_key(_pull(merged, "email", "contact_email"))
    display_name = _norm(_pull(merged, "display_name", "legal_name", "trade_name", "name"))
    existing = None
    if _norm(_pull(merged, "client_id")):
        existing = db[COL_OPS_CLIENTS].find_one({"client_id": _norm(_pull(merged, "client_id"))})
    elif tax_id:
        existing = db[COL_OPS_CLIENTS].find_one({"tax_id": tax_id, "status": {"$ne": "draft"}})
    elif phone_digits:
        existing = db[COL_OPS_CLIENTS].find_one({"phone_digits": phone_digits, "status": {"$ne": "draft"}})
    elif email_norm:
        existing = db[COL_OPS_CLIENTS].find_one({"email_norm": email_norm, "status": {"$ne": "draft"}})
    if not existing and display_name:
        existing = db[COL_OPS_CLIENTS].find_one({"display_name": {"$regex": re.escape(display_name), "$options": "i"}, "status": {"$ne": "draft"}})
    if not existing:
        dedupe_key = _client_dedupe_key(merged)
        if dedupe_key:
            existing = db[COL_OPS_CLIENTS].find_one({"dedupe_key": dedupe_key})
    if existing:
        client_id = _norm(existing.get("client_id") or client_id)
    doc = {
        "client_id": client_id,
        "display_name": display_name,
        "legal_name": _norm(_pull(merged, "legal_name", "display_name", "trade_name", "name")),
        "trade_name": _norm(_pull(merged, "trade_name", "display_name", "legal_name", "name")),
        "tax_id": tax_id,
        "phone": _norm(_pull(merged, "phone", "whatsapp", "contact_phone")),
        "phone_digits": phone_digits,
        "email": _norm(_pull(merged, "email", "contact_email")),
        "email_norm": email_norm,
        "city": _norm(_pull(merged, "city")),
        "address": _norm(_pull(merged, "address")),
        "sector": _norm(_pull(merged, "sector")),
        "status": _norm(_pull(merged, "status", default=(existing or {}).get("status") or ("temporary" if not tax_id else "active"))),
        "priority": _norm(_pull(merged, "priority", default=(existing or {}).get("priority") or "normal")),
        "primary_contact_ids": merged.get("primary_contact_ids") or (existing or {}).get("primary_contact_ids") or [],
        "entity_ids": merged.get("entity_ids") or (existing or {}).get("entity_ids") or [],
        "notes": _norm(_pull(merged, "notes", "source_note")) or (existing or {}).get("notes", ""),
        "tags": merged.get("tags") or (existing or {}).get("tags") or [],
        "source": _norm(_pull(merged, "source", default=(existing or {}).get("source") or "chatgpt_mcp")),
        "dedupe_key": _client_dedupe_key(merged),
        "updated_at": now,
    }
    if doc["status"] not in ALLOWED_CLIENT_STATUS:
        doc["status"] = "active"
    if not existing:
        doc["created_at"] = now
        db[COL_OPS_CLIENTS].insert_one(doc)
        created = True
    else:
        db[COL_OPS_CLIENTS].update_one({"_id": existing["_id"]}, {"$set": doc})
        created = False
    if draft_id:
        db[COL_OPS_CLIENTS].update_one({"draft_id": draft_id}, {"$set": {"status": "promoted", "client_id": client_id, "updated_at": now}})
    saved = _serialize(db[COL_OPS_CLIENTS].find_one({"client_id": client_id}))
    missing = _missing(saved, CLIENT_FIELDS)
    confidence = _confidence_from_missing(missing)
    log_ops_action(
        actor="CHATGPT",
        action="upsert_client",
        resource_type="client",
        resource_id=client_id,
        summary=f"Client {saved.get('display_name') or client_id}",
        tool_used="upsert_client",
        metadata={"created": created, "draft_id": draft_id or None},
    )
    return {"ok": True, "created": created, "client_id": client_id, "client": saved, "missing_fields": missing, "confidence": confidence}


def create_site_draft(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    client_ref = _norm(_pull(payload, "client_ref", "client_id", "client"))
    client_id = ""
    if client_ref:
        client_matches = resolve_client(client_ref).get("matches") or []
        if client_matches:
            client_id = _norm(client_matches[0].get("client_id"))
    preview = {
        "client_ref": client_ref,
        "client_id": client_id,
        "site_code": _norm(_pull(payload, "site_code")),
        "name": _norm(_pull(payload, "name", "site_name")),
        "address": _norm(_pull(payload, "address")),
    }
    dedupe_key = _site_dedupe_key({**preview, **payload})
    reusable = _find_reusable_by_dedupe(COL_OPS_SITES, dedupe_key)
    if reusable:
        reused_from, existing = reusable
        missing = _missing(existing, SITE_FIELDS)
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "site_draft": existing,
            "missing_fields": missing,
            "confidence": _confidence_from_missing(missing),
        }
        if reused_from == "canonical":
            out["site_id"] = existing.get("site_id")
            out["site"] = existing
        return out
    draft_id = _new_id("sitedraft")
    doc = {
        **preview,
        "draft_id": draft_id,
        "type": _norm(_pull(payload, "type", default="other")),
        "city": _norm(_pull(payload, "city")),
        "geo": payload.get("geo") or {},
        "access_notes": _norm(_pull(payload, "access_notes")),
        "security_notes": _norm(_pull(payload, "security_notes")),
        "contact_ids": payload.get("contact_ids") or [],
        "status": "draft",
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "site_code_norm": _normalize_key(_pull(payload, "site_code")),
        "dedupe_key": dedupe_key,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    missing = _missing(doc, SITE_FIELDS)
    doc["missing_fields"] = missing
    doc["confidence"] = _confidence_from_missing(missing)
    db[COL_OPS_SITES].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_site_draft",
        resource_type="site_draft",
        resource_id=draft_id,
        summary=f"Site draft {doc['name'] or draft_id}",
        tool_used="create_site_draft",
        metadata={"client_ref": client_ref, "missing_fields": missing, "confidence": doc["confidence"]},
    )
    return {"ok": True, "reused": False, "draft_id": draft_id, "site_draft": _serialize(doc), "missing_fields": missing, "confidence": doc["confidence"]}


def upsert_site(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "site_draft_id", "draft_id"))
    draft = _collection_find_one(COL_OPS_SITES, {"draft_id": draft_id}) if draft_id else None
    merged = {**(draft or {}), **payload}
    site_id = _norm(_pull(merged, "site_id")) or _new_id("site")
    client_id = _norm(_pull(merged, "client_id", "client_ref"))
    if client_id and not _norm(merged.get("client_id")):
        client_matches = resolve_client(client_id).get("matches") or []
        if client_matches:
            client_id = _norm(client_matches[0].get("client_id"))
    existing = db[COL_OPS_SITES].find_one({"site_id": site_id})
    if not existing and client_id and _norm(_pull(merged, "name", "site_name")):
        existing = db[COL_OPS_SITES].find_one({"client_id": client_id, "name": {"$regex": re.escape(_norm(_pull(merged, "name", "site_name"))), "$options": "i"}, "status": {"$ne": "draft"}})
    if not existing:
        dedupe_key = _site_dedupe_key(merged)
        if dedupe_key:
            existing = db[COL_OPS_SITES].find_one({"dedupe_key": dedupe_key})
    doc = {
        "site_id": site_id,
        "client_id": client_id,
        "site_code": _norm(_pull(merged, "site_code")),
        "name": _norm(_pull(merged, "name", "site_name")),
        "type": _norm(_pull(merged, "type", default=(existing or {}).get("type") or "other")),
        "address": _norm(_pull(merged, "address")),
        "city": _norm(_pull(merged, "city")),
        "geo": merged.get("geo") or (existing or {}).get("geo") or {},
        "access_notes": _norm(_pull(merged, "access_notes")) or (existing or {}).get("access_notes", ""),
        "security_notes": _norm(_pull(merged, "security_notes")) or (existing or {}).get("security_notes", ""),
        "contact_ids": merged.get("contact_ids") or (existing or {}).get("contact_ids") or [],
        "status": _norm(_pull(merged, "status", default=(existing or {}).get("status") or "active")),
        "tags": merged.get("tags") or (existing or {}).get("tags") or [],
        "source": _norm(_pull(merged, "source", default=(existing or {}).get("source") or "chatgpt_mcp")),
        "site_code_norm": _normalize_key(_pull(merged, "site_code")),
        "dedupe_key": _site_dedupe_key(merged),
        "updated_at": now,
    }
    if doc["status"] not in ALLOWED_SITE_STATUS:
        doc["status"] = "active"
    if not existing:
        doc["created_at"] = now
        db[COL_OPS_SITES].insert_one(doc)
        created = True
    else:
        db[COL_OPS_SITES].update_one({"_id": existing["_id"]}, {"$set": doc})
        created = False
    if draft_id:
        db[COL_OPS_SITES].update_one({"draft_id": draft_id}, {"$set": {"status": "promoted", "site_id": site_id, "updated_at": now}})
    saved = _serialize(db[COL_OPS_SITES].find_one({"site_id": site_id}))
    log_ops_action(
        actor="CHATGPT",
        action="upsert_site",
        resource_type="site",
        resource_id=site_id,
        summary=f"Site {saved.get('name') or site_id}",
        tool_used="upsert_site",
        metadata={"created": created, "client_id": client_id, "draft_id": draft_id or None},
    )
    return {"ok": True, "created": created, "site_id": site_id, "site": saved}


def create_asset_draft(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    client_ref = _norm(_pull(payload, "client_ref", "client_id"))
    site_ref = _norm(_pull(payload, "site_ref", "site_id"))
    client_id = ""
    site_id = ""
    if client_ref:
        client_matches = resolve_client(client_ref).get("matches") or []
        if client_matches:
            client_id = _norm(client_matches[0].get("client_id"))
    if site_ref:
        site_matches = resolve_site(site_ref).get("matches") or []
        if site_matches:
            site_id = _norm(site_matches[0].get("site_id"))
    preview = {
        "client_ref": client_ref,
        "client_id": client_id,
        "site_ref": site_ref,
        "site_id": site_id,
        "asset_tag": _norm(_pull(payload, "asset_tag")),
        "category": _norm(_pull(payload, "category")),
        "serial_number": _norm(_pull(payload, "serial_number", "serial")),
        "mac_address": _norm(_pull(payload, "mac_address")),
        "model": _norm(_pull(payload, "model")),
        "location_text": _norm(_pull(payload, "location_text")),
    }
    dedupe_key = _asset_dedupe_key({**preview, **payload})
    reusable = _find_reusable_by_dedupe(COL_OPS_EQUIPMENT_ASSETS, dedupe_key)
    if reusable:
        reused_from, existing = reusable
        missing = _missing(existing, ASSET_FIELDS)
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "asset_draft": existing,
            "missing_fields": missing,
            "confidence": _confidence_from_missing(missing),
        }
        if reused_from == "canonical":
            out["asset_id"] = existing.get("asset_id")
            out["asset"] = existing
        return out
    draft_id = _new_id("assetdraft")
    doc = {
        **preview,
        "draft_id": draft_id,
        "subtype": _norm(_pull(payload, "subtype")),
        "brand": _norm(_pull(payload, "brand")),
        "ip_address": _norm(_pull(payload, "ip_address")),
        "hostname": _norm(_pull(payload, "hostname")),
        "firmware_version": _norm(_pull(payload, "firmware_version")),
        "zone": _norm(_pull(payload, "zone")),
        "mount_type": _norm(_pull(payload, "mount_type")),
        "power_source": _norm(_pull(payload, "power_source")),
        "connectivity": _norm(_pull(payload, "connectivity")),
        "status": "draft",
        "ownership": _norm(_pull(payload, "ownership", default="unknown")),
        "purchase_info": payload.get("purchase_info") or {},
        "warranty": payload.get("warranty") or {},
        "notes": _norm(_pull(payload, "notes", "source_note")),
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "dedupe_key": dedupe_key,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    missing = _missing(doc, ASSET_FIELDS)
    doc["missing_fields"] = missing
    doc["confidence"] = _confidence_from_missing(missing)
    db[COL_OPS_EQUIPMENT_ASSETS].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_asset_draft",
        resource_type="asset_draft",
        resource_id=draft_id,
        summary=f"Asset draft {doc['brand']} {doc['model']}".strip(),
        tool_used="create_asset_draft",
        metadata={"client_ref": client_ref, "site_ref": site_ref, "missing_fields": missing, "confidence": doc["confidence"]},
    )
    return {"ok": True, "reused": False, "draft_id": draft_id, "asset_draft": _serialize(doc), "missing_fields": missing, "confidence": doc["confidence"]}


def upsert_asset(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "asset_draft_id", "draft_id"))
    draft = _collection_find_one(COL_OPS_EQUIPMENT_ASSETS, {"draft_id": draft_id}) if draft_id else None
    merged = {**(draft or {}), **payload}
    asset_id = _norm(_pull(merged, "asset_id")) or _new_id("asset")
    client_id = _norm(_pull(merged, "client_id", "client_ref"))
    site_id = _norm(_pull(merged, "site_id", "site_ref"))
    if client_id and not _norm(merged.get("client_id")):
        client_matches = resolve_client(client_id).get("matches") or []
        if client_matches:
            client_id = _norm(client_matches[0].get("client_id"))
    if site_id and not _norm(merged.get("site_id")):
        site_matches = resolve_site(site_id).get("matches") or []
        if site_matches:
            site_id = _norm(site_matches[0].get("site_id"))
    existing = db[COL_OPS_EQUIPMENT_ASSETS].find_one({"asset_id": asset_id})
    if not existing and _norm(_pull(merged, "serial_number", "serial")):
        serial = _norm(_pull(merged, "serial_number", "serial"))
        existing = db[COL_OPS_EQUIPMENT_ASSETS].find_one({"serial_number": serial, "status": {"$ne": "draft"}})
    if not existing and _norm(_pull(merged, "asset_tag")):
        existing = db[COL_OPS_EQUIPMENT_ASSETS].find_one({"asset_tag": _norm(_pull(merged, "asset_tag")), "status": {"$ne": "draft"}})
    if not existing and _norm(_pull(merged, "mac_address")):
        existing = db[COL_OPS_EQUIPMENT_ASSETS].find_one({"mac_address": _norm(_pull(merged, "mac_address")), "status": {"$ne": "draft"}})
    if not existing:
        dedupe_key = _asset_dedupe_key(merged)
        if dedupe_key:
            existing = db[COL_OPS_EQUIPMENT_ASSETS].find_one({"dedupe_key": dedupe_key})
    doc = {
        "asset_id": asset_id,
        "client_id": client_id,
        "site_id": site_id,
        "asset_tag": _norm(_pull(merged, "asset_tag")),
        "category": _norm(_pull(merged, "category")),
        "subtype": _norm(_pull(merged, "subtype")),
        "brand": _norm(_pull(merged, "brand")),
        "model": _norm(_pull(merged, "model")),
        "serial_number": _norm(_pull(merged, "serial_number", "serial")),
        "mac_address": _norm(_pull(merged, "mac_address")),
        "ip_address": _norm(_pull(merged, "ip_address")),
        "hostname": _norm(_pull(merged, "hostname")),
        "firmware_version": _norm(_pull(merged, "firmware_version")),
        "location_text": _norm(_pull(merged, "location_text")),
        "zone": _norm(_pull(merged, "zone")),
        "mount_type": _norm(_pull(merged, "mount_type")),
        "power_source": _norm(_pull(merged, "power_source")),
        "connectivity": _norm(_pull(merged, "connectivity")),
        "status": _norm(_pull(merged, "status", default=(existing or {}).get("status") or "active")),
        "ownership": _norm(_pull(merged, "ownership", default=(existing or {}).get("ownership") or "unknown")),
        "purchase_info": merged.get("purchase_info") or (existing or {}).get("purchase_info") or {},
        "warranty": merged.get("warranty") or (existing or {}).get("warranty") or {},
        "notes": _norm(_pull(merged, "notes", "source_note")) or (existing or {}).get("notes", ""),
        "tags": merged.get("tags") or (existing or {}).get("tags") or [],
        "source": _norm(_pull(merged, "source", default=(existing or {}).get("source") or "chatgpt_mcp")),
        "serial_digits": _norm_digits(_pull(merged, "serial_number", "serial")),
        "asset_tag_norm": _normalize_key(_pull(merged, "asset_tag")),
        "dedupe_key": _asset_dedupe_key(merged),
        "updated_at": now,
    }
    if doc["status"] not in ALLOWED_ASSET_STATUS:
        doc["status"] = "active"
    if not existing:
        doc["created_at"] = now
        db[COL_OPS_EQUIPMENT_ASSETS].insert_one(doc)
        created = True
    else:
        db[COL_OPS_EQUIPMENT_ASSETS].update_one({"_id": existing["_id"]}, {"$set": doc})
        created = False
    if draft_id:
        db[COL_OPS_EQUIPMENT_ASSETS].update_one({"draft_id": draft_id}, {"$set": {"status": "promoted", "asset_id": asset_id, "updated_at": now}})
    saved = _serialize(db[COL_OPS_EQUIPMENT_ASSETS].find_one({"asset_id": asset_id}))
    log_ops_action(
        actor="CHATGPT",
        action="upsert_asset",
        resource_type="asset",
        resource_id=asset_id,
        summary=f"Asset {saved.get('brand')} {saved.get('model')}".strip(),
        tool_used="upsert_asset",
        metadata={"created": created, "client_id": client_id, "site_id": site_id, "draft_id": draft_id or None},
    )
    return {"ok": True, "created": created, "asset_id": asset_id, "asset": saved}


def create_visit_draft(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    client_ref = _norm(_pull(payload, "client_ref", "client_id"))
    site_ref = _norm(_pull(payload, "site_ref", "site_id"))
    client_id = ""
    site_id = ""
    if client_ref:
        client_matches = resolve_client(client_ref).get("matches") or []
        if client_matches:
            client_id = _norm(client_matches[0].get("client_id"))
    if site_ref:
        site_matches = resolve_site(site_ref).get("matches") or []
        if site_matches:
            site_id = _norm(site_matches[0].get("site_id"))
    visit_type = _norm(_pull(payload, "visit_type", default="inspection"))
    if visit_type not in ALLOWED_VISIT_TYPES:
        visit_type = "inspection"
    preview = {
        "client_ref": client_ref,
        "client_id": client_id,
        "site_ref": site_ref,
        "site_id": site_id,
        "visit_type": visit_type,
        "scheduled_at": _norm(_pull(payload, "scheduled_at")),
        "started_at": _norm(_pull(payload, "started_at")),
    }
    dedupe_key = _visit_dedupe_key({**preview, **payload})
    reusable = _find_reusable_by_dedupe(COL_OPS_FIELD_VISITS, dedupe_key)
    if reusable:
        reused_from, existing = reusable
        missing = _missing(existing, VISIT_FIELDS)
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "visit_draft": existing,
            "missing_fields": missing,
            "confidence": _confidence_from_missing(missing),
        }
        if reused_from == "canonical":
            out["visit_id"] = existing.get("visit_id")
            out["visit"] = existing
        return out
    draft_id = _new_id("visitdraft")
    doc = {
        **preview,
        "draft_id": draft_id,
        "status": "draft",
        "technician_ids": payload.get("technician_ids") or [],
        "supervisor_id": _norm(_pull(payload, "supervisor_id")),
        "ended_at": _norm(_pull(payload, "ended_at")),
        "summary": _norm(_pull(payload, "summary", "source_note")),
        "findings": payload.get("findings") or [],
        "recommendations": payload.get("recommendations") or [],
        "next_steps": payload.get("next_steps") or [],
        "risk_level": _norm(_pull(payload, "risk_level", default="medium")),
        "billing_ready": bool(payload.get("billing_ready", False)),
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "dedupe_key": dedupe_key,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    missing = _missing(doc, VISIT_FIELDS)
    doc["missing_fields"] = missing
    doc["confidence"] = _confidence_from_missing(missing)
    db[COL_OPS_FIELD_VISITS].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_visit_draft",
        resource_type="visit_draft",
        resource_id=draft_id,
        summary=f"Visit draft {visit_type}",
        tool_used="create_visit_draft",
        metadata={"client_ref": client_ref, "site_ref": site_ref, "missing_fields": missing, "confidence": doc["confidence"]},
    )
    return {"ok": True, "reused": False, "draft_id": draft_id, "visit_draft": _serialize(doc), "missing_fields": missing, "confidence": doc["confidence"]}


def log_service_visit(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "visit_draft_id", "draft_id"))
    visit_id = _norm(_pull(payload, "visit_id")) or _new_id("visit")
    client_id = _norm(_pull(payload, "client_id", "client_ref"))
    site_id = _norm(_pull(payload, "site_id", "site_ref"))
    if client_id and not _norm(payload.get("client_id")):
        client_matches = resolve_client(client_id).get("matches") or []
        if client_matches:
            client_id = _norm(client_matches[0].get("client_id"))
    if site_id and not _norm(payload.get("site_id")):
        site_matches = resolve_site(site_id).get("matches") or []
        if site_matches:
            site_id = _norm(site_matches[0].get("site_id"))
    visit_type = _norm(_pull(payload, "visit_type", default="inspection"))
    if visit_type not in ALLOWED_VISIT_TYPES:
        visit_type = "inspection"
    status = _norm(_pull(payload, "status", default=("completed" if payload.get("ended_at") else "in_progress")))
    if status not in ALLOWED_VISIT_STATUS:
        status = "in_progress"
    doc = {
        "visit_id": visit_id,
        "client_id": client_id,
        "site_id": site_id,
        "visit_type": visit_type,
        "status": status,
        "technician_ids": payload.get("technician_ids") or [],
        "supervisor_id": _norm(_pull(payload, "supervisor_id")),
        "scheduled_at": _norm(_pull(payload, "scheduled_at")),
        "started_at": _norm(_pull(payload, "started_at")),
        "ended_at": _norm(_pull(payload, "ended_at")),
        "summary": _norm(_pull(payload, "summary", "source_note")),
        "findings": payload.get("findings") or [],
        "recommendations": payload.get("recommendations") or [],
        "next_steps": payload.get("next_steps") or [],
        "risk_level": _norm(_pull(payload, "risk_level", default="medium")),
        "billing_ready": bool(payload.get("billing_ready", False)),
        "tags": payload.get("tags") or [],
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "dedupe_key": _visit_dedupe_key(payload),
        "updated_at": now,
    }
    existing = db[COL_OPS_FIELD_VISITS].find_one({"visit_id": visit_id})
    if existing:
        db[COL_OPS_FIELD_VISITS].update_one({"_id": existing["_id"]}, {"$set": doc})
        created = False
    else:
        doc["created_at"] = now
        db[COL_OPS_FIELD_VISITS].insert_one(doc)
        created = True
    if draft_id:
        db[COL_OPS_FIELD_VISITS].update_one({"draft_id": draft_id}, {"$set": {"status": status, "visit_id": visit_id, "updated_at": now}})
    saved = _serialize(db[COL_OPS_FIELD_VISITS].find_one({"visit_id": visit_id}))
    log_ops_action(
        actor="CHATGPT",
        action="log_service_visit",
        resource_type="visit",
        resource_id=visit_id,
        summary=f"Visit {visit_type} {status}",
        tool_used="log_service_visit",
        metadata={"created": created, "client_id": client_id, "site_id": site_id},
    )
    return {"ok": True, "created": created, "visit_id": visit_id, "visit": saved}


def add_observation(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    event_id = _new_id("obs")
    now = _now_iso()
    event = {
        "event_id": event_id,
        "event_type": _norm(_pull(payload, "type", default="unknown")),
        "source": _norm(_pull(payload, "source", default="manual")),
        "visit_id": _norm(_pull(payload, "visit_id")),
        "client_id": _norm(_pull(payload, "client_id", "client_ref")),
        "site_id": _norm(_pull(payload, "site_id", "site_ref")),
        "asset_id": _norm(_pull(payload, "asset_id", "asset_ref")),
        "content": _norm(_pull(payload, "content", "body")),
        "normalized_value": _norm(_pull(payload, "normalized_value")),
        "confidence": float(payload.get("confidence", 0.7)),
        "needs_review": bool(payload.get("needs_review", False)),
        "tags": payload.get("tags") or [],
        "created_at": now,
        "updated_at": now,
    }
    db[COL_OPS_FIELD_VISIT_EVENTS].insert_one(event)
    log_ops_action(
        actor="CHATGPT",
        action="add_observation",
        resource_type="visit_event",
        resource_id=event_id,
        summary=f"Observation {event['event_type']}",
        tool_used="add_observation",
        metadata={"visit_id": event["visit_id"], "client_id": event["client_id"], "site_id": event["site_id"], "asset_id": event["asset_id"]},
    )
    return {"ok": True, "observation_id": event_id, "observation": _serialize(event)}


def attach_media_to_visit(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    media = _write_media(payload)
    event_id = _new_id("mediaevent")
    event = {
        "event_id": event_id,
        "event_type": "media_attachment",
        "source": _norm(_pull(payload, "source", default="chatgpt")),
        "visit_id": _norm(_pull(payload, "visit_id")),
        "client_id": _norm(_pull(payload, "client_id")),
        "site_id": _norm(_pull(payload, "site_id")),
        "asset_id": _norm(_pull(payload, "asset_id")),
        "kind": _norm(_pull(payload, "kind", default="photo")),
        "media_id": media["media_id"],
        "media_uri": media["media_uri"],
        "mime_type": media["mime_type"],
        "ocr_text": _norm(_pull(payload, "ocr_text")) or media.get("ocr_text", ""),
        "caption": _norm(_pull(payload, "caption", "prompt")) or media.get("caption", ""),
        "tags": payload.get("tags") or [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    db[COL_OPS_FIELD_VISIT_EVENTS].insert_one(event)
    log_ops_action(
        actor="CHATGPT",
        action="attach_media_to_visit",
        resource_type="visit_event",
        resource_id=event_id,
        summary=f"Media attached to visit {event['visit_id'] or ''}".strip(),
        tool_used="attach_media_to_visit",
        metadata={"visit_id": event["visit_id"], "asset_id": event["asset_id"], "media_uri": event["media_uri"]},
    )
    return {"ok": True, "event_id": event_id, "media": media, "event": _serialize(event)}


def attach_media_to_asset(payload: dict[str, Any]) -> dict[str, Any]:
    result = attach_media_to_visit(payload)
    if result.get("ok"):
        log_ops_action(
            actor="CHATGPT",
            action="attach_media_to_asset",
            resource_type="asset_media",
            resource_id=_norm(_pull(payload, "asset_id")) or None,
            summary="Media attached to asset",
            tool_used="attach_media_to_asset",
            metadata={"asset_id": _norm(_pull(payload, "asset_id")), "media_uri": result.get("media", {}).get("media_uri")},
        )
    return result


def extract_fields_from_media(media_id: str) -> dict[str, Any]:
    db = _db()
    needle = _norm(media_id)
    event = db[COL_OPS_FIELD_VISIT_EVENTS].find_one({"$or": [{"media_id": needle}, {"event_id": needle}]})
    if not event:
        return {"ok": False, "error": "media not found"}
    text = "\n".join(
        part
        for part in (
            _norm(event.get("ocr_text")),
            _norm(event.get("caption")),
            _norm(event.get("media_uri")),
            _norm(event.get("event_type")),
        )
        if part
    )
    prompt = (
        "Extrae seriales, modelos, IPs, MACs, marcas, ubicacion y equipo desde el siguiente texto. "
        "Devuelve JSON compacto con keys: device_type, brand, model, serial_number, ip_address, mac_address, location_text, zone, confidence, needs_review.\n\n"
        f"{text}"
    )
    model_result = local_model_router.run_local_model(task_type="vision_ocr", prompt=prompt, model="llava:7b", max_tokens=300)
    extracted = {
        "device_type": None,
        "brand": None,
        "model": None,
        "serial_number": None,
        "ip_address": None,
        "mac_address": None,
        "location_text": None,
        "zone": None,
        "confidence": 0.35,
        "needs_review": True,
    }
    patterns = {
        "serial_number": re.compile(r"(?:serial(?: number| no| #)?|s/n)[:\s]*([A-Z0-9-]{4,})", re.I),
        "ip_address": re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\b"),
        "mac_address": re.compile(r"\b([0-9A-F]{2}(?:[:-][0-9A-F]{2}){5})\b", re.I),
        "model": re.compile(r"\bmodel(?:o)?[:\s]*([A-Z0-9._-]{3,})", re.I),
        "brand": re.compile(r"\bbrand[:\s]*([A-Z0-9._-]{2,})", re.I),
    }
    for key, rx in patterns.items():
        m = rx.search(text)
        if m:
            extracted[key] = m.group(1).strip()
    location = re.search(r"\b(entrada|salida|jardin|patio|lobby|rack\s*\d+|oficina|bodega|parking|garage)\b", text, re.I)
    if location:
        extracted["location_text"] = location.group(1)
    if extracted.get("serial_number") or extracted.get("ip_address") or extracted.get("mac_address"):
        extracted["confidence"] = 0.7
        extracted["needs_review"] = False
    db[COL_OPS_FIELD_VISIT_EVENTS].update_one({"_id": event["_id"]}, {"$set": {"extracted_fields": extracted, "extracted_at": _now_iso(), "updated_at": _now_iso()}})
    return {"ok": True, "media_id": needle, "source_event": _serialize(event), "extracted_fields": extracted, "model_result": model_result}


def link_asset_to_client(asset_id: str, client_id: str) -> dict[str, Any]:
    _db()[COL_OPS_EQUIPMENT_ASSETS].update_one({"asset_id": asset_id}, {"$set": {"client_id": client_id, "updated_at": _now_iso()}})
    log_ops_action(actor="CHATGPT", action="link_asset_to_client", resource_type="asset", resource_id=asset_id, summary=f"Asset linked to client {client_id}", tool_used="link_asset_to_client", metadata={"client_id": client_id})
    return {"ok": True, "asset_id": asset_id, "client_id": client_id}


def link_asset_to_site(asset_id: str, site_id: str) -> dict[str, Any]:
    _db()[COL_OPS_EQUIPMENT_ASSETS].update_one({"asset_id": asset_id}, {"$set": {"site_id": site_id, "updated_at": _now_iso()}})
    log_ops_action(actor="CHATGPT", action="link_asset_to_site", resource_type="asset", resource_id=asset_id, summary=f"Asset linked to site {site_id}", tool_used="link_asset_to_site", metadata={"site_id": site_id})
    return {"ok": True, "asset_id": asset_id, "site_id": site_id}


def resolve_client(identifier: str, limit: int = 10) -> dict[str, Any]:
    ops_matches = _search_many(COL_OPS_CLIENTS, CLIENT_SEARCH_FIELDS, identifier, limit=limit)
    legacy_raw = _search_many(COL_LEGACY_CLIENTS, LEGACY_CLIENT_SEARCH_FIELDS, identifier, limit=limit)
    legacy_matches = [_legacy_client_to_match(doc) for doc in legacy_raw]
    matches = _merge_client_matches(ops_matches, legacy_matches, limit=limit)
    sources = sorted({m.get("_source", "ops_clients") for m in matches})
    return {
        "ok": True,
        "count": len(matches),
        "matches": matches,
        "best_match": matches[0] if matches else None,
        "sources": sources,
    }


def list_clients(limit: int = 25, scope: str = "pcdoctor") -> dict[str, Any]:
    """Lista clientes según ámbito.

    scope:
      - pcdoctor (default): clientes operativos PC Doctor (colección legacy `clients`)
      - contifico: personas marcadas es_cliente en Contífico importado
      - all: mezcla legacy + ops (comportamiento anterior)
    """
    limit = max(1, min(int(limit), 100))
    db = _db()
    scope_norm = (scope or "pcdoctor").strip().lower()
    total_legacy = db[COL_LEGACY_CLIENTS].count_documents({})
    total_ops = db[COL_OPS_CLIENTS].count_documents({})
    total_contifico = 0
    try:
        total_contifico = db["contifico_personas"].count_documents({"es_cliente": True})
    except Exception:
        pass

    if scope_norm == "contifico":
        rows = list(
            db["contifico_personas"]
            .find({"es_cliente": True}, {"_id": 0, "persona_id": 1, "nombre": 1, "ruc": 1, "client_id": 1})
            .sort("nombre_norm", 1)
            .limit(limit)
        )
        matches = [
            {
                "_source": "contifico_personas",
                "client_id": _norm(row.get("client_id") or row.get("persona_id")),
                "display_name": _norm(row.get("nombre")),
                "tax_id": _norm(row.get("ruc")),
            }
            for row in rows
        ]
        return {
            "ok": True,
            "scope": "contifico",
            "count": len(matches),
            "total_legacy": total_legacy,
            "total_ops": total_ops,
            "total_contifico": total_contifico,
            "matches": matches,
        }

    legacy = list(db[COL_LEGACY_CLIENTS].find({}, {"_id": 0}).sort("display_name", 1).limit(limit))
    legacy_matches = [_legacy_client_to_match(doc) for doc in legacy]

    if scope_norm == "pcdoctor":
        matches = legacy_matches[:limit]
        return {
            "ok": True,
            "scope": "pcdoctor",
            "count": len(matches),
            "total_legacy": total_legacy,
            "total_ops": total_ops,
            "total_contifico": total_contifico,
            "matches": matches,
        }

    ops = list(db[COL_OPS_CLIENTS].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit))
    matches = _merge_client_matches(
        [_legacy_client_to_match(doc) for doc in ops],
        legacy_matches,
        limit=limit,
    )
    return {
        "ok": True,
        "scope": "all",
        "count": len(matches),
        "total_legacy": total_legacy,
        "total_ops": total_ops,
        "total_contifico": total_contifico,
        "matches": matches,
    }


def resolve_site(identifier: str, limit: int = 10) -> dict[str, Any]:
    matches = _search_many(COL_OPS_SITES, SITE_SEARCH_FIELDS, identifier, limit=limit)
    return {"ok": True, "count": len(matches), "matches": matches, "best_match": matches[0] if matches else None}


def resolve_asset(identifier: str, limit: int = 10) -> dict[str, Any]:
    matches = _search_many(COL_OPS_EQUIPMENT_ASSETS, ASSET_SEARCH_FIELDS, identifier, limit=limit)
    return {"ok": True, "count": len(matches), "matches": matches, "best_match": matches[0] if matches else None}


def list_client_sites(client_id: str) -> dict[str, Any]:
    cursor = _db()[COL_OPS_SITES].find({"client_id": client_id}).sort("updated_at", -1)
    items = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(items), "sites": items}


def list_site_assets(site_id: str) -> dict[str, Any]:
    cursor = _db()[COL_OPS_EQUIPMENT_ASSETS].find({"site_id": site_id}).sort("updated_at", -1)
    items = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(items), "assets": items}


def create_quote_draft(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    preview = {
        "client_id": _norm(_pull(payload, "client_id", "client_ref")),
        "site_id": _norm(_pull(payload, "site_id", "site_ref")),
        "visit_id": _norm(_pull(payload, "visit_id", "visit_ref")),
        "title": _norm(_pull(payload, "title", default="PC Doctor Quote Draft")),
    }
    dedupe_key = _quote_dedupe_key({**preview, **payload})
    reusable = _find_reusable_by_dedupe(COL_OPS_QUOTE_DRAFTS, dedupe_key)
    if reusable:
        reused_from, existing = reusable
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "quote_id": existing.get("quote_id"),
            "quote_draft": existing,
        }
        return out
    quote_id = _new_id("quotedraft")
    line_items = payload.get("line_items") or []
    subtotal = 0.0
    for item in line_items:
        qty = float(item.get("quantity", 1) or 1)
        price = float(item.get("unit_price", item.get("price", 0)) or 0)
        subtotal += qty * price
    tax_rate = float(payload.get("tax_rate", 0.0) or 0.0)
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    entity_id = _norm(_pull(payload, "entity_id", default="ent_pcdoctor"))
    display_number = _norm(_pull(payload, "display_number"))
    numbering_namespace = _norm(_pull(payload, "numbering_namespace", default="ralfia"))
    if not display_number and numbering_namespace == "ralfia":
        from raphiia_openai.operational.document_numbering import reserve_document_number
        num = reserve_document_number("quote", entity_id=entity_id)
        if num.get("ok"):
            display_number = num.get("display_number") or ""
    doc = {
        "quote_id": quote_id,
        "client_id": preview["client_id"],
        "site_id": preview["site_id"],
        "visit_id": preview["visit_id"],
        "title": preview["title"],
        "status": _norm(_pull(payload, "status", default="draft")),
        "currency": _norm(_pull(payload, "currency", default="USD")),
        "line_items": line_items,
        "subtotal": round(subtotal, 2),
        "tax_rate": tax_rate,
        "tax": tax,
        "total": total,
        "entity_id": entity_id,
        "display_number": display_number,
        "numbering_namespace": numbering_namespace,
        "billing_ready": bool(payload.get("billing_ready", False)),
        "notes": _norm(_pull(payload, "notes", "source_note")),
        "approved_by": _norm(_pull(payload, "approved_by")),
        "created_by": _norm(_pull(payload, "created_by", default="CHATGPT")),
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "dedupe_key": _quote_dedupe_key(payload),
        "created_at": now,
        "updated_at": now,
    }
    if doc["status"] not in ALLOWED_QUOTE_STATUS:
        doc["status"] = "draft"
    db[COL_OPS_QUOTE_DRAFTS].insert_one(doc)
    log_ops_action(actor="CHATGPT", action="create_quote_draft", resource_type="quote_draft", resource_id=quote_id, summary=f"Quote draft {doc['title']}", tool_used="create_quote_draft", metadata={"client_id": doc["client_id"], "site_id": doc["site_id"], "visit_id": doc["visit_id"]})
    return {"ok": True, "reused": False, "quote_id": quote_id, "quote_draft": _serialize(doc)}


def update_quote_draft(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    quote_id = _norm(_pull(payload, "quote_id", "draft_id"))
    if not quote_id:
        return {"ok": False, "error": "quote_id required"}
    doc = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote_id})
    if not doc:
        return {"ok": False, "error": "quote not found"}
    patch = {k: v for k, v in payload.items() if k not in {"quote_id", "draft_id", "_id"}}
    if "status" in patch and patch["status"] not in ALLOWED_QUOTE_STATUS:
        patch["status"] = "draft"
    if "line_items" in patch:
        subtotal = 0.0
        normalized_items = []
        for item in patch.get("line_items") or []:
            row = dict(item)
            qty = float(row.get("quantity", 1) or 1)
            if abs(qty - round(qty)) < 1e-9:
                row["quantity"] = int(round(qty))
                qty = float(row["quantity"])
            price = float(row.get("unit_price", row.get("price", 0)) or 0)
            row["total"] = round(qty * price, 2)
            subtotal += row["total"]
            normalized_items.append(row)
        patch["line_items"] = normalized_items
        patch["subtotal"] = round(subtotal, 2)
        patch["tax"] = round(subtotal * float(patch.get("tax_rate", doc.get("tax_rate", 0.0)) or 0.0), 2)
        patch["total"] = round(patch["subtotal"] + patch["tax"], 2)
    patch["dedupe_key"] = _quote_dedupe_key({**doc, **patch})
    patch["updated_at"] = now
    db[COL_OPS_QUOTE_DRAFTS].update_one({"_id": doc["_id"]}, {"$set": patch})
    updated = db[COL_OPS_QUOTE_DRAFTS].find_one({"_id": doc["_id"]})
    log_ops_action(actor="CHATGPT", action="update_quote_draft", resource_type="quote_draft", resource_id=quote_id, summary=f"Quote draft updated {quote_id}", tool_used="update_quote_draft", metadata={"status": patch.get("status", doc.get("status"))})
    return {"ok": True, "quote_draft": _serialize(updated)}


def generate_supervisor_report(client_id: str, site_id: str | None = None, visit_id: str | None = None) -> dict[str, Any]:
    db = _db()
    client = db[COL_OPS_CLIENTS].find_one({"client_id": client_id})
    site = db[COL_OPS_SITES].find_one({"site_id": site_id}) if site_id else None
    visit = db[COL_OPS_FIELD_VISITS].find_one({"visit_id": visit_id}) if visit_id else None
    assets_query: dict[str, Any] = {"client_id": client_id}
    if site_id:
        assets_query["site_id"] = site_id
    assets = [_serialize(doc) for doc in db[COL_OPS_EQUIPMENT_ASSETS].find(assets_query).sort("updated_at", -1).limit(50)]
    observations_query: dict[str, Any] = {"client_id": client_id}
    if site_id:
        observations_query["site_id"] = site_id
    if visit_id:
        observations_query["visit_id"] = visit_id
    observations = [_serialize(doc) for doc in db[COL_OPS_FIELD_VISIT_EVENTS].find(observations_query).sort("created_at", -1).limit(100)]
    quotes_query: dict[str, Any] = {"client_id": client_id}
    if site_id:
        quotes_query["site_id"] = site_id
    if visit_id:
        quotes_query["visit_id"] = visit_id
    quotes = [_serialize(doc) for doc in db[COL_OPS_QUOTE_DRAFTS].find(quotes_query).sort("updated_at", -1).limit(20)]
    summary_payload = {"client": _serialize(client), "site": _serialize(site), "visit": _serialize(visit), "assets": assets[:20], "observations": observations[:30], "quotes": quotes[:10]}
    prompt = json.dumps(summary_payload, ensure_ascii=False, indent=2)
    model_result = local_model_router.run_local_model(task_type="technical_report", prompt=prompt, max_tokens=700, temperature=0.2)
    if model_result.get("ok"):
        report_markdown = model_result.get("response", "")
    else:
        lines = [
            f"# Supervisor Report - {_norm((client or {}).get('display_name') or client_id)}",
            "",
            f"- Client ID: {client_id}",
            f"- Site ID: {site_id or 'n/a'}",
            f"- Visit ID: {visit_id or 'n/a'}",
            f"- Assets: {len(assets)}",
            f"- Observations: {len(observations)}",
            f"- Quotes: {len(quotes)}",
            "",
            "## Findings",
        ]
        for obs in observations[:10]:
            lines.append(f"- {obs.get('event_type', 'observation')}: {obs.get('content', '')}".strip())
        lines += ["", "## Next Steps"]
        if visit:
            for item in (visit.get("next_steps") or [])[:10]:
                lines.append(f"- {item}")
        else:
            lines.append("- Review visit data and confirm billing readiness.")
        report_markdown = "\n".join(lines).strip() + "\n"
    report_id = _new_id("report")
    report_doc = {"report_id": report_id, "client_id": client_id, "site_id": site_id, "visit_id": visit_id, "report_markdown": report_markdown, "source": "chatgpt_mcp", "model_result": model_result, "created_at": _now_iso(), "updated_at": _now_iso()}
    db[COL_OPS_TECHNICAL_REPORTS].insert_one(report_doc)
    log_ops_action(actor="CHATGPT", action="generate_supervisor_report", resource_type="technical_report", resource_id=report_id, summary=f"Supervisor report {report_id}", tool_used="generate_supervisor_report", metadata={"client_id": client_id, "site_id": site_id, "visit_id": visit_id})
    return {"ok": True, "report_id": report_id, "report_markdown": report_markdown, "summary_payload": summary_payload, "model_result": model_result}


try:
    _ensure_pcdoctor_indexes()
except Exception:
    # Keep module import resilient; index creation is best-effort and can be retried later.
    pass


