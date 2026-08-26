"""Productivity/ROI ledger for InnerOS automation savings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "productivity_metrics"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_event(payload: dict[str, Any]) -> dict[str, Any]:
    human = max(0.0, _float(payload.get("human_baseline_minutes")))
    assisted = max(0.0, _float(payload.get("assisted_minutes")))
    saved = max(0.0, human - assisted)
    reduction = round((saved / human) * 100, 2) if human else 0.0
    speedup = round(human / assisted, 2) if assisted else 0.0
    return {
        "task_key": str(payload.get("task_key") or "").strip(),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at") or _now(),
        "human_baseline_minutes": human,
        "assisted_minutes": assisted,
        "saved_minutes": saved,
        "reduction_percent": reduction,
        "speedup": speedup,
        "confidence": str(payload.get("confidence") or "medium").strip().lower(),
        "evidence_refs": list(payload.get("evidence_refs") or []),
        "notes": str(payload.get("notes") or "").strip(),
        "source": str(payload.get("source") or "mcp").strip(),
    }


def save_productivity_event(payload: dict[str, Any]) -> dict[str, Any]:
    event = calculate_event(payload)
    if not event["task_key"]:
        return {"ok": False, "error": "task_key_required"}
    now = _now()
    event["updated_at"] = now
    existing = mongo_store.get_db()[COLLECTION].find_one({"task_key": event["task_key"]}, {"_id": 0})
    update = {"$set": event, "$setOnInsert": {"created_at": now}}
    mongo_store.get_db()[COLLECTION].update_one({"task_key": event["task_key"]}, update, upsert=True)
    saved = mongo_store.get_db()[COLLECTION].find_one({"task_key": event["task_key"]}, {"_id": 0})
    return {"ok": True, "created": existing is None, "event": saved}


def list_productivity_events(limit: int = 50, task_key: str = "") -> dict[str, Any]:
    query: dict[str, Any] = {}
    if task_key:
        query["task_key"] = task_key
    rows = list(
        mongo_store.get_db()[COLLECTION]
        .find(query, {"_id": 0})
        .sort("completed_at", -1)
        .limit(max(1, min(int(limit or 50), 500)))
    )
    return {"ok": True, "count": len(rows), "events": rows}


def summarize_productivity_events(limit: int = 500) -> dict[str, Any]:
    rows = list_productivity_events(limit=limit).get("events") or []
    human = sum(_float(row.get("human_baseline_minutes")) for row in rows)
    assisted = sum(_float(row.get("assisted_minutes")) for row in rows)
    saved = sum(_float(row.get("saved_minutes")) for row in rows)
    reduction = round((saved / human) * 100, 2) if human else 0.0
    speedup = round(human / assisted, 2) if assisted else 0.0
    return {
        "ok": True,
        "count": len(rows),
        "human_baseline_minutes": human,
        "assisted_minutes": assisted,
        "saved_minutes": saved,
        "reduction_percent": reduction,
        "speedup": speedup,
    }
