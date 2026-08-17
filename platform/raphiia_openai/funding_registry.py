"""Funding / credits registry para RalfiIA."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from raphiia_openai import mongo_store
from raphiia_openai.settings import (
    COL_FUNDING_APPLICATIONS,
    COL_FUNDING_CREDIT_ACCOUNTS,
    COL_FUNDING_CREDIT_CONSUMPTIONS,
    COL_FUNDING_PROGRAMS,
    COL_FUNDING_PROJECT_LINKS,
)

VALID_STATUSES = {"draft", "active", "paused", "archived", "submitted", "approved", "rejected"}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out

def _oid(value: str | None) -> ObjectId | None:
    if not value:
        return None
    try:
        return ObjectId(value)
    except Exception:
        return None

def _db():
    return mongo_store.get_db()

def _clean_tags(tags: list[str] | None) -> list[str]:
    return [t.strip() for t in (tags or []) if str(t).strip()]

def save_funding_program(
    *,
    name: str,
    description: str | None = None,
    status: str | None = "active",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "chatgpt_mcp",
) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    status_value = (status or "active").strip().lower()
    if status_value not in VALID_STATUSES:
        status_value = "active"
    doc = {
        "name": name.strip(),
        "description": (description or "").strip(),
        "status": status_value,
        "tags": _clean_tags(tags),
        "metadata": metadata or {},
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_FUNDING_PROGRAMS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"ok": True, "program": _serialize(doc)}

def list_funding_programs(query: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    db = _db()
    limit = max(1, min(int(limit), 100))
    filt: dict[str, Any] = {}
    if status:
        filt["status"] = status.strip().lower()
    if query:
        q = query.strip()
        if q:
            filt["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
                {"tags": {"$elemMatch": {"$regex": q, "$options": "i"}}},
            ]
    cursor = db[COL_FUNDING_PROGRAMS].find(filt).sort("updated_at", -1).limit(limit)
    items = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(items), "items": items, "filter": filt}

def save_funding_application(
    *,
    title: str,
    program_id: str | None = None,
    body: str | None = None,
    status: str | None = "draft",
    metadata: dict[str, Any] | None = None,
    source: str = "chatgpt_mcp",
) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    status_value = (status or "draft").strip().lower()
    if status_value not in VALID_STATUSES:
        status_value = "draft"
    doc = {
        "title": title.strip(),
        "program_id": program_id,
        "body": (body or "").strip(),
        "status": status_value,
        "metadata": metadata or {},
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_FUNDING_APPLICATIONS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"ok": True, "application": _serialize(doc)}

def list_funding_applications(
    *,
    limit: int = 20,
    program_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    db = _db()
    limit = max(1, min(int(limit), 100))
    filt: dict[str, Any] = {}
    if program_id:
        filt["program_id"] = program_id.strip()
    if status:
        filt["status"] = status.strip().lower()
    cursor = db[COL_FUNDING_APPLICATIONS].find(filt).sort("updated_at", -1).limit(limit)
    items = [_serialize(doc) for doc in cursor]
    return {"ok": True, "count": len(items), "items": items, "filter": filt}

def save_funding_credit_account(
    *,
    name: str,
    provider: str | None = None,
    currency: str = "USD",
    balance: float | int = 0,
    status: str | None = "active",
    metadata: dict[str, Any] | None = None,
    source: str = "chatgpt_mcp",
) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    status_value = (status or "active").strip().lower()
    if status_value not in VALID_STATUSES:
        status_value = "active"
    doc = {
        "name": name.strip(),
        "provider": (provider or "").strip(),
        "currency": currency.strip().upper() or "USD",
        "balance": float(balance or 0),
        "status": status_value,
        "metadata": metadata or {},
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_FUNDING_CREDIT_ACCOUNTS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"ok": True, "account": _serialize(doc)}

def record_funding_consumption(
    *,
    account_id: str,
    amount: float | int,
    reason: str,
    currency: str | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "chatgpt_mcp",
) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    oid = _oid(account_id)
    if oid is None:
        return {"ok": False, "error": f"invalid account_id: {account_id}"}
    account = db[COL_FUNDING_CREDIT_ACCOUNTS].find_one({"_id": oid})
    if not account:
        return {"ok": False, "error": f"account not found: {account_id}"}
    amt = float(amount or 0)
    doc = {
        "account_id": str(oid),
        "amount": amt,
        "currency": (currency or account.get("currency") or "USD").strip().upper(),
        "reason": reason.strip(),
        "metadata": metadata or {},
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_FUNDING_CREDIT_CONSUMPTIONS].insert_one(doc)
    doc["_id"] = result.inserted_id
    new_balance = float(account.get("balance") or 0) - amt
    db[COL_FUNDING_CREDIT_ACCOUNTS].update_one(
        {"_id": oid},
        {"$set": {"balance": new_balance, "updated_at": now}},
    )
    account = db[COL_FUNDING_CREDIT_ACCOUNTS].find_one({"_id": oid}) or account
    return {"ok": True, "consumption": _serialize(doc), "account": _serialize(account)}

def link_funding_project(
    *,
    project_name: str | None = None,
    project_id: str | None = None,
    program_id: str | None = None,
    application_id: str | None = None,
    external_ref: str | None = None,
    status: str | None = "active",
    metadata: dict[str, Any] | None = None,
    source: str = "chatgpt_mcp",
) -> dict[str, Any]:
    db = _db()
    now = _now_iso()
    status_value = (status or "active").strip().lower()
    if status_value not in VALID_STATUSES:
        status_value = "active"
    doc = {
        "project_name": (project_name or "").strip(),
        "project_id": (project_id or "").strip(),
        "program_id": (program_id or "").strip() or None,
        "application_id": (application_id or "").strip() or None,
        "external_ref": (external_ref or "").strip(),
        "status": status_value,
        "metadata": metadata or {},
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_FUNDING_PROJECT_LINKS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"ok": True, "link": _serialize(doc)}

def get_funding_registry_summary(limit: int = 5) -> dict[str, Any]:
    db = _db()
    limit = max(1, min(int(limit), 20))
    return {
        "ok": True,
        "counts": {
            "programs": db[COL_FUNDING_PROGRAMS].count_documents({}),
            "applications": db[COL_FUNDING_APPLICATIONS].count_documents({}),
            "credit_accounts": db[COL_FUNDING_CREDIT_ACCOUNTS].count_documents({}),
            "consumptions": db[COL_FUNDING_CREDIT_CONSUMPTIONS].count_documents({}),
            "project_links": db[COL_FUNDING_PROJECT_LINKS].count_documents({}),
        },
        "recent": {
            "programs": [_serialize(d) for d in db[COL_FUNDING_PROGRAMS].find({}).sort("updated_at", -1).limit(limit)],
            "applications": [_serialize(d) for d in db[COL_FUNDING_APPLICATIONS].find({}).sort("updated_at", -1).limit(limit)],
            "credit_accounts": [_serialize(d) for d in db[COL_FUNDING_CREDIT_ACCOUNTS].find({}).sort("updated_at", -1).limit(limit)],
            "consumptions": [_serialize(d) for d in db[COL_FUNDING_CREDIT_CONSUMPTIONS].find({}).sort("updated_at", -1).limit(limit)],
            "project_links": [_serialize(d) for d in db[COL_FUNDING_PROJECT_LINKS].find({}).sort("updated_at", -1).limit(limit)],
        },
    }
