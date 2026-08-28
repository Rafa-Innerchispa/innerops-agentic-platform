"""PC Doctor operational store for clients, sites, assets, visits and quotes."""

from __future__ import annotations

import base64
import hashlib
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

CLIENT_SEARCH_FIELDS = ("client_id", "draft_id", "display_name", "legal_name", "trade_name", "tax_id", "phone", "email", "notes", "tags")
SITE_SEARCH_FIELDS = ("site_id", "draft_id", "client_id", "name", "address", "site_code", "access_notes", "security_notes", "tags")
ASSET_SEARCH_FIELDS = (
    "asset_id",
    "draft_id",
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
VISIT_SEARCH_FIELDS = ("visit_id", "draft_id", "client_id", "site_id", "visit_type", "summary", "findings", "recommendations", "next_steps", "tags")
QUOTE_SEARCH_FIELDS = ("quote_id", "client_id", "site_id", "visit_id", "title", "status", "notes", "option_key")

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
QUOTE_STATUS_ALIASES = {
    "review": "ready_for_review",
    "ready": "ready_for_review",
    "pending_review": "ready_for_review",
    "in_review": "ready_for_review",
}


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip().lower()


def _signature(*parts: Any) -> str:
    cleaned = [_normalize_key(part) for part in parts if _normalize_key(part)]
    return "::".join(cleaned)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in {".", "-", "-."}:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _normalize_quote_status(status: Any) -> str:
    raw = _normalize_key(status) or "draft"
    raw = QUOTE_STATUS_ALIASES.get(raw, raw)
    if raw not in ALLOWED_QUOTE_STATUS:
        return "draft"
    return raw


def _lookup_by_ids(collection: str, identifier: str, id_fields: tuple[str, ...]) -> dict[str, Any] | None:
    """Exact lookup by canonical id or draft_id before fuzzy search."""
    needle = _norm(identifier)
    if not needle:
        return None
    db = _db()
    for field in id_fields:
        doc = db[collection].find_one({field: needle})
        if doc:
            return _serialize(doc)
    return None


def _resolve_client_link(client_ref: str) -> dict[str, Any]:
    """Resolve client_ref → client_id usable as FK (draft_id allowed as provisional)."""
    ref = _norm(client_ref)
    if not ref:
        return {"ok": False, "client_id": "", "client_ref": "", "found": False, "is_draft": False}
    exact = _lookup_by_ids(COL_OPS_CLIENTS, ref, ("client_id", "draft_id"))
    if exact:
        client_id = _norm(exact.get("client_id")) or _norm(exact.get("draft_id"))
        return {
            "ok": True,
            "client_id": client_id,
            "client_ref": ref,
            "found": True,
            "is_draft": _norm(exact.get("status")) == "draft" or not _norm(exact.get("client_id")),
            "match": exact,
        }
    matches = resolve_client(ref).get("matches") or []
    if matches:
        best = matches[0]
        client_id = _norm(best.get("client_id")) or _norm(best.get("draft_id"))
        return {
            "ok": True,
            "client_id": client_id,
            "client_ref": ref,
            "found": True,
            "is_draft": _norm(best.get("status")) == "draft" or not _norm(best.get("client_id")),
            "match": best,
        }
    return {"ok": False, "client_id": "", "client_ref": ref, "found": False, "is_draft": False, "error": "client_not_found"}


def _resolve_site_link(site_ref: str) -> dict[str, Any]:
    ref = _norm(site_ref)
    if not ref:
        return {"ok": False, "site_id": "", "site_ref": "", "found": False, "is_draft": False}
    exact = _lookup_by_ids(COL_OPS_SITES, ref, ("site_id", "draft_id"))
    if exact:
        site_id = _norm(exact.get("site_id")) or _norm(exact.get("draft_id"))
        return {
            "ok": True,
            "site_id": site_id,
            "site_ref": ref,
            "client_id": _norm(exact.get("client_id")),
            "found": True,
            "is_draft": _norm(exact.get("status")) == "draft" or not _norm(exact.get("site_id")),
            "match": exact,
        }
    matches = resolve_site(ref).get("matches") or []
    if matches:
        best = matches[0]
        site_id = _norm(best.get("site_id")) or _norm(best.get("draft_id"))
        return {
            "ok": True,
            "site_id": site_id,
            "site_ref": ref,
            "client_id": _norm(best.get("client_id")),
            "found": True,
            "is_draft": _norm(best.get("status")) == "draft" or not _norm(best.get("site_id")),
            "match": best,
        }
    return {"ok": False, "site_id": "", "site_ref": ref, "found": False, "is_draft": False, "error": "site_not_found"}


def _resolve_visit_link(visit_ref: str) -> dict[str, Any]:
    ref = _norm(visit_ref)
    if not ref:
        return {"ok": False, "visit_id": "", "visit_ref": "", "found": False, "is_draft": False}
    exact = _lookup_by_ids(COL_OPS_FIELD_VISITS, ref, ("visit_id", "draft_id"))
    if exact:
        visit_id = _norm(exact.get("visit_id")) or _norm(exact.get("draft_id"))
        return {
            "ok": True,
            "visit_id": visit_id,
            "visit_ref": ref,
            "client_id": _norm(exact.get("client_id")),
            "site_id": _norm(exact.get("site_id")),
            "found": True,
            "is_draft": _norm(exact.get("status")) == "draft" or not _norm(exact.get("visit_id")),
            "match": exact,
        }
    matches = _search_many(COL_OPS_FIELD_VISITS, VISIT_SEARCH_FIELDS, ref, limit=5)
    if matches:
        best = matches[0]
        visit_id = _norm(best.get("visit_id")) or _norm(best.get("draft_id"))
        return {
            "ok": True,
            "visit_id": visit_id,
            "visit_ref": ref,
            "client_id": _norm(best.get("client_id")),
            "site_id": _norm(best.get("site_id")),
            "found": True,
            "is_draft": _norm(best.get("status")) == "draft" or not _norm(best.get("visit_id")),
            "match": best,
        }
    return {"ok": False, "visit_id": "", "visit_ref": ref, "found": False, "is_draft": False, "error": "visit_not_found"}


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
    summary = _normalize_key(_pull(doc, "summary", "source_note"))
    if client_id and site_id and visit_type and (scheduled_at or started_at):
        return f"client:{client_id}::site:{site_id}::type:{visit_type}::when:{scheduled_at or started_at}"
    if client_id and site_id and visit_type and summary:
        return f"client:{client_id}::site:{site_id}::type:{visit_type}::summary:{summary}"
    if client_id and site_id and visit_type:
        return f"client:{client_id}::site:{site_id}::type:{visit_type}"
    return ""


def _quote_dedupe_key(doc: dict[str, Any]) -> str:
    """Idempotencia por alternativa: visit+option_key (o title), no solo visit_id."""
    client_id = _norm(_pull(doc, "client_id", "client_ref"))
    site_id = _norm(_pull(doc, "site_id", "site_ref"))
    visit_id = _norm(_pull(doc, "visit_id", "visit_ref"))
    title = _normalize_key(_pull(doc, "title"))
    option_key = _normalize_key(
        _pull(doc, "option_key", "quote_option", "alternative_key", "version", "quote_type", "dedupe_key_override")
    )
    # Explicit override wins (caller-controlled idempotency)
    explicit = _normalize_key(_pull(doc, "dedupe_key"))
    if explicit and explicit.startswith("quote:"):
        return explicit
    if visit_id and option_key:
        return f"visit:{visit_id}::option:{option_key}"
    if visit_id and title:
        return f"visit:{visit_id}::title:{title}"
    if visit_id:
        # Sin option/title: no bloquear multi-cotización; clave débil por timestamp bucket no —
        # usa notes fingerprint o deja vacío para no dedupe forzado.
        notes = _normalize_key(_pull(doc, "notes", "source_note"))
        if notes:
            return f"visit:{visit_id}::notes:{notes[:80]}"
        return ""
    if client_id and site_id and title and option_key:
        return f"client:{client_id}::site:{site_id}::title:{title}::option:{option_key}"
    if client_id and site_id and title:
        return f"client:{client_id}::site:{site_id}::title:{title}"
    if client_id and title and option_key:
        return f"client:{client_id}::title:{title}::option:{option_key}"
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


def _find_reusable_by_dedupe(
    collection: str,
    dedupe_key: str,
    *,
    canonical_id_field: str = "",
) -> tuple[str, dict[str, Any]] | None:
    if not dedupe_key:
        return None
    db = _db()
    docs = list(db[collection].find({"dedupe_key": dedupe_key}).sort("updated_at", -1))
    for doc in docs:
        if _norm(doc.get("status")) not in NON_CANONICAL_STATUSES:
            return "canonical", _serialize(doc)
    for doc in docs:
        if _norm(doc.get("status")) == "draft":
            return "draft", _serialize(doc)
    if canonical_id_field:
        for doc in docs:
            if _norm(doc.get("status")) == "promoted":
                linked_id = _norm(doc.get(canonical_id_field)) or _norm(doc.get(f"promoted_to_{canonical_id_field}"))
                if linked_id:
                    canonical = db[collection].find_one(
                        {canonical_id_field: linked_id, "status": {"$nin": list(NON_CANONICAL_STATUSES)}}
                    )
                    if canonical:
                        return "canonical", _serialize(canonical)
    return None


def _unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    inner = payload.get("payload")
    if isinstance(inner, dict):
        merged = {**inner, **{k: v for k, v in payload.items() if k != "payload"}}
        return merged
    return payload


def _normalize_quote_payload(payload: dict[str, Any]) -> dict[str, Any]:
    p = _unwrap_payload(payload)
    if p.get("items") and not p.get("line_items"):
        p["line_items"] = p["items"]
    if p.get("subtotal") is not None and not p.get("line_items"):
        p.setdefault("line_items", [])
    if "tax_rate" in p:
        try:
            p["tax_rate"] = float(p["tax_rate"])
        except (TypeError, ValueError):
            p["tax_rate"] = 0.0
    return p


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


SECRET_FIELD_RE = re.compile(r"(password|passwd|secret|token|credential|api[_-]?key|wifi[_-]?key|wifi[_-]?pass|admin[_-]?pass)", re.I)


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str:
    target = Path(path)
    if not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact_secret_fields(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_FIELD_RE.search(str(key)) and not str(key).endswith(("_ref", "_refs")):
                clean[key] = "[REDACTED]"
            else:
                clean[key] = _redact_secret_fields(item)
        return clean
    if isinstance(value, list):
        return [_redact_secret_fields(item) for item in value]
    return value


def _event_dedupe_key(payload: dict[str, Any], event_type: str, *parts: Any) -> str:
    explicit = _norm(_pull(payload, "idempotency_key", "dedupe_key"))
    if explicit:
        return explicit
    raw = "|".join(_norm(part) for part in parts if _norm(part))
    return f"{event_type}:{_sha256_text(raw)[:24]}"


def _list_visit_events(query: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    capped = max(1, min(int(limit or 25), 100))
    cursor = _db()[COL_OPS_FIELD_VISIT_EVENTS].find(query).sort("created_at", -1).limit(capped)
    return [_serialize(doc) for doc in cursor]


def register_client_document(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    client_id = _norm(_pull(payload, "client_id", "client_ref"))
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}
    site_id = _norm(_pull(payload, "site_id", "site_ref"))
    visit_id = _norm(_pull(payload, "visit_id", "visit_ref"))
    asset_id = _norm(_pull(payload, "asset_id", "asset_ref"))
    source = _norm(_pull(payload, "source", default="chatgpt"))
    title = _norm(_pull(payload, "title", "name", "caption", default="client document"))
    document_type = _norm(_pull(payload, "document_type", "kind", default="document"))
    file_path = _norm(_pull(payload, "file_path", "path"))
    content_hash = _norm(_pull(payload, "hash_sha256", "sha256"))
    if not content_hash and file_path:
        content_hash = _sha256_file(file_path)
    if not content_hash:
        content_hash = _sha256_text({"title": title, "content": _pull(payload, "content", "body", default=""), "metadata": payload.get("metadata") or {}})
    dedupe_key = _event_dedupe_key(payload, "document_attachment", client_id, site_id, visit_id, asset_id, document_type, title, content_hash, source)
    existing = db[COL_OPS_FIELD_VISIT_EVENTS].find_one({"event_type": "document_attachment", "dedupe_key": dedupe_key})
    if existing:
        return {"ok": True, "created": False, "reused": True, "event_id": existing.get("event_id"), "document": _serialize(existing)}

    event_id = _new_id("doc")
    media = {
        "media_id": "",
        "media_uri": _norm(_pull(payload, "file_path", "path", "image_url")),
        "source": source,
        "mime_type": _norm(_pull(payload, "mime_type", default="application/octet-stream")),
        "caption": title,
        "ocr_text": _norm(_pull(payload, "ocr_text")),
        "created_at": now,
        "bytes": 0,
        "image_url": _norm(_pull(payload, "image_url")),
    } if payload.get("dry_run") else _write_media({**payload, "caption": title, "mime_type": _norm(_pull(payload, "mime_type", default="application/octet-stream"))})
    event = {
        "event_id": event_id,
        "document_id": _norm(_pull(payload, "document_id")) or event_id,
        "event_type": "document_attachment",
        "dedupe_key": dedupe_key,
        "source": source,
        "client_id": client_id,
        "site_id": site_id,
        "visit_id": visit_id,
        "asset_id": asset_id,
        "document_type": document_type,
        "title": title,
        "mime_type": media.get("mime_type"),
        "hash_sha256": content_hash,
        "media_id": media.get("media_id"),
        "media_uri": media.get("media_uri"),
        "caption": _norm(_pull(payload, "caption", "prompt")) or media.get("caption", ""),
        "field_verified": bool(payload.get("field_verified", False)),
        "captured_at": _norm(_pull(payload, "captured_at")) or now,
        "tags": payload.get("tags") or [],
        "metadata": _redact_secret_fields(payload.get("metadata") or {}),
        "created_at": now,
        "updated_at": now,
    }
    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "would_write": _serialize(event), "media": media}
    db[COL_OPS_FIELD_VISIT_EVENTS].insert_one(event)
    log_ops_action(
        actor="CHATGPT",
        action="register_client_document",
        resource_type="visit_event",
        resource_id=event_id,
        summary=f"Document registered for client {client_id}",
        tool_used="register_client_document",
        metadata={"client_id": client_id, "site_id": site_id, "visit_id": visit_id, "asset_id": asset_id, "document_type": document_type},
    )
    return {"ok": True, "created": True, "event_id": event_id, "media": media, "document": _serialize(event)}


def list_client_documents(client_id: str, site_id: str = "", visit_id: str = "", asset_id: str = "", limit: int = 50) -> dict[str, Any]:
    query: dict[str, Any] = {"event_type": {"$in": ["document_attachment", "media_attachment"]}, "client_id": _norm(client_id)}
    if not query["client_id"]:
        return {"ok": False, "error": "missing_client_id"}
    if _norm(site_id):
        query["site_id"] = _norm(site_id)
    if _norm(visit_id):
        query["visit_id"] = _norm(visit_id)
    if _norm(asset_id):
        query["asset_id"] = _norm(asset_id)
    items = _list_visit_events(query, limit)
    return {"ok": True, "count": len(items), "documents": items}


def record_site_network_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    client_id = _norm(_pull(payload, "client_id", "client_ref"))
    site_id = _norm(_pull(payload, "site_id", "site_ref"))
    if not site_id:
        return {"ok": False, "error": "missing_site_id"}
    source = _norm(_pull(payload, "source", default="chatgpt"))
    captured_at = _norm(_pull(payload, "captured_at")) or now
    snapshot_body = {
        "topology": _redact_secret_fields(payload.get("topology") or {}),
        "subnets": _redact_secret_fields(payload.get("subnets") or []),
        "vlans": _redact_secret_fields(payload.get("vlans") or []),
        "gateway": _redact_secret_fields(payload.get("gateway") or {}),
        "switches": _redact_secret_fields(payload.get("switches") or []),
        "aps": _redact_secret_fields(payload.get("aps") or []),
        "nvr": _redact_secret_fields(payload.get("nvr") or {}),
        "camera_count": payload.get("camera_count"),
        "channels": payload.get("channels") or [],
        "status": _norm(_pull(payload, "status", default="unverified")),
        "notes": _norm(_pull(payload, "notes", "summary")),
        "secret_refs": payload.get("secret_refs") or [],
    }
    dedupe_key = _event_dedupe_key(payload, "site_network_snapshot", client_id, site_id, source, captured_at[:10], snapshot_body)
    existing = db[COL_OPS_FIELD_VISIT_EVENTS].find_one({"event_type": "site_network_snapshot", "dedupe_key": dedupe_key})
    if existing:
        return {"ok": True, "created": False, "reused": True, "snapshot_id": existing.get("snapshot_id"), "snapshot": _serialize(existing)}
    event_id = _new_id("snapshot")
    event = {
        "event_id": event_id,
        "snapshot_id": _norm(_pull(payload, "snapshot_id")) or event_id,
        "event_type": "site_network_snapshot",
        "dedupe_key": dedupe_key,
        "source": source,
        "client_id": client_id,
        "site_id": site_id,
        "visit_id": _norm(_pull(payload, "visit_id", "visit_ref")),
        "asset_id": _norm(_pull(payload, "asset_id", "asset_ref")),
        "field_verified": bool(payload.get("field_verified", False)),
        "captured_at": captured_at,
        "tags": payload.get("tags") or [],
        "metadata": _redact_secret_fields(payload.get("metadata") or {}),
        **snapshot_body,
        "created_at": now,
        "updated_at": now,
    }
    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "would_write": _serialize(event)}
    db[COL_OPS_FIELD_VISIT_EVENTS].insert_one(event)
    log_ops_action(
        actor="CHATGPT",
        action="record_site_network_snapshot",
        resource_type="visit_event",
        resource_id=event_id,
        summary=f"Network snapshot for site {site_id}",
        tool_used="record_site_network_snapshot",
        metadata={"client_id": client_id, "site_id": site_id, "source": source, "field_verified": event["field_verified"]},
    )
    return {"ok": True, "created": True, "snapshot_id": event["snapshot_id"], "snapshot": _serialize(event)}


def list_site_network_snapshots(site_id: str, client_id: str = "", limit: int = 20) -> dict[str, Any]:
    query: dict[str, Any] = {"event_type": "site_network_snapshot", "site_id": _norm(site_id)}
    if not query["site_id"]:
        return {"ok": False, "error": "missing_site_id"}
    if _norm(client_id):
        query["client_id"] = _norm(client_id)
    items = _list_visit_events(query, limit)
    return {"ok": True, "count": len(items), "snapshots": items}


def build_client_360_snapshot(client_id: str, site_id: str = "") -> dict[str, Any]:
    client_id = _norm(client_id)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}
    client = _collection_find_one(COL_OPS_CLIENTS, {"client_id": client_id})
    sites_query: dict[str, Any] = {"client_id": client_id}
    if _norm(site_id):
        sites_query["site_id"] = _norm(site_id)
    sites = [_serialize(doc) for doc in _db()[COL_OPS_SITES].find(sites_query).sort("updated_at", -1).limit(25)]
    site_ids = [doc.get("site_id") for doc in sites if doc.get("site_id")]
    asset_query: dict[str, Any] = {"client_id": client_id}
    if site_ids:
        asset_query["site_id"] = {"$in": site_ids}
    assets = [_serialize(doc) for doc in _db()[COL_OPS_EQUIPMENT_ASSETS].find(asset_query).sort("updated_at", -1).limit(100)]
    docs = list_client_documents(client_id, site_id=_norm(site_id), limit=25)
    snapshots = []
    for sid in site_ids[:10]:
        snapshots.extend(list_site_network_snapshots(sid, client_id=client_id, limit=5).get("snapshots") or [])
    return {
        "ok": True,
        "client": client,
        "site_count": len(sites),
        "asset_count": len(assets),
        "document_count": docs.get("count", 0),
        "snapshot_count": len(snapshots),
        "sites": sites,
        "assets": assets[:25],
        "documents": docs.get("documents", [])[:10],
        "network_snapshots": snapshots[:10],
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
    reusable = _find_reusable_by_dedupe(COL_OPS_CLIENTS, dedupe_key, canonical_id_field="client_id")
    if reusable:
        reused_from, existing = reusable
        missing = _missing(existing, CLIENT_FIELDS)
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing.get("draft_id"),
            "client_draft": existing,
            "missing_fields": missing,
            "confidence": _confidence_from_missing(missing),
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
        db[COL_OPS_CLIENTS].update_one(
            {"draft_id": draft_id},
            {"$set": {"status": "promoted", "promoted_to_client_id": client_id, "updated_at": now}, "$unset": {"client_id": ""}},
        )
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
    link = _resolve_client_link(client_ref) if client_ref else {"client_id": "", "found": False, "is_draft": False}
    client_id = _norm(link.get("client_id"))
    preview = {
        "client_ref": client_ref,
        "client_id": client_id,
        "site_code": _norm(_pull(payload, "site_code")),
        "name": _norm(_pull(payload, "name", "site_name")),
        "address": _norm(_pull(payload, "address")),
    }
    dedupe_key = _site_dedupe_key({**preview, **payload})
    reusable = _find_reusable_by_dedupe(COL_OPS_SITES, dedupe_key, canonical_id_field="site_id")
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
        "client_link_is_draft": bool(link.get("is_draft")),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    missing = _missing(doc, SITE_FIELDS)
    if client_ref and not client_id:
        missing = list(dict.fromkeys([*missing, "client_id"]))
        doc["needs_review"] = True
        doc["review_reasons"] = ["client_ref_unresolved"]
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
        metadata={"client_ref": client_ref, "client_id": client_id, "missing_fields": missing, "confidence": doc["confidence"]},
    )
    return {
        "ok": True,
        "reused": False,
        "draft_id": draft_id,
        "site_draft": _serialize(doc),
        "missing_fields": missing,
        "confidence": doc["confidence"],
        "client_id": client_id,
        "needs_review": bool(doc.get("needs_review")),
    }


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
        db[COL_OPS_SITES].update_one(
            {"draft_id": draft_id},
            {"$set": {"status": "promoted", "promoted_to_site_id": site_id, "updated_at": now}, "$unset": {"site_id": ""}},
        )
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
    payload = _unwrap_payload(payload)
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
        "serial_number": _norm(_pull(payload, "serial_number", "serial")),
        "mac_address": _norm(_pull(payload, "mac_address")),
        "brand": _norm(_pull(payload, "brand")),
        "model": _norm(_pull(payload, "model")),
        "location_text": _norm(_pull(payload, "location_text")),
    }
    dedupe_key = _asset_dedupe_key({**preview, **payload})
    reusable = _find_reusable_by_dedupe(COL_OPS_EQUIPMENT_ASSETS, dedupe_key, canonical_id_field="asset_id")
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
        "draft_id": draft_id,
        **preview,
        "category": _norm(_pull(payload, "category")),
        "subtype": _norm(_pull(payload, "subtype")),
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
        "serial_digits": _norm_digits(_pull(payload, "serial_number", "serial")),
        "asset_tag_norm": _normalize_key(_pull(payload, "asset_tag")),
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
        db[COL_OPS_EQUIPMENT_ASSETS].update_one(
            {"draft_id": draft_id},
            {
                "$set": {"status": "promoted", "promoted_to_asset_id": asset_id, "updated_at": now},
                "$unset": {"asset_id": ""},
            },
        )
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
    draft_id = _new_id("visitdraft")
    client_ref = _norm(_pull(payload, "client_ref", "client_id"))
    site_ref = _norm(_pull(payload, "site_ref", "site_id"))
    client_link = _resolve_client_link(client_ref) if client_ref else {"client_id": "", "found": False, "is_draft": False}
    site_link = _resolve_site_link(site_ref) if site_ref else {"site_id": "", "found": False, "is_draft": False, "client_id": ""}
    client_id = _norm(client_link.get("client_id")) or _norm(site_link.get("client_id"))
    site_id = _norm(site_link.get("site_id"))
    visit_type = _norm(_pull(payload, "visit_type", default="inspection"))
    if visit_type not in ALLOWED_VISIT_TYPES:
        visit_type = "inspection"
    doc = {
        "draft_id": draft_id,
        "client_ref": client_ref,
        "client_id": client_id,
        "site_ref": site_ref,
        "site_id": site_id,
        "visit_type": visit_type,
        "status": "draft",
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
        "captured_by": _norm(_pull(payload, "captured_by", default="CHATGPT")),
        "dedupe_key": _visit_dedupe_key({**payload, "client_id": client_id, "site_id": site_id, "client_ref": client_ref, "site_ref": site_ref}),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    review_reasons: list[str] = []
    if client_ref and not client_id:
        review_reasons.append("client_ref_unresolved")
    if site_ref and not site_id:
        review_reasons.append("site_ref_unresolved")
    if review_reasons:
        doc["needs_review"] = True
        doc["review_reasons"] = review_reasons
    missing = _missing(doc, VISIT_FIELDS)
    doc["missing_fields"] = missing
    doc["confidence"] = _confidence_from_missing(missing)
    dedupe_key = _norm(doc.get("dedupe_key"))
    reusable = _find_reusable_by_dedupe(COL_OPS_FIELD_VISITS, dedupe_key, canonical_id_field="visit_id") if dedupe_key else None
    if reusable:
        reused_from, existing = reusable
        existing_serialized = existing
        missing = _missing(existing_serialized, VISIT_FIELDS)
        out: dict[str, Any] = {
            "ok": True,
            "reused": True,
            "reused_from": reused_from,
            "draft_id": existing_serialized.get("draft_id"),
            "visit_draft": existing_serialized,
            "missing_fields": missing,
            "confidence": _confidence_from_missing(missing),
            "client_id": _norm(existing_serialized.get("client_id")),
            "site_id": _norm(existing_serialized.get("site_id")),
        }
        if reused_from == "canonical":
            out["visit_id"] = existing_serialized.get("visit_id")
            out["visit"] = existing_serialized
        log_ops_action(
            actor="CHATGPT",
            action="create_visit_draft",
            resource_type="visit_draft",
            resource_id=_norm(existing_serialized.get("draft_id")) or _norm(existing_serialized.get("visit_id")) or draft_id,
            summary=f"Visit draft {visit_type}",
            tool_used="create_visit_draft",
            metadata={"client_ref": client_ref, "site_ref": site_ref, "reused": True, "reused_from": reused_from},
        )
        return out
    db[COL_OPS_FIELD_VISITS].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_visit_draft",
        resource_type="visit_draft",
        resource_id=draft_id,
        summary=f"Visit draft {visit_type}",
        tool_used="create_visit_draft",
        metadata={"client_ref": client_ref, "site_ref": site_ref, "client_id": client_id, "site_id": site_id, "missing_fields": missing, "confidence": doc["confidence"]},
    )
    return {
        "ok": True,
        "draft_id": draft_id,
        "visit_draft": _serialize(doc),
        "missing_fields": missing,
        "confidence": doc["confidence"],
        "client_id": client_id,
        "site_id": site_id,
        "needs_review": bool(doc.get("needs_review")),
    }


def log_service_visit(payload: dict[str, Any]) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    draft_id = _norm(_pull(payload, "visit_draft_id", "draft_id"))
    draft_doc = db[COL_OPS_FIELD_VISITS].find_one({"draft_id": draft_id}) if draft_id else None
    visit_id = _norm(_pull(payload, "visit_id")) or _norm((draft_doc or {}).get("visit_id")) or _new_id("visit")
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
        "draft_id": draft_id or _norm((draft_doc or {}).get("draft_id")),
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
    if draft_doc:
        created = False
        doc["created_at"] = draft_doc.get("created_at", now)
        db[COL_OPS_FIELD_VISITS].update_one({"_id": draft_doc["_id"]}, {"$set": doc}, upsert=False)
    else:
        existing = db[COL_OPS_FIELD_VISITS].find_one({"visit_id": visit_id})
        if existing:
            db[COL_OPS_FIELD_VISITS].update_one({"_id": existing["_id"]}, {"$set": doc})
            created = False
        else:
            doc["created_at"] = now
            db[COL_OPS_FIELD_VISITS].insert_one(doc)
            created = True
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


def resolve_site(identifier: str, limit: int = 10) -> dict[str, Any]:
    matches = _search_many(COL_OPS_SITES, SITE_SEARCH_FIELDS, identifier, limit=limit)
    return {"ok": True, "count": len(matches), "matches": matches, "best_match": matches[0] if matches else None}


def resolve_asset(identifier: str, limit: int = 10) -> dict[str, Any]:
    matches = _search_many(COL_OPS_EQUIPMENT_ASSETS, ASSET_SEARCH_FIELDS, identifier, limit=limit * 2)

    def _rank(doc: dict[str, Any]) -> int:
        st = _norm(doc.get("status"))
        if st in ("active", "inactive", "maintenance", "retired"):
            return 0
        if st == "promoted":
            return 2
        if st == "draft":
            return 3
        return 1

    matches.sort(key=_rank)
    matches = matches[:limit]
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
    payload = _normalize_quote_payload(payload)
    now = _now_iso()

    client_ref = _norm(_pull(payload, "client_id", "client_ref"))
    site_ref = _norm(_pull(payload, "site_id", "site_ref"))
    visit_ref = _norm(_pull(payload, "visit_id", "visit_ref"))
    option_key = _norm(_pull(payload, "option_key", "quote_option", "alternative_key", "version", "quote_type"))

    client_link = _resolve_client_link(client_ref) if client_ref else {"client_id": "", "found": False}
    site_link = _resolve_site_link(site_ref) if site_ref else {"site_id": "", "found": False, "client_id": ""}
    visit_link = _resolve_visit_link(visit_ref) if visit_ref else {"visit_id": "", "found": False, "client_id": "", "site_id": ""}

    client_id = _norm(client_link.get("client_id")) or _norm(visit_link.get("client_id")) or _norm(site_link.get("client_id"))
    site_id = _norm(site_link.get("site_id")) or _norm(visit_link.get("site_id"))
    visit_id = _norm(visit_link.get("visit_id"))

    review_reasons: list[str] = []
    if client_ref and not client_link.get("found"):
        review_reasons.append("client_not_found")
    if site_ref and not site_link.get("found"):
        review_reasons.append("site_not_found")
    if visit_ref and not visit_link.get("found"):
        review_reasons.append("visit_not_found")
    if not client_id and not site_id and not visit_id:
        return {
            "ok": False,
            "error": "missing_references",
            "detail": "create_quote_draft requiere client_id/site_id/visit_id válidos (canónicos o draft_id).",
            "review_reasons": review_reasons or ["no_refs"],
        }

    enriched = {
        **payload,
        "client_id": client_id,
        "site_id": site_id,
        "visit_id": visit_id,
        "option_key": option_key,
    }
    dedupe_key = _quote_dedupe_key(enriched)
    if dedupe_key:
        reusable = _find_reusable_by_dedupe(COL_OPS_QUOTE_DRAFTS, dedupe_key, canonical_id_field="quote_id")
        if reusable:
            reused_from, existing = reusable
            return {
                "ok": True,
                "reused": True,
                "reused_from": reused_from,
                "quote_id": existing.get("quote_id"),
                "quote_draft": existing,
                "option_key": existing.get("option_key") or option_key,
            }

    quote_id = _new_id("quotedraft")
    line_items = payload.get("line_items") or []
    normalized_items: list[dict[str, Any]] = []
    subtotal = 0.0
    for item in line_items:
        if not isinstance(item, dict):
            continue
        qty = _safe_float(item.get("quantity", 1), 1.0)
        price = _safe_float(item.get("unit_price", item.get("price", 0)), 0.0)
        normalized_items.append({**item, "quantity": qty, "unit_price": price})
        subtotal += qty * price
    if not normalized_items and payload.get("subtotal") is not None:
        subtotal = _safe_float(payload.get("subtotal"), 0.0)
    tax_rate = _safe_float(payload.get("tax_rate", 0.0), 0.0)
    tax = round(subtotal * tax_rate, 2)
    total = round(_safe_float(payload.get("total"), 0.0) or (subtotal + tax), 2)
    status = _normalize_quote_status(_pull(payload, "status", default="draft"))
    if review_reasons:
        status = "draft"

    doc = {
        "quote_id": quote_id,
        "client_id": client_id,
        "site_id": site_id,
        "visit_id": visit_id,
        "client_ref": client_ref,
        "site_ref": site_ref,
        "visit_ref": visit_ref,
        "option_key": option_key,
        "title": _norm(_pull(payload, "title", default="PC Doctor Quote Draft")),
        "status": status,
        "currency": _norm(_pull(payload, "currency", default="USD")),
        "line_items": normalized_items,
        "subtotal": round(subtotal, 2),
        "tax_rate": tax_rate,
        "tax": tax,
        "total": total,
        "billing_ready": bool(payload.get("billing_ready", False)),
        "notes": _norm(_pull(payload, "notes", "source_note")),
        "intro_md": _norm(_pull(payload, "intro_md", "scope_summary")),
        "scope_summary": _norm(_pull(payload, "scope_summary")),
        "display_number": _norm(_pull(payload, "display_number", "quote_number")),
        "entity_id": _norm(_pull(payload, "entity_id", default="ent_pcdoctor")),
        "valid_until": _norm(_pull(payload, "valid_until")),
        "client_phone": _norm(_pull(payload, "client_phone", "phone")),
        "client_email": _norm(_pull(payload, "client_email", "email")),
        "approved_by": _norm(_pull(payload, "approved_by")),
        "created_by": _norm(_pull(payload, "created_by", default="CHATGPT")),
        "source": _norm(_pull(payload, "source", default="chatgpt_mcp")),
        "dedupe_key": dedupe_key,
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "created_at": now,
        "updated_at": now,
    }
    db[COL_OPS_QUOTE_DRAFTS].insert_one(doc)
    log_ops_action(
        actor="CHATGPT",
        action="create_quote_draft",
        resource_type="quote_draft",
        resource_id=quote_id,
        summary=f"Quote draft {doc['title']}",
        tool_used="create_quote_draft",
        metadata={
            "client_id": doc["client_id"],
            "site_id": doc["site_id"],
            "visit_id": doc["visit_id"],
            "option_key": option_key,
            "needs_review": bool(review_reasons),
            "review_reasons": review_reasons,
        },
    )
    return {
        "ok": True,
        "reused": False,
        "quote_id": quote_id,
        "quote_draft": _serialize(doc),
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "option_key": option_key,
    }


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
    if "status" in patch:
        patch["status"] = _normalize_quote_status(patch["status"])
    if "line_items" in patch:
        normalized_items: list[dict[str, Any]] = []
        subtotal = 0.0
        for item in patch.get("line_items") or []:
            if not isinstance(item, dict):
                continue
            qty = _safe_float(item.get("quantity", 1), 1.0)
            price = _safe_float(item.get("unit_price", item.get("price", 0)), 0.0)
            normalized_items.append({**item, "quantity": qty, "unit_price": price})
            subtotal += qty * price
        patch["line_items"] = normalized_items
        patch["subtotal"] = round(subtotal, 2)
        patch["tax"] = round(subtotal * _safe_float(patch.get("tax_rate", doc.get("tax_rate", 0.0)), 0.0), 2)
        patch["total"] = round(patch["subtotal"] + patch["tax"], 2)
    merged = {**doc, **patch}
    patch["dedupe_key"] = _quote_dedupe_key(merged)
    if _norm(patch.get("option_key")) == "" and _norm(merged.get("option_key")):
        patch["option_key"] = merged.get("option_key")
    patch["updated_at"] = now
    db[COL_OPS_QUOTE_DRAFTS].update_one({"_id": doc["_id"]}, {"$set": patch})
    updated = db[COL_OPS_QUOTE_DRAFTS].find_one({"_id": doc["_id"]})
    log_ops_action(
        actor="CHATGPT",
        action="update_quote_draft",
        resource_type="quote_draft",
        resource_id=quote_id,
        summary=f"Quote draft updated {quote_id}",
        tool_used="update_quote_draft",
        metadata={"status": patch.get("status", doc.get("status"))},
    )
    return {"ok": True, "quote_draft": _serialize(updated)}


def generate_supervisor_report(client_id: str, site_id: str | None = None, visit_id: str | None = None) -> dict[str, Any]:
    db = _db()
    client_link = _resolve_client_link(client_id) if client_id else {"found": False, "client_id": ""}
    resolved_client_id = _norm(client_link.get("client_id")) or _norm(client_id)
    client = None
    if client_link.get("match"):
        client = client_link["match"]
    elif resolved_client_id:
        client = db[COL_OPS_CLIENTS].find_one({"$or": [{"client_id": resolved_client_id}, {"draft_id": resolved_client_id}]})
        client = _serialize(client) if client else None

    if not resolved_client_id or not client:
        return {
            "ok": False,
            "error": "client_required",
            "detail": "generate_supervisor_report requiere un client_id existente (canónico o draft).",
            "client_id": client_id,
            "site_id": site_id,
            "visit_id": visit_id,
        }

    site = None
    resolved_site_id = _norm(site_id)
    if resolved_site_id:
        site_link = _resolve_site_link(resolved_site_id)
        if not site_link.get("found"):
            return {
                "ok": False,
                "error": "site_not_found",
                "detail": f"site_id no encontrado: {resolved_site_id}",
                "client_id": resolved_client_id,
                "site_id": resolved_site_id,
            }
        resolved_site_id = _norm(site_link.get("site_id"))
        site = site_link.get("match")

    visit = None
    resolved_visit_id = _norm(visit_id)
    if resolved_visit_id:
        visit_link = _resolve_visit_link(resolved_visit_id)
        if not visit_link.get("found"):
            return {
                "ok": False,
                "error": "visit_not_found",
                "detail": f"visit_id no encontrado: {resolved_visit_id}",
                "client_id": resolved_client_id,
                "visit_id": resolved_visit_id,
            }
        resolved_visit_id = _norm(visit_link.get("visit_id"))
        visit = visit_link.get("match")

    assets_query: dict[str, Any] = {"client_id": resolved_client_id}
    if resolved_site_id:
        assets_query["site_id"] = resolved_site_id
    assets = [_serialize(doc) for doc in db[COL_OPS_EQUIPMENT_ASSETS].find(assets_query).sort("updated_at", -1).limit(50)]
    observations_query: dict[str, Any] = {"client_id": resolved_client_id}
    if resolved_site_id:
        observations_query["site_id"] = resolved_site_id
    if resolved_visit_id:
        observations_query["visit_id"] = resolved_visit_id
    observations = [_serialize(doc) for doc in db[COL_OPS_FIELD_VISIT_EVENTS].find(observations_query).sort("created_at", -1).limit(100)]
    quotes_query: dict[str, Any] = {"client_id": resolved_client_id}
    if resolved_site_id:
        quotes_query["site_id"] = resolved_site_id
    if resolved_visit_id:
        quotes_query["visit_id"] = resolved_visit_id
    quotes = [_serialize(doc) for doc in db[COL_OPS_QUOTE_DRAFTS].find(quotes_query).sort("updated_at", -1).limit(20)]
    summary_payload = {
        "client": _serialize(client),
        "site": _serialize(site),
        "visit": _serialize(visit),
        "assets": assets[:20],
        "observations": observations[:30],
        "quotes": quotes[:10],
    }
    prompt = json.dumps(summary_payload, ensure_ascii=False, indent=2)
    model_result = local_model_router.run_local_model(task_type="technical_report", prompt=prompt, max_tokens=700, temperature=0.2)
    if model_result.get("ok"):
        report_markdown = model_result.get("response", "")
    else:
        lines = [
            f"# Supervisor Report - {_norm((client or {}).get('display_name') or resolved_client_id)}",
            "",
            f"- Client ID: {resolved_client_id}",
            f"- Site ID: {resolved_site_id or 'n/a'}",
            f"- Visit ID: {resolved_visit_id or 'n/a'}",
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
    report_doc = {
        "report_id": report_id,
        "client_id": resolved_client_id,
        "site_id": resolved_site_id or None,
        "visit_id": resolved_visit_id or None,
        "report_markdown": report_markdown,
        "source": "chatgpt_mcp",
        "model_result": model_result,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    db[COL_OPS_TECHNICAL_REPORTS].insert_one(report_doc)
    log_ops_action(
        actor="CHATGPT",
        action="generate_supervisor_report",
        resource_type="technical_report",
        resource_id=report_id,
        summary=f"Supervisor report {report_id}",
        tool_used="generate_supervisor_report",
        metadata={"client_id": resolved_client_id, "site_id": resolved_site_id, "visit_id": resolved_visit_id},
    )
    return {
        "ok": True,
        "report_id": report_id,
        "report_markdown": report_markdown,
        "summary_payload": summary_payload,
        "model_result": model_result,
    }


try:
    _ensure_pcdoctor_indexes()
except Exception:
    # Keep module import resilient; index creation is best-effort and can be retried later.
    pass
