"""Append-only model/provider execution journal on ops tasks (HA historial #227)."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store, ralfia_time


def record_model_execution(
    task_id: str,
    *,
    provider: str,
    configured_model: str | None = None,
    resolved_model: str | None = None,
    model_source: str | None = None,
    usage: dict[str, Any] | None = None,
    transport: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    now = ralfia_time.now_utc_iso()
    entry: dict[str, Any] = {
        "at": now,
        "provider": (provider or "").strip().lower(),
        "configured_model": configured_model or None,
        "resolved_model": resolved_model or None,
        "model_source": model_source or "unknown",
        "usage": usage if isinstance(usage, dict) and usage else None,
        "transport": transport or None,
    }
    if extra:
        entry.update(extra)
    db = mongo_store.get_db()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$push": {"model_execution_journal": entry},
            "$set": {
                "updated_at": now,
                "last_model_execution": entry,
            },
            "$inc": {"revision": 1},
        },
    )
    return {"ok": True, "task_id": tid, "entry": entry}
