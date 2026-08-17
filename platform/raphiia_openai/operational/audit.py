"""Auditoría Operational Layer — quién hizo qué, cuándo (Guayaquil + UTC)."""

from __future__ import annotations

from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.operational.constants import COL_OPS_AUDIT_LOG


def log_ops_action(
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    summary: str,
    visibility: str = "INTERNAL",
    tool_used: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registro dual: ops_audit_log + ralfia_coordination_log."""
    db = mongo_store.get_db()
    doc = {
        "ts": ralfia_time.now_utc_iso(),
        "ts_local": ralfia_time.now_local_iso(),
        "ts_display": ralfia_time.format_log(),
        "actor": actor.strip().upper(),
        "action": action.strip(),
        "resource_type": resource_type,
        "resource_id": resource_id,
        "summary": summary.strip(),
        "visibility": visibility,
        "tool_used": tool_used,
        "metadata": metadata or {},
    }
    db[COL_OPS_AUDIT_LOG].insert_one(doc)
    mongo_store.log_coordination(
        agent=actor,
        summary=summary,
        event=f"ops_{action}",
        project="pc-doctor-ops",
        tool_used=tool_used,
        metadata={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "visibility": visibility,
            **(metadata or {}),
        },
    )
    return doc
