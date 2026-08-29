"""Auditable KPI ledger for InnerOS self-healing incidents.

The ledger deliberately separates operational recovery evidence from human-time
savings. A repair only contributes to Human Hours Returned when a real manual
baseline has been supplied. This prevents autonomous activity from being
misrepresented as verified ROI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from raphiia_openai import mongo_store
from raphiia_openai import productivity_metrics

INCIDENT_COLLECTION = "self_heal_incidents"
BASELINE_COLLECTION = "self_heal_baselines"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return bool(value)


def get_service_baseline(service_id: str) -> dict[str, Any] | None:
    service = str(service_id or "").strip().lower()
    if not service:
        return None
    return mongo_store.get_db()[BASELINE_COLLECTION].find_one({"service_id": service}, {"_id": 0})


def save_service_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    service_id = str(payload.get("service_id") or "").strip().lower()
    minutes = max(0.0, _float(payload.get("manual_baseline_minutes")))
    if not service_id:
        return {"ok": False, "error": "service_id_required"}
    if minutes <= 0:
        return {"ok": False, "error": "manual_baseline_minutes_must_be_positive"}
    measurement_class = str(payload.get("measurement_class") or "manual").strip().lower()
    if measurement_class not in productivity_metrics.VALID_MEASUREMENT_CLASSES:
        return {"ok": False, "error": "invalid_measurement_class"}
    evidence_refs = list(payload.get("evidence_refs") or [])
    row = {
        "service_id": service_id,
        "manual_baseline_minutes": minutes,
        "measurement_class": measurement_class,
        "verified": _bool(payload.get("verified", measurement_class == "measured")),
        "evidence_refs": evidence_refs,
        "notes": str(payload.get("notes") or "").strip(),
        "updated_at": _now(),
    }
    mongo_store.get_db()[BASELINE_COLLECTION].update_one(
        {"service_id": service_id},
        {"$set": row, "$setOnInsert": {"created_at": row["updated_at"]}},
        upsert=True,
    )
    return {"ok": True, "baseline": row}


def record_self_heal_incident(payload: dict[str, Any]) -> dict[str, Any]:
    service_id = str(payload.get("service_id") or "unknown").strip().lower()
    incident_id = str(payload.get("incident_id") or f"heal_{uuid4().hex[:12]}")
    cycle_id = str(payload.get("cycle_id") or incident_id)
    detected_at = payload.get("detected_at") or _now()
    recovered_at = payload.get("recovered_at")
    duration_seconds = max(0.0, _float(payload.get("repair_duration_seconds")))
    human_minutes = max(0.0, _float(payload.get("human_intervention_minutes")))
    human_intervention = _bool(payload.get("human_intervention_required")) or human_minutes > 0
    verified_recovered = _bool(payload.get("verified_recovered"))
    automatic = _bool(payload.get("automatic", True)) and not human_intervention

    baseline = get_service_baseline(service_id)
    manual_baseline_minutes = _float((baseline or {}).get("manual_baseline_minutes"))
    baseline_class = str((baseline or {}).get("measurement_class") or "").strip().lower()
    baseline_verified = _bool((baseline or {}).get("verified"))

    saved_minutes = 0.0
    productivity_task_key = None
    productivity_result = None
    if verified_recovered and manual_baseline_minutes > 0:
        saved_minutes = max(0.0, manual_baseline_minutes - human_minutes)
        productivity_task_key = f"selfheal:{incident_id}"
        productivity_result = productivity_metrics.save_productivity_event(
            {
                "task_key": productivity_task_key,
                "started_at": detected_at,
                "completed_at": recovered_at or _now(),
                "human_baseline_minutes": manual_baseline_minutes,
                "assisted_minutes": human_minutes,
                "measurement_class": baseline_class or "manual",
                "verified": baseline_verified and baseline_class == "measured",
                "confidence": "high" if baseline_verified else "medium",
                "evidence_refs": list((baseline or {}).get("evidence_refs") or [])
                + list(payload.get("evidence_refs") or []),
                "notes": f"Self-heal {service_id}; autonomous={automatic}; verification={verified_recovered}",
                "source": "self_heal_metrics",
            }
        )

    row = {
        "incident_id": incident_id,
        "cycle_id": cycle_id,
        "service_id": service_id,
        "node": str(payload.get("node") or "").strip(),
        "detected_at": detected_at,
        "repair_started_at": payload.get("repair_started_at") or detected_at,
        "recovered_at": recovered_at,
        "repair_duration_seconds": round(duration_seconds, 3),
        "repair_action": str(payload.get("repair_action") or "").strip(),
        "repair_action_ok": _bool(payload.get("repair_action_ok")),
        "verified_recovered": verified_recovered,
        "verification_method": str(payload.get("verification_method") or "").strip(),
        "automatic": automatic,
        "human_intervention_required": human_intervention,
        "human_intervention_minutes": human_minutes,
        "manual_baseline_minutes": manual_baseline_minutes if baseline else None,
        "baseline_measurement_class": baseline_class or None,
        "baseline_verified": baseline_verified if baseline else False,
        "saved_minutes": round(saved_minutes, 3),
        "human_hours_returned": round(saved_minutes / 60.0, 4),
        "productivity_task_key": productivity_task_key,
        "evidence_refs": list(payload.get("evidence_refs") or []),
        "details": payload.get("details") or {},
        "created_at": _now(),
    }
    mongo_store.get_db()[INCIDENT_COLLECTION].update_one(
        {"incident_id": incident_id}, {"$set": row}, upsert=True
    )
    return {
        "ok": True,
        "incident": row,
        "productivity_recorded": productivity_result is not None,
        "productivity_result": productivity_result,
        "roi_counted": bool(verified_recovered and manual_baseline_minutes > 0),
    }


def summarize_self_heal_incidents(limit: int = 500) -> dict[str, Any]:
    rows = list(
        mongo_store.get_db()[INCIDENT_COLLECTION]
        .find({}, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(int(limit or 500), 5000)))
    )
    count = len(rows)
    verified = [row for row in rows if _bool(row.get("verified_recovered"))]
    automatic_verified = [row for row in verified if _bool(row.get("automatic"))]
    human_interventions = [row for row in rows if _bool(row.get("human_intervention_required"))]
    recovered_durations = [
        _float(row.get("repair_duration_seconds")) for row in verified if _float(row.get("repair_duration_seconds")) >= 0
    ]
    saved = sum(_float(row.get("saved_minutes")) for row in rows)
    verified_saved = sum(
        _float(row.get("saved_minutes"))
        for row in rows
        if _bool(row.get("baseline_verified"))
        and str(row.get("baseline_measurement_class") or "").lower() == "measured"
        and _bool(row.get("verified_recovered"))
    )
    return {
        "ok": True,
        "incident_count": count,
        "verified_recoveries": len(verified),
        "automatic_verified_recoveries": len(automatic_verified),
        "recovery_rate_percent": round((len(verified) / count) * 100, 2) if count else 0.0,
        "human_intervention_rate_percent": round((len(human_interventions) / count) * 100, 2) if count else 0.0,
        "mttr_seconds": round(sum(recovered_durations) / len(recovered_durations), 3) if recovered_durations else 0.0,
        "human_hours_returned": round(saved / 60.0, 4),
        "verified_human_hours_returned": round(verified_saved / 60.0, 4),
        "incidents_without_baseline": sum(1 for row in rows if row.get("manual_baseline_minutes") is None),
    }
