"""Cola de autorización ops por teléfono owner (1=Sí, 2=No, encuesta)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

COL = "ralfia_whatsapp_ops_auth_pending"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_phone(phone: str) -> str:
    return "".join(c for c in str(phone or "") if c.isdigit())


def register_pending(*, phone: str, task_id: str, provider: str, poll_message_id: str | None = None) -> dict[str, Any]:
    db = mongo_store.get_db()
    doc = {
        "phone": _norm_phone(phone),
        "task_id": task_id.strip(),
        "provider": provider,
        "poll_message_id": poll_message_id,
        "status": "pending",
        "updated_at": _now(),
    }
    db[COL].update_one(
        {"task_id": doc["task_id"]},
        {"$set": doc, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    return {"ok": True, **doc}


def latest_pending(phone: str) -> dict[str, Any] | None:
    db = mongo_store.get_db()
    return db[COL].find_one(
        {"phone": _norm_phone(phone), "status": "pending"},
        sort=[("updated_at", -1)],
    )


def clear_pending(task_id: str) -> None:
    mongo_store.get_db()[COL].update_one(
        {"task_id": task_id.strip()},
        {"$set": {"status": "resolved", "updated_at": _now()}},
    )


def find_by_poll_message_id(poll_message_id: str) -> dict[str, Any] | None:
    pid = str(poll_message_id or "").strip()
    if not pid:
        return None
    db = mongo_store.get_db()
    pending = db[COL].find_one({"poll_message_id": pid, "status": "pending"}, sort=[("updated_at", -1)])
    if pending:
        return pending
    return db[COL].find_one({"poll_message_id": pid}, sort=[("updated_at", -1)])


def pending_for_phone(phone: str, *, limit: int = 5) -> list[dict[str, Any]]:
    return list(
        mongo_store.get_db()[COL]
        .find({"phone": _norm_phone(phone), "status": "pending"})
        .sort("updated_at", -1)
        .limit(max(1, limit))
    )
