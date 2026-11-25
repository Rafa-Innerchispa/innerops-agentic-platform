"""Daily budget for Home Assistant Companion pushes (self-hosted, Intel → HA LAN).

Owner-authorization pushes are high-signal and exempt by default. Scout alerts,
coordination summaries, and task outcome fanout are low-signal and gated so they
do not burn the mobile Companion daily quota (~500).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

LEDGER = "ralfia_ops_ha_push_ledger"

# owner_auth: pulsar para aprobar OPS (siempre permitido por defecto)
# outcome: completed/failed (ruido si hay muchos agentes)
# scout: resúmenes, oportunidades, fallbacks email
# transition: otros cambios de estado
CLASS_OWNER_AUTH = "owner_auth"
CLASS_OUTCOME = "outcome"
CLASS_SCOUT = "scout"
CLASS_TRANSITION = "transition"


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cap() -> int:
    try:
        return max(1, int(os.getenv("OPS_HA_PUSH_DAILY_CAP", "120")))
    except ValueError:
        return 120


def _owner_auth_exempt() -> bool:
    return os.getenv("OPS_HA_PUSH_OWNER_AUTH_EXEMPT", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _collection():
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    col = db[LEDGER]
    col.create_index("day", unique=True)
    return col


def day_stats() -> dict[str, Any]:
    day = _today_key()
    col = _collection()
    row = col.find_one({"day": day}, {"_id": 0}) or {}
    counts = dict(row.get("counts") or {})
    total = int(row.get("total") or sum(int(v) for v in counts.values()))
    cap = _cap()
    return {
        "day": day,
        "total": total,
        "cap": cap,
        "remaining": max(0, cap - total),
        "counts": counts,
        "owner_auth_exempt": _owner_auth_exempt(),
    }


def should_send(push_class: str, *, force: bool = False) -> dict[str, Any]:
    """Fail-closed when daily cap reached (except owner_auth when exempt)."""
    pc = (push_class or CLASS_SCOUT).strip().lower()
    stats = day_stats()
    if force:
        return {"ok": True, "allowed": True, "reason": "forced", **stats}
    if pc == CLASS_OWNER_AUTH and _owner_auth_exempt():
        return {"ok": True, "allowed": True, "reason": "owner_auth_exempt", **stats}
    if stats["remaining"] <= 0:
        return {
            "ok": True,
            "allowed": False,
            "reason": "daily_cap_reached",
            "push_class": pc,
            **stats,
        }
    return {"ok": True, "allowed": True, "reason": "within_cap", "push_class": pc, **stats}


def record_sent(push_class: str, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    day = _today_key()
    pc = (push_class or CLASS_SCOUT).strip().lower()
    col = _collection()
    col.update_one(
        {"day": day},
        {
            "$inc": {f"counts.{pc}": 1, "total": 1},
            "$setOnInsert": {"day": day, "created_at": datetime.now(timezone.utc).isoformat()},
            "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )
    if meta:
        try:
            col.update_one(
                {"day": day},
                {
                    "$push": {
                        "last_events": {
                            "$each": [{"class": pc, **meta}],
                            "$slice": -40,
                        }
                    }
                },
            )
        except Exception:
            pass
    return day_stats()


def ha_outcomes_enabled() -> bool:
    return os.getenv("NOTIFY_OPS_HA_OUTCOMES", "0").strip().lower() in {"1", "true", "yes", "on"}


def ha_scout_enabled() -> bool:
    return os.getenv("NOTIFY_OPS_HA_SCOUT", "0").strip().lower() in {"1", "true", "yes", "on"}


def ops_primary_channel() -> str:
    """ha_companion = push directo Intel→HA→móvil; telegram = secundario opcional."""
    return (os.getenv("NOTIFY_OPS_PRIMARY") or "ha_companion").strip().lower()


def telegram_secondary_enabled() -> bool:
    if ops_primary_channel() != "ha_companion":
        return True
    return os.getenv("NOTIFY_OPS_TELEGRAM_SECONDARY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }