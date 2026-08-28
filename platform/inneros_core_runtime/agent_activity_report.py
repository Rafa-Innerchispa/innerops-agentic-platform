"""Agent Activity Report — resumen automático de ejecuciones reales."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.agent_auto_log import COL_AGENT_ACTIVITY, record_agent_run

AGENT_ID = "AG-58_ACTIVITY_REPORT"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_recent_agent_activity(*, hours: int = 24, limit: int = 50) -> dict[str, Any]:
    db = mongo_store.get_db()
    since = (_now() - timedelta(hours=max(1, hours))).isoformat()
    items = list(
        db[COL_AGENT_ACTIVITY]
        .find({"finished_at": {"$gte": since}})
        .sort("finished_at", -1)
        .limit(max(1, min(limit, 200)))
    )
    for doc in items:
        doc["_id"] = str(doc.get("_id", ""))
    by_agent = Counter(str(i.get("agent") or "?") for i in items)
    return {
        "ok": True,
        "hours": hours,
        "count": len(items),
        "by_agent": dict(by_agent.most_common(20)),
        "items": items,
    }


def generate_agent_activity_report(*, hours: int = 24, include_ops: bool = True) -> dict[str, Any]:
    db = mongo_store.get_db()
    since = _now() - timedelta(hours=max(1, hours))
    since_iso = since.isoformat()

    activity = list(
        db[COL_AGENT_ACTIVITY]
        .find({"finished_at": {"$gte": since_iso}})
        .sort("finished_at", -1)
        .limit(500)
    )
    by_agent = Counter(str(i.get("agent") or "?") for i in activity)
    by_action = Counter(str(i.get("action") or "?") for i in activity)

    ingest_cp = db.ingest_pipeline_checkpoint.find_one({"_id": "pst"}) or {}
    vkr_cp = db.ingest_pipeline_checkpoint.find_one({"_id": "email_vkr"}) or {}
    memory_canonical = db.ralfia_memory_records.count_documents({"verification_status": "canonical"})
    email_pst = db.email_messages.count_documents({"source": "pst_import"})

    open_ops = db.ralfia_ops_tasks.count_documents(
        {"status": {"$nin": ["completed", "cancelled", "superseded", "done"]}}
    )
    backlog_open = db.ralfia_dev_backlog.count_documents(
        {"status": {"$in": ["planned", "in_progress", "discussed"]}}
    )

    fleet: dict[str, Any] = {}
    try:
        from raphiia_openai import mcp_fleet

        fleet = mcp_fleet.fleet_status()
    except Exception as exc:
        fleet = {"error": str(exc)[:200]}

    highlights: list[str] = []
    for row in activity[:12]:
        highlights.append(
            f"{row.get('agent')} · {row.get('action')} — {(row.get('summary') or '')[:120]}"
        )

    report_text = (
        f"# Agent Activity Report — {ralfia_time.format_log()}\n\n"
        f"Ventana: últimas {hours}h\n"
        f"Ejecuciones registradas: {len(activity)}\n"
        f"Agentes activos: {len(by_agent)}\n\n"
        f"## Top agentes\n"
        + "\n".join(f"- {a}: {n}" for a, n in by_agent.most_common(10))
        + f"\n\n## Ingesta / memoria\n"
        f"- PST completados: {len(ingest_cp.get('pst_hashes') or [])}/22\n"
        f"- Correos PST: {email_pst}\n"
        f"- VKR procesados: {len(vkr_cp.get('mail_ids') or [])}\n"
        f"- Memoria canonical: {memory_canonical}\n\n"
        f"## Coordinación\n"
        f"- Ops abiertas: {open_ops}\n"
        f"- Backlog abierto: {backlog_open}\n\n"
        f"## Highlights\n"
        + "\n".join(f"- {h}" for h in highlights[:10])
    )

    result = {
        "ok": True,
        "agent_id": AGENT_ID,
        "hours": hours,
        "generated_at": _now().isoformat(),
        "activity_count": len(activity),
        "by_agent": dict(by_agent.most_common(30)),
        "by_action": dict(by_action.most_common(20)),
        "ingest": {
            "pst_done": len(ingest_cp.get("pst_hashes") or []),
            "email_pst": email_pst,
            "vkr_processed": len(vkr_cp.get("mail_ids") or []),
            "memory_canonical": memory_canonical,
        },
        "coordination": {"open_ops": open_ops, "backlog_open": backlog_open},
        "fleet_ok": fleet.get("ok"),
        "report_text": report_text,
        "highlights": highlights,
    }

    if include_ops:
        result["open_ops"] = open_ops

    db["ralfia_agent_activity_reports"].update_one(
        {"_id": "latest"},
        {"$set": {**result, "updated_at": _now().isoformat()}},
        upsert=True,
    )
    record_agent_run(
        AGENT_ID,
        action="generate_report",
        summary=f"activity={len(activity)} ops_open={open_ops}",
        project="ralfia-ops",
        mirror_feed=True,
    )
    return result
