"""AG-36 Deferred Tasks Sentinel — ops propuestas/atrasadas."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-36_DEFERRED_TASKS"


def run_deferred_ops_scan(*, limit: int = 30) -> dict[str, Any]:
    from raphiia_openai import coordination_live

    open_tasks = coordination_live.list_ops_tasks(status=None, limit=limit)
    items = open_tasks.get("tasks") or open_tasks.get("items") or []
    deferred = [
        t for t in items
        if str(t.get("status", "")).lower() in ("proposed", "blocked", "verification")
    ]
    record_agent_run(AGENT_ID, action="deferred_scan", summary=f"count={len(deferred)}", project="ralfia-ops")
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "total": len(items),
        "deferred_count": len(deferred),
        "deferred": deferred[:limit],
        "action_hint": "create_ops_task / complete_ops_task vía RalfIA",
    }


def run_deferred_ops_cycle(*, auto_escalate: bool = False, limit: int = 30) -> dict[str, Any]:
    """Scan + opcional escalado local a ops tasks (sin cloud)."""
    from raphiia_openai import coordination_live

    scan = run_deferred_ops_scan(limit=limit)
    escalations: list[dict[str, Any]] = []
    if auto_escalate:
        keywords = ("guardian", "unhealthy", "ngrok", "mcp", "reconcile", "self_heal", "servicio")
        for task in scan.get("deferred") or []:
            title = str(task.get("title") or "")
            if not any(k in title.lower() for k in keywords):
                continue
            created = coordination_live.create_ops_task(
                assignee="cursor",
                title=f"[AG-36] Escalar: {title[:120]}",
                checklist=[
                    "Revisar evidencia en HUB/ESTADO_VIVO.md",
                    "run_self_heal_cycle(auto_repair=true) si aplica",
                    "Completar ops task con evidencia",
                ],
                from_agent=AGENT_ID,
                related_project="ralfia-ops",
            )
            escalations.append({"source_title": title, "result": created})

    record_agent_run(
        AGENT_ID,
        action="deferred_cycle",
        summary=f"deferred={scan.get('deferred_count')} escalated={len(escalations)}",
        project="ralfia-ops",
    )
    return {
        **scan,
        "auto_escalate": auto_escalate,
        "escalations": escalations,
        "local_only": True,
    }
