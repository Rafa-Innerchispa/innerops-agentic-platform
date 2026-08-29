"""AG-42 Service Guardian — ciclo permanente observabilidad (AG-40 + AG-31 + AG-41)."""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import Any
from uuid import uuid4

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-42_SERVICE_GUARDIAN"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_service_guardian(*, notify: bool = False) -> dict[str, Any]:
    """Un ciclo: reconciliar runtime, health watch, snapshot peer ops."""
    from raphiia_openai.agents import ag31_service_recovery_agent as ag31
    from raphiia_openai.agents import ag40_runtime_reconciler as ag40
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    reconcile = ag40.reconcile_runtime_state(dry_run=True)
    health = ag31.run_health_watch(notify=notify, trigger="AG-42")
    peers = ag41.peer_ops_snapshot()

    unhealthy = [
        i for i in (peers.get("items") or [])
        if i.get("ok") and not i.get("healthy") and not i.get("warm_standby")
    ]
    core_issues = list(reconcile.get("real_core_issues") or [])
    for issue in list(core_issues):
        if issue.get("service") == "raphiia-mcp" and issue.get("tcp_ok"):
            core_issues.remove(issue)

    ok = not core_issues and len(unhealthy) == 0
    out = {
        "ok": ok,
        "agent_id": AGENT_ID,
        "reconcile_summary": reconcile.get("summary"),
        "core_issues": core_issues,
        "health_ok": health.get("ok", True),
        "unhealthy_services": [
            {"service_id": i.get("service_id"), "node": i.get("node_label"), "health": i.get("health")}
            for i in unhealthy[:10]
        ],
        "warm_standby": peers.get("warm_standby_amd"),
        "recommended_action": None if ok else "peer_ops_status then peer_ops_action if needed",
    }
    record_agent_run(AGENT_ID, action="run_service_guardian", summary=f"ok={ok} unhealthy={len(unhealthy)}", project="ralfia-ops")
    return out


# Servicios auto-reparables (allowlist peer_ops)
_HEALABLE = frozenset({"mcp", "portal", "app", "coordination", "evolution"})


def _try_recover_mongo(*, auto_repair: bool) -> dict[str, Any] | None:
    """Reinicia contenedor docker mongodb en Intel si ping falla."""
    from raphiia_openai import mongo_store

    ping = mongo_store.ping_mongo()
    if ping.get("ok"):
        return None
    out: dict[str, Any] = {"ok": False, "before": ping, "action": None}
    if not auto_repair:
        out["dry_run"] = True
        out["would"] = "docker restart mongodb @192.168.1.4"
        return out
    import subprocess

    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "rlopez@192.168.1.4",
        "docker restart mongodb",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out["action"] = "docker_restart_mongodb"
        out["exit_code"] = proc.returncode
        out["stderr"] = (proc.stderr or "")[-300:]
        import time
        time.sleep(5)
        after = mongo_store.ping_mongo()
        out["after"] = after
        out["ok"] = bool(after.get("ok"))
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out


def _record_cycle_metrics(
    *,
    cycle_id: str,
    cycle_started_at: str,
    cycle_completed_at: str,
    cycle_duration_seconds: float,
    repairs: list[dict[str, Any]],
    post: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Best-effort self-heal telemetry; it must never break recovery itself."""
    if not repairs:
        return []
    try:
        from raphiia_openai import self_heal_metrics
    except Exception as exc:
        return [{"ok": False, "error": f"self_heal_metrics_import_failed:{exc}"}]

    post_ok = bool((post or {}).get("ok"))
    recorded: list[dict[str, Any]] = []
    for repair in repairs:
        result = repair.get("result") if isinstance(repair.get("result"), dict) else {}
        skipped = bool(repair.get("skipped"))
        action_ok = bool(result.get("ok")) if result else False
        service_id = str(repair.get("service_id") or "unknown")
        action = str(result.get("action") or ("skipped" if skipped else "restart"))
        try:
            item = self_heal_metrics.record_self_heal_incident(
                {
                    "incident_id": f"{cycle_id}:{service_id}:{len(recorded) + 1}",
                    "cycle_id": cycle_id,
                    "service_id": service_id,
                    "node": repair.get("node") or "",
                    "detected_at": cycle_started_at,
                    "repair_started_at": cycle_started_at,
                    "recovered_at": cycle_completed_at if action_ok and post_ok else None,
                    "repair_duration_seconds": cycle_duration_seconds,
                    "repair_action": action,
                    "repair_action_ok": action_ok,
                    "verified_recovered": action_ok and post_ok,
                    "verification_method": "AG-42 post-repair service guardian",
                    "automatic": True,
                    "human_intervention_required": False,
                    "human_intervention_minutes": 0,
                    "details": {"repair": repair, "post_guardian_ok": post_ok},
                }
            )
        except Exception as exc:
            item = {"ok": False, "error": str(exc)[:300], "service_id": service_id}
        recorded.append(item)
    return recorded


def run_self_heal_cycle(*, auto_repair: bool = False, max_repairs: int = 3) -> dict[str, Any]:
    """
    Ciclo auto-reparación local: detecta caídos → restart allowlisted vía AG-41.
    Incluye recuperación ngrok (AG-31) antes de restarts. Sin créditos cloud.

    Cuando auto_repair=True cada reparación real deja un incidente auditable.
    El ledger NO atribuye Human Hours Returned hasta que exista un baseline
    manual verificable para ese servicio.
    """
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    cycle_id = f"healcycle_{uuid4().hex[:12]}"
    cycle_started_at = _now()
    cycle_clock = monotonic()

    mongo_recover = _try_recover_mongo(auto_repair=auto_repair)
    guard = run_service_guardian(notify=False)
    ngrok_recover: dict[str, Any] | None = None
    try:
        from raphiia_openai import ngrok_watch

        ng = ngrok_watch.check_ngrok_tunnel()
        if ng.get("status") != "up" and auto_repair:
            ngrok_recover = ngrok_watch.try_recover_ngrok()
            if ngrok_recover.get("ok"):
                guard = run_service_guardian(notify=False)
    except Exception as exc:
        ngrok_recover = {"ok": False, "error": str(exc)[:200]}

    repairs: list[dict[str, Any]] = []
    if mongo_recover:
        repairs.append({"service_id": "mongodb", "node": "primary", "result": mongo_recover})
    if ngrok_recover:
        repairs.append({"service_id": "ngrok-public-tunnel", "node": "primary", "result": ngrok_recover})

    for item in guard.get("unhealthy_services") or []:
        if len(repairs) >= max(1, min(max_repairs, 5)):
            break
        sid = str(item.get("service_id") or "").lower()
        node_label = str(item.get("node") or item.get("node_label") or "primary")
        node = "amd" if node_label in (".5", "amd", "192.168.1.5") else "primary"
        if sid not in _HEALABLE:
            repairs.append({"service_id": sid, "node": node, "skipped": True, "reason": "not_healable"})
            continue
        result = ag41.peer_ops_action(sid, node=node, action="restart", dry_run=not auto_repair)
        repairs.append({"service_id": sid, "node": node, "result": result})
        if auto_repair and result.get("ok"):
            import time
            time.sleep(3)

    post = run_service_guardian(notify=False) if auto_repair and repairs else None
    healed = post.get("ok") if post else guard.get("ok")
    cycle_completed_at = _now()
    cycle_duration_seconds = max(0.0, monotonic() - cycle_clock)
    metric_records = (
        _record_cycle_metrics(
            cycle_id=cycle_id,
            cycle_started_at=cycle_started_at,
            cycle_completed_at=cycle_completed_at,
            cycle_duration_seconds=cycle_duration_seconds,
            repairs=repairs,
            post=post,
        )
        if auto_repair and repairs
        else []
    )

    record_agent_run(
        AGENT_ID,
        action="run_self_heal_cycle",
        summary=f"auto={auto_repair} repairs={len(repairs)} ok={healed}",
        project="ralfia-ops",
    )
    return {
        "ok": bool(healed),
        "agent_id": AGENT_ID,
        "cycle_id": cycle_id,
        "cycle_started_at": cycle_started_at,
        "cycle_completed_at": cycle_completed_at,
        "cycle_duration_seconds": round(cycle_duration_seconds, 3),
        "auto_repair": auto_repair,
        "mongo_recover": mongo_recover,
        "ngrok_recover": ngrok_recover,
        "before": guard,
        "repairs": repairs,
        "after": post,
        "self_heal_metric_records": metric_records,
        "local_only": True,
    }
