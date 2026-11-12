"""Productivity/ROI ledger for InnerOS automation savings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "productivity_metrics"
VALID_MEASUREMENT_CLASSES = frozenset({"measured", "estimated", "inferred", "manual"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _minutes_between(start: Any, end: Any) -> float:
    begin, finish = _parse_ts(start), _parse_ts(end)
    if begin is None or finish is None:
        return 0.0
    return round(max(0.0, (finish - begin).total_seconds() / 60.0), 3)


def record_task_completion(
    task: dict[str, Any] | None,
    *,
    outcome: str,
    requested: str | None = None,
    now_iso: str | None = None,
    source: str = "ops_complete",
) -> dict[str, Any]:
    """MEASURED lifecycle event built from real task timestamps.

    Never fabricates savings: the human baseline is unknown at completion
    time, so it stays 0 and saved/HTR stay 0. What IS measured: wall-clock
    durations, throughput counts, lanes, providers, outcomes.
    """
    data = dict(task or {})
    tid = str(data.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_key_required"}
    lane = str(data.get("execution_lane") or "").strip()
    provider = str(data.get("preferred_provider") or data.get("assignee") or "").strip()
    outcome_n = (outcome or "").strip().lower() or "unknown"
    requested_n = (requested or outcome_n).strip().lower()
    end = now_iso or _now()
    start = data.get("claimed_at") or data.get("created_at")
    return save_productivity_event(
        {
            "task_key": tid,
            "started_at": start,
            "completed_at": end,
            "human_baseline_minutes": 0.0,
            "assisted_minutes": _minutes_between(start, end),
            "measurement_class": "measured",
            "verified": True,
            "confidence": "high",
            "evidence_refs": [tid],
            "notes": f"lane={lane or '?'} provider={provider or '?'} outcome={outcome_n} requested={requested_n}",
            "source": source,
        }
    )


def calculate_event(payload: dict[str, Any]) -> dict[str, Any]:
    human = max(0.0, _float(payload.get("human_baseline_minutes")))
    assisted = max(0.0, _float(payload.get("assisted_minutes")))
    saved = max(0.0, human - assisted)
    reduction = round((saved / human) * 100, 2) if human else 0.0
    speedup = round(human / assisted, 2) if assisted else 0.0
    measurement_class = str(payload.get("measurement_class") or "manual").strip().lower()
    if measurement_class not in VALID_MEASUREMENT_CLASSES:
        measurement_class = "manual"
    verified = bool(payload.get("verified", measurement_class == "measured"))
    return {
        "task_key": str(payload.get("task_key") or "").strip(),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at") or _now(),
        "human_baseline_minutes": human,
        "assisted_minutes": assisted,
        "saved_minutes": saved,
        "human_hours_returned": round(saved / 60.0, 4),
        "reduction_percent": reduction,
        "speedup": speedup,
        "measurement_class": measurement_class,
        "verified": verified,
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
    verified_saved = sum(
        _float(row.get("saved_minutes"))
        for row in rows
        if bool(row.get("verified"))
        and str(row.get("measurement_class") or "").strip().lower() == "measured"
    )
    by_measurement_class: dict[str, int] = {}
    for row in rows:
        key = str(row.get("measurement_class") or "legacy").strip().lower()
        by_measurement_class[key] = by_measurement_class.get(key, 0) + 1
    return {
        "ok": True,
        "count": len(rows),
        "human_baseline_minutes": human,
        "assisted_minutes": assisted,
        "saved_minutes": saved,
        "human_hours_returned": round(saved / 60.0, 4),
        "verified_human_hours_returned": round(verified_saved / 60.0, 4),
        "reduction_percent": reduction,
        "speedup": speedup,
        "by_measurement_class": by_measurement_class,
    }
