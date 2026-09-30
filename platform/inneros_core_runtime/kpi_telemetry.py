"""Minimal KPI telemetry hooks on the canonical tracking envelope."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

KPI_SCHEMA_VERSION = "inneros_kpi_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def human_hours_returned(
    *,
    estimated_manual_minutes: float,
    human_minutes_spent: float,
    source: str = "operator_estimate",
    confidence: str = "low",
) -> dict[str, Any]:
    saved = max(float(estimated_manual_minutes) - float(human_minutes_spent), 0.0)
    return {
        "human_hours_returned": round(saved / 60.0, 4),
        "automated_minutes_saved": saved,
        "estimated_manual_minutes": estimated_manual_minutes,
        "human_minutes_spent": human_minutes_spent,
        "source": source,
        "confidence": confidence,
        "measured": confidence == "measured",
    }


def record_task_kpi(
    *,
    task_id: str,
    agent: str,
    outcome: str,
    correlation_id: str = "",
    provider: str = "",
    model: str = "",
    task_type: str = "",
    estimated_manual_minutes: float = 0.0,
    human_minutes_spent: float = 0.0,
    energy_source: str = "UNAVAILABLE",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce one machine-readable KPI row; never label synthetic data measured."""
    hh = human_hours_returned(
        estimated_manual_minutes=estimated_manual_minutes,
        human_minutes_spent=human_minutes_spent,
        source="envelope" if estimated_manual_minutes else "unavailable",
        confidence="estimated" if estimated_manual_minutes else "unavailable",
    )
    row = {
        "schema_version": KPI_SCHEMA_VERSION,
        "task_id": task_id,
        "agent": agent,
        "outcome": outcome,
        "correlation_id": correlation_id,
        "provider": provider,
        "model": model,
        "task_type": task_type,
        "completed_at": _now(),
        "human_hours_returned": hh,
        "energy_telemetry": {"source": energy_source},
        "automation_rate_eligible": outcome in ("PASS", "OK", "completed"),
    }
    if extra:
        row.update(extra)
    return row
