"""Persistencia tabular Memory Records — staging + canonical + dedupe."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.memory_record_schema import (
    auto_verification_status,
    record_fingerprint,
    validate_record,
    PathHierarchy,
)

RECORDS = "ralfia_memory_records"
FILE_INDEX = "ralfia_memory_file_index"
TENANT_DEFAULT = "RAFAEL"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rid(prefix: str = "mrec") -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def ensure_indexes() -> None:
    db = mongo_store.get_db()
    db[RECORDS].create_index("record_id", unique=True)
    db[RECORDS].create_index("fingerprint")
    db[RECORDS].create_index([("verification_status", 1), ("tenant_id", 1)])
    db[RECORDS].create_index([("hierarchy.brand", 1), ("hierarchy.client_name", 1)])
    db[RECORDS].create_index([("hierarchy.source_path", 1)])
    db[RECORDS].create_index("source_content_hash")
    db[FILE_INDEX].create_index("content_hash")
    db[FILE_INDEX].create_index("source_path", unique=True)


def index_file(*, source_path: str, content_hash: str, mtime: float, hierarchy: dict[str, Any]) -> dict[str, Any]:
    """Detecta archivos duplicados por hash de contenido."""
    ensure_indexes()
    db = mongo_store.get_db()
    existing = db[FILE_INDEX].find_one({"content_hash": content_hash, "source_path": {"$ne": source_path}})
    duplicate_of = existing.get("source_path") if existing else None
    doc = {
        "source_path": source_path,
        "content_hash": content_hash,
        "mtime": mtime,
        "hierarchy": hierarchy,
        "duplicate_of": duplicate_of,
        "updated_at": _now(),
    }
    db[FILE_INDEX].update_one({"source_path": source_path}, {"$set": doc}, upsert=True)
    return {"duplicate_of": duplicate_of, "is_duplicate": bool(duplicate_of)}


def save_records_from_extraction(
    raw_records: list[dict[str, Any]],
    *,
    source_path: str,
    content_hash: str,
    mtime: float,
    hierarchy: PathHierarchy,
    tenant_id: str = TENANT_DEFAULT,
    curator_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_indexes()
    db = mongo_store.get_db()
    file_info = index_file(
        source_path=source_path,
        content_hash=content_hash,
        mtime=mtime,
        hierarchy=hierarchy.to_dict(),
    )

    counts = {"canonical": 0, "extracted": 0, "review": 0, "rejected": 0, "duplicate": 0}
    record_ids: list[str] = []

    if file_info.get("is_duplicate"):
        counts["duplicate"] += 1
        return {"ok": True, "file_duplicate": True, "duplicate_of": file_info["duplicate_of"], "counts": counts}

    for raw in raw_records:
        validated, reject_reason = validate_record(raw, hierarchy)
        if not validated:
            counts["rejected"] += 1
            continue

        fp = record_fingerprint(
            tenant_id=tenant_id,
            brand=hierarchy.brand,
            client_name=hierarchy.client_name,
            record_type=validated["record_type"],
            attribute=validated["attribute"],
            subject_role=validated["subject_role"],
            subject_name=validated["subject_name"],
            value_normalized=validated["value_normalized"],
        )
        existing = db[RECORDS].find_one({"fingerprint": fp, "verification_status": {"$ne": "rejected"}})
        if existing:
            counts["duplicate"] += 1
            record_ids.append(existing["record_id"])
            db[RECORDS].update_one(
                {"record_id": existing["record_id"]},
                {"$addToSet": {"source_paths": source_path}, "$set": {"last_seen_at": _now()}},
            )
            continue

        verification = auto_verification_status(validated)
        counts[verification] = counts.get(verification, 0) + 1

        doc = {
            "record_id": _rid(),
            "tenant_id": tenant_id,
            "fingerprint": fp,
            "verification_status": verification,
            "searchable": verification == "canonical",
            "source_paths": [source_path],
            "source_content_hash": content_hash,
            "source_mtime": mtime,
            "curator": curator_meta or {},
            "created_at": _now(),
            "updated_at": _now(),
            "last_seen_at": _now(),
            **validated,
        }
        db[RECORDS].insert_one(doc)
        record_ids.append(doc["record_id"])

    return {"ok": True, "counts": counts, "record_ids": record_ids}


def search_records(
    query: str,
    *,
    tenant_id: str = TENANT_DEFAULT,
    canonical_only: bool = True,
    brand: str | None = None,
    client_name: str | None = None,
    record_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    ensure_indexes()
    db = mongo_store.get_db()
    filt: dict[str, Any] = {"tenant_id": tenant_id}
    if canonical_only:
        filt["verification_status"] = "canonical"
        filt["searchable"] = True
    if brand:
        filt["hierarchy.brand"] = brand
    if client_name:
        filt["hierarchy.client_name"] = {"$regex": client_name, "$options": "i"}
    if record_type:
        filt["record_type"] = record_type

    tokens = [t for t in (query or "").lower().split() if len(t) > 2]
    candidates = list(db[RECORDS].find(filt).limit(800))
    scored: list[dict[str, Any]] = []
    for item in candidates:
        blob = " ".join(
            [
                str(item.get("value_normalized") or ""),
                str(item.get("value_raw") or ""),
                str(item.get("subject_name") or ""),
                str((item.get("hierarchy") or {}).get("client_name") or ""),
                str(item.get("attribute") or ""),
                str(item.get("record_type") or ""),
            ]
        ).lower()
        score = sum(1 for t in tokens if t in blob) if tokens else 0
        if query.lower() in blob:
            score += 3
        if score > 0:
            item.pop("_id", None)
            item["score"] = score
            scored.append(item)
    scored.sort(key=lambda x: x["score"], reverse=True)
    items = scored[: max(1, min(limit, 50))]
    return {"ok": True, "count": len(items), "items": items, "canonical_only": canonical_only}


def stats(tenant_id: str = TENANT_DEFAULT) -> dict[str, Any]:
    ensure_indexes()
    db = mongo_store.get_db()
    pipeline = [
        {"$match": {"tenant_id": tenant_id}},
        {"$group": {"_id": "$verification_status", "n": {"$sum": 1}}},
    ]
    by_status = {r["_id"]: r["n"] for r in db[RECORDS].aggregate(pipeline)}
    clients = db[RECORDS].distinct("hierarchy.client_name", {"hierarchy.brand": "pcdoctor"})
    dup_files = db[FILE_INDEX].count_documents({"duplicate_of": {"$ne": None}})
    return {
        "ok": True,
        "by_status": by_status,
        "total": sum(by_status.values()),
        "pcdoctor_clients": sorted(c for c in clients if c),
        "duplicate_files": dup_files,
        "file_index_count": db[FILE_INDEX].estimated_document_count(),
    }
