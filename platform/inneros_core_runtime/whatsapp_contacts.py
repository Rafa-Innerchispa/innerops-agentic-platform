"""Importación y normalización de contactos Google → Mongo operativo."""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.constants import COL_OPS_CONTACTS, COL_OPS_WHATSAPP_GROUPS

CONTACTS_COL = "contacts"
DEFAULT_ENTITY_IDS = ["ent_rafael_personal", "ent_pcdoctor"]

# Contactos importados del chip Innerchispa (Evolution) — NO son conocidos personales de Rafael.
SOURCE_EVOLUTION_INNERCHISPA = "evolution_innerchispa"
CHIP_IMPORT_LABELS = [
    "innerchispa",
    "whatsapp_evolution",
    "marketing_pool",
    "chip_import",
    "not_personal",
]
CHIP_IMPORT_PROVENANCE = {
    "known_to_owner": False,
    "relationship": "unknown",
    "contact_class": "chip_import",
    "trust_level": "cold",
    "privacy_scope": "MARKETING_COLD",
    "origin_note": (
        "Importado del chip/número Innerchispa recién agregado. "
        "Era usado por otra persona para trabajo; NO son contactos personales de Rafael."
    ),
    "source_instance": "Innerchispa",
    "chip_number_role": "innerchispa_work_line",
}

ENTITY_RULES: list[tuple[str, str]] = [
    ("pc doctor", "ent_pcdoctor"),
    ("inner chispa", "ent_innerchispa"),
    ("innerspark", "ent_innerspark"),
    ("inner spark", "ent_innerspark"),
    ("iskcon", "ent_iskcon"),
    ("domot", "ent_domotika"),
    ("creator os", "ent_creatoros"),
    ("ralfia", "ent_ralfia"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str | None) -> str:
    return (text or "").strip()


def _digits(text: str | None) -> str:
    return "".join(c for c in (text or "") if c.isdigit())


def _contact_hash(parts: list[str]) -> str:
    payload = "|".join(_norm(p).lower() for p in parts if _norm(p))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    items = re.split(r"[;,]", value)
    return [item.strip() for item in items if item.strip()]


def _entity_for_row(row: dict[str, str]) -> tuple[str | None, str | None]:
    blob = " ".join(
        _norm(row.get(key))
        for key in (
            "Organization Name",
            "Notes",
            "Labels",
            "File As",
            "First Name",
            "Last Name",
        )
    ).lower()
    for needle, entity_id in ENTITY_RULES:
        if needle in blob:
            return entity_id, needle
    return None, None


def _collect_entity_ids(
    *,
    base_entity_ids: list[str] | None = None,
    row_entity_id: str | None = None,
    explicit_entity_id: str | None = None,
) -> list[str]:
    result: list[str] = []
    for value in (base_entity_ids or DEFAULT_ENTITY_IDS) + [row_entity_id, explicit_entity_id]:
        if not value:
            continue
        if value not in result:
            result.append(value)
    return result


def _contact_doc(
    row: dict[str, str],
    row_num: int,
    source_file: str,
    entity_ids: list[str],
) -> dict[str, Any]:
    first = _norm(row.get("First Name"))
    middle = _norm(row.get("Middle Name"))
    last = _norm(row.get("Last Name"))
    file_as = _norm(row.get("File As"))
    name = file_as or " ".join(p for p in [first, middle, last] if p).strip()
    org = _norm(row.get("Organization Name"))
    phones = [
        {
            "label": _norm(row.get("Phone 1 - Label")),
            "value": _norm(row.get("Phone 1 - Value")),
            "digits": _digits(row.get("Phone 1 - Value")),
        },
        {
            "label": _norm(row.get("Phone 2 - Label")),
            "value": _norm(row.get("Phone 2 - Value")),
            "digits": _digits(row.get("Phone 2 - Value")),
        },
        {
            "label": _norm(row.get("Phone 3 - Label")),
            "value": _norm(row.get("Phone 3 - Value")),
            "digits": _digits(row.get("Phone 3 - Value")),
        },
    ]
    phones = [p for p in phones if p["value"]]
    emails = [
        {
            "label": _norm(row.get("E-mail 1 - Label")),
            "value": _norm(row.get("E-mail 1 - Value")),
        },
        {
            "label": _norm(row.get("E-mail 2 - Label")),
            "value": _norm(row.get("E-mail 2 - Value")),
        },
    ]
    emails = [e for e in emails if e["value"]]
    labels = _split_list(row.get("Labels"))
    notes = _norm(row.get("Notes"))
    whatsapp = phones[0]["value"] if phones else ""
    whatsapp_digits = phones[0]["digits"] if phones else ""
    contact_id = _contact_hash([
        name,
        org,
        whatsapp_digits or whatsapp,
        ";".join(e["value"] for e in emails),
        str(row_num),
    ])
    now = _now()
    return {
        "contact_id": contact_id,
        "source": "google_contacts_csv",
        "source_file": source_file,
        "source_row": row_num,
        "entity_ids": entity_ids,
        "entity_id": entity_ids[0] if entity_ids else None,
        "entity_hint": org,
        "name": name,
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "organization_name": org,
        "title": _norm(row.get("Organization Title")),
        "department": _norm(row.get("Organization Department")),
        "labels": labels,
        "emails": emails,
        "phones": phones,
        "whatsapp": whatsapp,
        "whatsapp_digits": whatsapp_digits,
        "phone": whatsapp,
        "phone_digits": whatsapp_digits,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "imported_at": now,
        "raw": {k: _norm(v) for k, v in row.items() if _norm(v)},
    }


def import_google_contacts_csv(
    path: str,
    *,
    entity_id: str | None = None,
    entity_ids: list[str] | None = None,
    upsert_ops: bool = True,
) -> dict[str, Any]:
    csv_path = Path(path)
    if not csv_path.is_file():
        return {"ok": False, "error": f"file not found: {csv_path}"}

    db = mongo_store.get_db()
    total = 0
    imported = 0
    ops_imported = 0
    entity_hits: dict[str, int] = {}

    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row_num, row in enumerate(reader, start=2):
            total += 1
            row_entity_id, _ = _entity_for_row(row)
            final_entity_ids = _collect_entity_ids(
                base_entity_ids=entity_ids,
                row_entity_id=row_entity_id,
                explicit_entity_id=entity_id,
            )
            for e in final_entity_ids:
                entity_hits[e] = entity_hits.get(e, 0) + 1
            doc = _contact_doc(row, row_num, csv_path.name, final_entity_ids)
            db[CONTACTS_COL].update_one(
                {"contact_id": doc["contact_id"]},
                {
                    "$set": {k: v for k, v in doc.items() if k != "created_at"},
                    "$setOnInsert": {"created_at": doc["created_at"]},
                },
                upsert=True,
            )
            imported += 1
            if upsert_ops and doc.get("whatsapp_digits"):
                ops_doc = {
                    "contact_id": doc["contact_id"],
                    "name": doc["name"],
                    "phone": doc["phone"],
                    "phone_digits": doc["phone_digits"],
                    "whatsapp": doc["whatsapp"],
                    "whatsapp_digits": doc["whatsapp_digits"],
                    "company": doc.get("organization_name", ""),
                    "tags": list(doc.get("labels", [])),
                    "entity_ids": final_entity_ids,
                    "entity_id": final_entity_ids[0] if final_entity_ids else None,
                    "metadata": {
                        "source": doc["source"],
                        "source_file": doc["source_file"],
                        "source_row": doc["source_row"],
                        "entity_hint": doc.get("entity_hint", ""),
                        "emails": doc.get("emails", []),
                    },
                    "notes": doc.get("notes", ""),
                    "source": doc["source"],
                    "updated_at": doc["updated_at"],
                }
                db[COL_OPS_CONTACTS].update_one(
                    {"contact_id": doc["contact_id"]},
                    {
                        "$set": {k: v for k, v in ops_doc.items() if k != "created_at"},
                        "$setOnInsert": {"created_at": doc["created_at"]},
                    },
                    upsert=True,
                )
                ops_imported += 1

    return {
        "ok": True,
        "file": str(csv_path),
        "rows_seen": total,
        "contacts_upserted": imported,
        "ops_contacts_upserted": ops_imported,
        "entity_hits": entity_hits,
    }


def link_contact_entities(contact_id: str, entity_ids: list[str]) -> dict[str, Any]:
    db = mongo_store.get_db()
    safe_ids = [e.strip() for e in entity_ids if e and e.strip()]
    now = _now()
    result = db[CONTACTS_COL].update_one(
        {"contact_id": contact_id},
        {"$set": {"entity_ids": safe_ids, "entity_id": safe_ids[0] if safe_ids else None, "updated_at": now}},
    )
    db[COL_OPS_CONTACTS].update_one(
        {"contact_id": contact_id},
        {"$set": {"entity_ids": safe_ids, "entity_id": safe_ids[0] if safe_ids else None, "updated_at": now}},
    )
    return {"ok": True, "matched": result.matched_count, "entity_ids": safe_ids}


def resolve_contact(identifier: str, limit: int = 10) -> dict[str, Any]:
    db = mongo_store.get_db()
    raw = (identifier or "").strip()
    digits = _digits(raw)
    escaped = re.escape(raw)
    clauses: list[dict[str, Any]] = [
        {"contact_id": raw},
        {"name": {"$regex": escaped, "$options": "i"}},
        {"organization_name": {"$regex": escaped, "$options": "i"}},
        {"labels": {"$regex": escaped, "$options": "i"}},
        {"notes": {"$regex": escaped, "$options": "i"}},
    ]
    if digits:
        clauses.extend([
            {"phone_digits": digits},
            {"whatsapp_digits": digits},
            {"phone": {"$regex": escaped, "$options": "i"}},
            {"whatsapp": {"$regex": escaped, "$options": "i"}},
            {"emails.value": {"$regex": escaped, "$options": "i"}},
        ])
    filt = {"$or": clauses}
    items = list(db[CONTACTS_COL].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 20))))
    if not items:
        items = list(db[COL_OPS_CONTACTS].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 20))))
    return {"ok": True, "count": len(items), "matches": items, "query": raw, "digits": digits}


def _chip_import_filter(*, include_groups: bool = False) -> dict[str, Any]:
    filt: dict[str, Any] = {"source": SOURCE_EVOLUTION_INNERCHISPA}
    if not include_groups:
        filt["contact_class"] = "chip_import"
    return filt


def chip_import_provenance() -> dict[str, Any]:
    """Metadatos estándar para contactos del chip Innerchispa (no personales)."""
    return dict(CHIP_IMPORT_PROVENANCE)


def ensure_chip_import_metadata(source: str = SOURCE_EVOLUTION_INNERCHISPA) -> dict[str, Any]:
    """Corrige en Mongo la procedencia de contactos importados del chip."""
    db = mongo_store.get_db()
    now = _now()
    prov = chip_import_provenance()
    entity_ids = ["ent_innerchispa"]
    contact_set = {
        **prov,
        "entity_ids": entity_ids,
        "entity_id": entity_ids[0],
        "labels": list(CHIP_IMPORT_LABELS),
        "updated_at": now,
    }
    ops_set = {
        **prov,
        "entity_ids": entity_ids,
        "entity_id": entity_ids[0],
        "tags": list(CHIP_IMPORT_LABELS),
        "metadata.known_to_owner": False,
        "metadata.relationship": prov["relationship"],
        "metadata.contact_class": prov["contact_class"],
        "metadata.origin_note": prov["origin_note"],
        "metadata.source_instance": prov["source_instance"],
        "updated_at": now,
    }
    c_res = db[CONTACTS_COL].update_many({"source": source}, {"$set": contact_set})
    o_res = db[COL_OPS_CONTACTS].update_many({"source": source}, {"$set": ops_set})
    group_set = {
        **prov,
        "entity_ids": entity_ids,
        "entity_id": entity_ids[0],
        "labels": ["innerchispa", "whatsapp_group", "marketing_pool", "chip_import", "not_personal"],
        "contact_class": "chip_import_group",
        "updated_at": now,
    }
    g_res = db[COL_OPS_WHATSAPP_GROUPS].update_many({"source": source}, {"$set": group_set})
    return {
        "ok": True,
        "source": source,
        "contacts_modified": c_res.modified_count,
        "ops_contacts_modified": o_res.modified_count,
        "groups_modified": g_res.modified_count,
        "provenance": prov,
    }


def list_marketing_pool(
    query: str | None = None,
    *,
    source: str = SOURCE_EVOLUTION_INNERCHISPA,
    known_to_owner: bool | None = False,
    limit: int = 50,
    skip: int = 0,
    include_groups: bool = False,
) -> dict[str, Any]:
    """Lista pool de marketing (chip Innerchispa). Por defecto solo desconocidos/no personales."""
    db = mongo_store.get_db()
    filt: dict[str, Any] = {"source": source}
    if known_to_owner is not None:
        filt["known_to_owner"] = known_to_owner
    if not include_groups:
        filt["contact_class"] = "chip_import"
    clauses: list[dict[str, Any]] = []
    if query:
        q = re.escape(query.strip())
        clauses.extend([
            {"name": {"$regex": q, "$options": "i"}},
            {"push_name": {"$regex": q, "$options": "i"}},
            {"whatsapp": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
            {"whatsapp_digits": {"$regex": q, "$options": "i"}},
        ])
    if clauses:
        filt = {"$and": [filt, {"$or": clauses}]}
    cap = max(1, min(limit, 200))
    skip_n = max(0, skip)
    cursor = (
        db[CONTACTS_COL]
        .find(filt, {"_id": 0, "raw": 0})
        .sort("name", 1)
        .skip(skip_n)
        .limit(cap)
    )
    items = list(cursor)
    total = db[CONTACTS_COL].count_documents(filt)
    groups: list[dict[str, Any]] = []
    groups_total = 0
    if include_groups:
        gfilt: dict[str, Any] = {"source": source}
        if known_to_owner is not None:
            gfilt["known_to_owner"] = known_to_owner
        groups_total = db[COL_OPS_WHATSAPP_GROUPS].count_documents(gfilt)
        groups = list(
            db[COL_OPS_WHATSAPP_GROUPS]
            .find(gfilt, {"_id": 0})
            .sort("name", 1)
            .limit(max(1, min(limit, 100)))
        )
    return {
        "ok": True,
        "pool": "innerchispa_chip_marketing",
        "disclaimer": CHIP_IMPORT_PROVENANCE["origin_note"],
        "known_to_owner_filter": known_to_owner,
        "count": len(items),
        "total": total,
        "skip": skip_n,
        "limit": cap,
        "contacts": items,
        "groups_count": len(groups),
        "groups_total": groups_total,
        "groups": groups,
    }


def marketing_pool_stats(source: str = SOURCE_EVOLUTION_INNERCHISPA) -> dict[str, Any]:
    db = mongo_store.get_db()
    base = {"source": source}
    return {
        "ok": True,
        "pool": "innerchispa_chip_marketing",
        "disclaimer": CHIP_IMPORT_PROVENANCE["origin_note"],
        "provenance": chip_import_provenance(),
        "contacts": db[CONTACTS_COL].count_documents({**base, "contact_class": "chip_import"}),
        "ops_contacts": db[COL_OPS_CONTACTS].count_documents(base),
        "groups": db[COL_OPS_WHATSAPP_GROUPS].count_documents(base),
        "not_personal": db[CONTACTS_COL].count_documents({**base, "known_to_owner": False}),
    }


def list_contacts(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    clauses: list[dict[str, Any]] = []
    if query:
        q = re.escape(query.strip())
        clauses.append({"name": {"$regex": q, "$options": "i"}})
        clauses.append({"organization_name": {"$regex": q, "$options": "i"}})
        clauses.append({"whatsapp": {"$regex": q, "$options": "i"}})
        clauses.append({"phone": {"$regex": q, "$options": "i"}})
        clauses.append({"labels": {"$regex": q, "$options": "i"}})
    if entity_id:
        clauses.append({"entity_ids": entity_id})
    if clauses:
        filt = {"$and": [{"$or": clauses}]}
    items = list(db[CONTACTS_COL].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(items), "contacts": items}


def _group_jid(value: str | None) -> str:
    raw = _norm(value)
    return raw if raw.endswith("@g.us") else raw


def save_whatsapp_group(
    payload: dict[str, Any],
) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now()
    group_jid = _group_jid(payload.get("group_jid") or payload.get("jid") or payload.get("conversation_id") or payload.get("id"))
    name = _norm(payload.get("name") or payload.get("title") or payload.get("alias") or group_jid)
    if not group_jid or not group_jid.endswith("@g.us"):
        return {"ok": False, "error": "group_jid required and must end with @g.us"}
    entity_ids = payload.get("entity_ids") or ([payload["entity_id"]] if payload.get("entity_id") else [])
    safe_entity_ids = [e.strip() for e in entity_ids if e and e.strip()]
    labels = payload.get("labels") or []
    doc = {
        "group_id": payload.get("group_id") or group_jid,
        "group_jid": group_jid,
        "name": name,
        "alias": _norm(payload.get("alias") or ""),
        "labels": labels,
        "entity_ids": safe_entity_ids,
        "entity_id": safe_entity_ids[0] if safe_entity_ids else None,
        "notes": _norm(payload.get("notes") or ""),
        "source": _norm(payload.get("source") or "manual"),
        "updated_at": now,
    }
    db[COL_OPS_WHATSAPP_GROUPS].update_one(
        {"group_jid": group_jid},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, "group": doc}


def list_whatsapp_groups(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    clauses: list[dict[str, Any]] = []
    if query:
        q = re.escape(query.strip())
        clauses.append({"name": {"$regex": q, "$options": "i"}})
        clauses.append({"alias": {"$regex": q, "$options": "i"}})
        clauses.append({"group_jid": {"$regex": q, "$options": "i"}})
        clauses.append({"notes": {"$regex": q, "$options": "i"}})
        clauses.append({"labels": {"$regex": q, "$options": "i"}})
    if entity_id:
        clauses.append({"entity_ids": entity_id})
    if clauses:
        filt = {"$and": [{"$or": clauses}]}
    items = list(db[COL_OPS_WHATSAPP_GROUPS].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(items), "groups": items}


def resolve_whatsapp_group(identifier: str, limit: int = 10) -> dict[str, Any]:
    db = mongo_store.get_db()
    raw = _norm(identifier)
    escaped = re.escape(raw)
    filt = {
        "$or": [
            {"group_jid": raw},
            {"group_id": raw},
            {"name": {"$regex": escaped, "$options": "i"}},
            {"alias": {"$regex": escaped, "$options": "i"}},
            {"labels": {"$regex": escaped, "$options": "i"}},
            {"notes": {"$regex": escaped, "$options": "i"}},
        ]
    }
    items = list(db[COL_OPS_WHATSAPP_GROUPS].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 20))))
    return {"ok": True, "count": len(items), "matches": items, "query": raw}


def broadcast_whatsapp_groups(
    message: str,
    *,
    group_ids: list[str] | None = None,
    labels: list[str] | None = None,
    entity_ids: list[str] | None = None,
    limit: int = 200,
    dry_run: bool = True,
    approved_by: str | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    clauses: list[dict[str, Any]] = []
    if group_ids:
        safe_group_ids = [g.strip() for g in group_ids if g and g.strip()]
        clauses.append({"group_jid": {"$in": safe_group_ids}})
        clauses.append({"group_id": {"$in": safe_group_ids}})
    if entity_ids:
        clauses.append({"entity_ids": {"$in": [e.strip() for e in entity_ids if e and e.strip()]}})
    if labels:
        clauses.append({"labels": {"$in": [l.strip() for l in labels if l and l.strip()]}})
    if clauses:
        filt = {"$and": [{"$or": clauses}]}
    cursor = db[COL_OPS_WHATSAPP_GROUPS].find(filt, {"_id": 0, "group_jid": 1, "name": 1, "alias": 1, "entity_ids": 1, "labels": 1}).limit(max(1, min(limit, 500)))
    targets = []
    seen: set[str] = set()
    for doc in cursor:
        jid = (doc.get("group_jid") or doc.get("group_id") or "").strip()
        if not jid or jid in seen:
            continue
        seen.add(jid)
        targets.append({"group_jid": jid, "name": doc.get("name"), "alias": doc.get("alias"), "entity_ids": doc.get("entity_ids", []), "labels": doc.get("labels", [])})
    if dry_run:
        return {"ok": True, "dry_run": True, "count": len(targets), "targets": targets}
    if not approved_by:
        return {"ok": False, "error": "approval_required", "message": "approved_by required for real broadcast", "count": len(targets), "targets": targets}
    sent = 0
    results = []
    for target in targets:
        res = send_whatsapp(message, number=target["group_jid"])
        results.append({"target": target, "result": res})
        if res.get("ok"):
            sent += 1
    return {"ok": True, "dry_run": False, "sent": sent, "count": len(targets), "results": results}


def broadcast_whatsapp(
    message: str,
    *,
    entity_ids: list[str] | None = None,
    labels: list[str] | None = None,
    limit: int = 200,
    dry_run: bool = True,
    approved_by: str | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    clauses: list[dict[str, Any]] = []
    if entity_ids:
        clauses.append({"entity_ids": {"$in": [e.strip() for e in entity_ids if e and e.strip()]}})
    if labels:
        clauses.append({"labels": {"$in": [l.strip() for l in labels if l and l.strip()]}})
    if clauses:
        filt = {"$and": [{"$or": clauses}]}
    cursor = db[COL_OPS_CONTACTS].find(filt, {"_id": 0, "whatsapp": 1, "phone": 1, "whatsapp_digits": 1, "name": 1, "contact_id": 1, "entity_ids": 1, "labels": 1}).limit(max(1, min(limit, 500)))
    targets = []
    seen: set[str] = set()
    for doc in cursor:
        recipient = (doc.get("whatsapp") or doc.get("phone") or "").strip()
        digits = "".join(c for c in recipient if c.isdigit())
        if not digits or digits in seen:
            continue
        seen.add(digits)
        targets.append({"contact_id": doc.get("contact_id"), "name": doc.get("name"), "recipient": digits, "entity_ids": doc.get("entity_ids", []), "labels": doc.get("labels", [])})
    if dry_run:
        return {"ok": True, "dry_run": True, "count": len(targets), "targets": targets}
    if not approved_by:
        return {"ok": False, "error": "approval_required", "message": "approved_by required for real broadcast", "count": len(targets), "targets": targets}
    sent = 0
    results = []
    for target in targets:
        res = send_whatsapp(message, number=target["recipient"])
        results.append({"target": target, "result": res})
        if res.get("ok"):
            sent += 1
    return {"ok": True, "dry_run": False, "sent": sent, "count": len(targets), "results": results}
