"""CRM kernel — party identity (party_id) across clients, suppliers and ops."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import (
    COL_CRM_IDENTITY_MAP,
    COL_CRM_PARTIES,
    COL_OPS_CLIENTS,
)

COL_LEGACY_CLIENTS = "clients"
COL_SUPPLIERS = "suppliers"
COL_QUOTE_CLIENTS = "quote_clients"

ALLOWED_PARTY_ROLES = {"client", "supplier", "prospect", "partner", "contact_org"}
SOURCE_COLLECTIONS = (
    COL_CRM_PARTIES,
    COL_LEGACY_CLIENTS,
    COL_OPS_CLIENTS,
    COL_SUPPLIERS,
    COL_QUOTE_CLIENTS,
    "contifico_personas",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _norm(value)).strip().lower()


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


def _new_party_id() -> str:
    return f"party_{ObjectId()}"


def _party_dedupe_key(doc: dict[str, Any]) -> str:
    tax_id = _norm(_pull(doc, "tax_id", "ruc", "id_number"))
    phone_digits = _norm_digits(_pull(doc, "phone", "whatsapp", "contact_phone"))
    email = _normalize_key(_pull(doc, "email", "contact_email"))
    display_name = _normalize_key(_pull(doc, "display_name", "legal_name", "trade_name", "name", "client_name", "nombre"))
    if tax_id:
        return f"tax_id:{tax_id}"
    if phone_digits:
        return f"phone:{phone_digits}"
    if email:
        return f"email:{email}"
    if display_name:
        return f"name:{display_name}"
    return ""


def _ensure_party_indexes() -> None:
    db = _db()
    specs = [
        (COL_CRM_PARTIES, [("party_id", 1)], {"name": "ux_crm_parties_party_id", "unique": True}),
        (COL_CRM_PARTIES, [("tax_id", 1)], {"name": "ux_crm_parties_tax_id", "unique": True, "sparse": True, "partialFilterExpression": {"tax_id": {"$type": "string", "$ne": ""}}}),
        (COL_CRM_PARTIES, [("dedupe_key", 1)], {"name": "ux_crm_parties_dedupe_key", "unique": True, "sparse": True, "partialFilterExpression": {"dedupe_key": {"$type": "string", "$ne": ""}}}),
        (COL_CRM_IDENTITY_MAP, [("party_id", 1), ("source_collection", 1), ("source_id", 1)], {"name": "ux_crm_identity_party_source", "unique": True}),
        (COL_CRM_IDENTITY_MAP, [("source_collection", 1), ("source_id", 1)], {"name": "ux_crm_identity_source", "unique": True}),
    ]
    for collection, keys, kwargs in specs:
        try:
            db[collection].create_index(keys, **kwargs)
        except Exception:
            continue


def _lookup_party_id(source_collection: str, source_id: str) -> str:
    if not source_id:
        return ""
    row = _db()[COL_CRM_IDENTITY_MAP].find_one({"source_collection": source_collection, "source_id": source_id})
    return _norm(row.get("party_id")) if row else ""


def _identity_links_for_party(party_id: str) -> list[dict[str, Any]]:
    if not party_id:
        return []
    rows = _db()[COL_CRM_IDENTITY_MAP].find({"party_id": party_id}).sort("linked_at", -1)
    return [_serialize(row) for row in rows]


def _source_id_from_doc(collection: str, doc: dict[str, Any]) -> str:
    if collection == COL_LEGACY_CLIENTS:
        return _norm(doc.get("client_id")) or str(doc.get("_id", ""))
    if collection == COL_OPS_CLIENTS:
        return _norm(doc.get("client_id") or doc.get("draft_id"))
    if collection == COL_SUPPLIERS:
        return _norm(doc.get("supplier_id")) or str(doc.get("_id", ""))
    if collection == COL_QUOTE_CLIENTS:
        return _norm(doc.get("client_id")) or str(doc.get("_id", ""))
    if collection == COL_CRM_PARTIES:
        return _norm(doc.get("party_id"))
    if collection == "contifico_personas":
        return _norm(doc.get("persona_id"))
    return str(doc.get("_id", ""))


def _normalize_source_match(collection: str, doc: dict[str, Any]) -> dict[str, Any]:
    source_id = _source_id_from_doc(collection, doc)
    party_id = _lookup_party_id(collection, source_id) or _norm(doc.get("party_id"))
    if collection == COL_LEGACY_CLIENTS:
        base = {
            "display_name": _norm(doc.get("name")),
            "legal_name": _norm(doc.get("name")),
            "tax_id": _norm(doc.get("ruc")),
            "email": _norm(doc.get("email")),
            "phone": _norm(doc.get("phone")),
            "city": _norm(doc.get("city")),
            "address": _norm(doc.get("address")),
            "roles": ["client"],
        }
    elif collection == COL_OPS_CLIENTS:
        base = {
            "display_name": _norm(doc.get("display_name") or doc.get("legal_name")),
            "legal_name": _norm(doc.get("legal_name")),
            "tax_id": _norm(doc.get("tax_id")),
            "email": _norm(doc.get("email")),
            "phone": _norm(doc.get("phone")),
            "city": _norm(doc.get("city")),
            "address": _norm(doc.get("address")),
            "roles": ["client"],
            "status": _norm(doc.get("status")),
        }
    elif collection == COL_SUPPLIERS:
        base = {
            "display_name": _norm(doc.get("nombre")),
            "legal_name": _norm(doc.get("nombre")),
            "tax_id": _norm(doc.get("ruc")),
            "email": _norm(doc.get("email")),
            "phone": _norm(doc.get("phone")),
            "city": _norm(doc.get("ciudad")),
            "roles": ["supplier"],
        }
    elif collection == COL_QUOTE_CLIENTS:
        base = {
            "display_name": _norm(doc.get("client_name")),
            "legal_name": _norm(doc.get("client_name")),
            "tax_id": "",
            "email": _norm((doc.get("contact") or {}).get("email") if isinstance(doc.get("contact"), dict) else ""),
            "phone": _norm((doc.get("contact") or {}).get("phone") if isinstance(doc.get("contact"), dict) else ""),
            "roles": ["client"],
            "entity_ids": [_norm(doc.get("entity_id"))] if doc.get("entity_id") else [],
        }
    else:
        base = {
            "display_name": _norm(doc.get("display_name")),
            "legal_name": _norm(doc.get("legal_name")),
            "tax_id": _norm(doc.get("tax_id")),
            "email": _norm(doc.get("email")),
            "phone": _norm(doc.get("phone")),
            "roles": doc.get("roles") or [],
            "entity_ids": doc.get("entity_ids") or [],
        }
    base.update(
        {
            "party_id": party_id,
            "_source": collection,
            "_source_id": source_id,
            "_linked": bool(party_id),
        }
    )
    return base


def _search_collection(collection: str, fields: tuple[str, ...], identifier: str, limit: int) -> list[dict[str, Any]]:
    db = _db()
    raw = _norm(identifier)
    if not raw:
        return []
    or_filters = [{field: {"$regex": re.escape(raw), "$options": "i"}} for field in fields]
    digits = _norm_digits(raw)
    if digits:
        for field in ("phone", "phone_digits", "tax_id", "ruc", "whatsapp"):
            or_filters.append({field: {"$regex": re.escape(digits), "$options": "i"}})
    cursor = db[collection].find({"$or": or_filters}).limit(max(1, min(limit, 50)))
    return [_normalize_source_match(collection, doc) for doc in cursor]


def _merge_party_matches(matches: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    by_party: dict[str, dict[str, Any]] = {}
    by_sig: dict[str, dict[str, Any]] = {}
    merged: list[dict[str, Any]] = []
    for match in matches:
        party_id = _norm(match.get("party_id"))
        sig = _party_dedupe_key(match) or f"{match.get('_source')}:{match.get('_source_id')}"
        if party_id:
            if party_id not in by_party:
                entry = dict(match)
                entry["sources"] = [{match.get("_source"): match.get("_source_id")}]
                by_party[party_id] = entry
                merged.append(entry)
            else:
                by_party[party_id]["sources"].append({match.get("_source"): match.get("_source_id")})
            continue
        if sig in by_sig:
            by_sig[sig]["sources"].append({match.get("_source"): match.get("_source_id")})
            roles = set(by_sig[sig].get("roles") or [])
            roles.update(match.get("roles") or [])
            by_sig[sig]["roles"] = sorted(roles)
            continue
        entry = dict(match)
        entry["sources"] = [{match.get("_source"): match.get("_source_id")}]
        by_sig[sig] = entry
        merged.append(entry)
        if len(merged) >= limit:
            break
    return merged[:limit]


def resolve_party(identifier: str, limit: int = 10, roles: list[str] | None = None) -> dict[str, Any]:
    """Busca identidad unificada en crm_parties y colecciones legacy/ops."""
    db = _db()
    raw = _norm(identifier)
    matches: list[dict[str, Any]] = []
    if raw:
        party_fields = ("party_id", "display_name", "legal_name", "trade_name", "tax_id", "email", "phone", "aliases")
        for doc in db[COL_CRM_PARTIES].find(
            {"$or": [{f: {"$regex": re.escape(raw), "$options": "i"}} for f in party_fields]}
        ).limit(limit):
            matches.append(_normalize_source_match(COL_CRM_PARTIES, doc))
        matches.extend(_search_collection(COL_LEGACY_CLIENTS, ("client_id", "name", "ruc", "email", "city"), raw, limit))
        matches.extend(_search_collection(COL_OPS_CLIENTS, ("client_id", "draft_id", "display_name", "tax_id", "email", "phone"), raw, limit))
        matches.extend(_search_collection(COL_SUPPLIERS, ("supplier_id", "nombre", "ruc", "email", "phone"), raw, limit))
        matches.extend(_search_collection(COL_QUOTE_CLIENTS, ("client_id", "client_name"), raw, limit))
    merged = _merge_party_matches(matches, limit=limit)
    if roles:
        role_set = {r.strip().lower() for r in roles if r}
        merged = [m for m in merged if role_set.intersection({r.lower() for r in (m.get("roles") or [])})]
    for match in merged:
        pid = _norm(match.get("party_id"))
        if pid:
            match["identity_links"] = _identity_links_for_party(pid)
    sources = sorted({m.get("_source") for m in merged if m.get("_source")})
    return {
        "ok": True,
        "count": len(merged),
        "matches": merged,
        "best_match": merged[0] if merged else None,
        "sources": sources,
        "kernel": "crm_parties",
    }


def _upsert_identity_link(party_id: str, source_collection: str, source_id: str, role: str | None = None) -> None:
    if not party_id or not source_collection or not source_id:
        return
    now = _now_iso()
    _db()[COL_CRM_IDENTITY_MAP].update_one(
        {"source_collection": source_collection, "source_id": source_id},
        {
            "$set": {
                "party_id": party_id,
                "source_collection": source_collection,
                "source_id": source_id,
                "role": _norm(role),
                "linked_at": now,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def _auto_discover_links(party: dict[str, Any]) -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    tax_id = _norm(party.get("tax_id"))
    display_name = _norm(party.get("display_name"))
    if tax_id:
        for doc in _db()[COL_LEGACY_CLIENTS].find({"ruc": tax_id}).limit(5):
            discovered.append({"source_collection": COL_LEGACY_CLIENTS, "source_id": _source_id_from_doc(COL_LEGACY_CLIENTS, doc), "role": "client"})
        for doc in _db()[COL_OPS_CLIENTS].find({"tax_id": tax_id, "status": {"$ne": "draft"}}).limit(5):
            discovered.append({"source_collection": COL_OPS_CLIENTS, "source_id": _source_id_from_doc(COL_OPS_CLIENTS, doc), "role": "client"})
        for doc in _db()[COL_SUPPLIERS].find({"ruc": tax_id}).limit(5):
            discovered.append({"source_collection": COL_SUPPLIERS, "source_id": _source_id_from_doc(COL_SUPPLIERS, doc), "role": "supplier"})
    elif display_name:
        for doc in _db()[COL_LEGACY_CLIENTS].find({"name": {"$regex": re.escape(display_name), "$options": "i"}}).limit(3):
            discovered.append({"source_collection": COL_LEGACY_CLIENTS, "source_id": _source_id_from_doc(COL_LEGACY_CLIENTS, doc), "role": "client"})
    return discovered


def upsert_party(payload: dict[str, Any]) -> dict[str, Any]:
    """Crea o actualiza party canónico y enlaces identity_map."""
    db = _db()
    now = _now_iso()
    party_id = _norm(_pull(payload, "party_id"))
    tax_id = _norm(_pull(payload, "tax_id", "ruc"))
    display_name = _norm(_pull(payload, "display_name", "legal_name", "name", "nombre", "client_name"))
    roles = payload.get("roles") or []
    roles = [r for r in roles if _norm(r).lower() in ALLOWED_PARTY_ROLES] or ["client"]
    entity_ids = payload.get("entity_ids") or []
    existing = db[COL_CRM_PARTIES].find_one({"party_id": party_id}) if party_id else None
    if not existing and tax_id:
        existing = db[COL_CRM_PARTIES].find_one({"tax_id": tax_id})
    if not existing:
        dedupe_key = _party_dedupe_key(payload)
        if dedupe_key:
            existing = db[COL_CRM_PARTIES].find_one({"dedupe_key": dedupe_key})
    if not party_id and existing:
        party_id = _norm(existing.get("party_id"))
    if not party_id:
        party_id = _new_party_id()
    doc = {
        "party_id": party_id,
        "display_name": display_name or _norm((existing or {}).get("display_name")),
        "legal_name": _norm(_pull(payload, "legal_name", "display_name", "name")) or _norm((existing or {}).get("legal_name")),
        "trade_name": _norm(_pull(payload, "trade_name")) or _norm((existing or {}).get("trade_name")),
        "tax_id": tax_id or _norm((existing or {}).get("tax_id")),
        "phone": _norm(_pull(payload, "phone", "whatsapp")) or _norm((existing or {}).get("phone")),
        "phone_digits": _norm_digits(_pull(payload, "phone", "whatsapp")) or _norm((existing or {}).get("phone_digits")),
        "email": _norm(_pull(payload, "email")) or _norm((existing or {}).get("email")),
        "city": _norm(_pull(payload, "city", "ciudad")) or _norm((existing or {}).get("city")),
        "address": _norm(_pull(payload, "address")) or _norm((existing or {}).get("address")),
        "roles": sorted(set((existing or {}).get("roles") or []) | set(roles)),
        "entity_ids": sorted(set((existing or {}).get("entity_ids") or []) | set(entity_ids)),
        "aliases": sorted(set((existing or {}).get("aliases") or []) | set(payload.get("aliases") or [])),
        "notes": _norm(_pull(payload, "notes")) or _norm((existing or {}).get("notes")),
        "status": _norm(_pull(payload, "status", default=(existing or {}).get("status") or "active")),
        "dedupe_key": _party_dedupe_key({**dict(existing or {}), **payload}),
        "updated_at": now,
    }
    created = False
    if not existing:
        doc["created_at"] = now
        db[COL_CRM_PARTIES].insert_one(doc)
        created = True
    else:
        db[COL_CRM_PARTIES].update_one({"party_id": party_id}, {"$set": doc})
    links = payload.get("identity_links") or payload.get("links") or []
    for link in links:
        _upsert_identity_link(
            party_id,
            _norm(link.get("source_collection") or link.get("collection")),
            _norm(link.get("source_id") or link.get("id")),
            _norm(link.get("role")),
        )
    if payload.get("auto_link", True):
        seen = {(l.get("source_collection"), l.get("source_id")) for l in links}
        for auto in _auto_discover_links(doc):
            key = (auto["source_collection"], auto["source_id"])
            if key not in seen:
                _upsert_identity_link(party_id, auto["source_collection"], auto["source_id"], auto.get("role"))
    saved = _serialize(db[COL_CRM_PARTIES].find_one({"party_id": party_id}))
    saved["identity_links"] = _identity_links_for_party(party_id)
    log_ops_action(
        actor="CHATGPT",
        action="upsert_party",
        resource_type="party",
        resource_id=party_id,
        summary=f"Party {saved.get('display_name') or party_id}",
        tool_used="upsert_party",
        metadata={"created": created, "roles": saved.get("roles"), "links": len(saved.get("identity_links") or [])},
    )
    return {"ok": True, "created": created, "party_id": party_id, "party": saved}


try:
    _ensure_party_indexes()
except Exception:
    pass
