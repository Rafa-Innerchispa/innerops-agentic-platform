"""AG-31 Service Recovery Watchdog — post-reinicio, health watch, WhatsApp down/up."""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.agents.base import AgentBase
from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

AGENT_ID = "AG-31_SERVICE_RECOVERY"
COL_HEALTH_WATCH = "ralfia_health_watch"
DOC_ID = "global"
UP_STATUSES = frozenset({"up", "unauthorized_alive"})
CRITICAL_IDS = frozenset({"portal", "ralphia-app", "mcp", "editorial"})
DRILL_UNITS = [
    ("ralfia-mcp.service", "user"),
    ("ralfia-app.service", "user"),
    ("ralfia-portal.service", "user"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict[str, Any]:
    db = mongo_store.get_db()
    doc = db[COL_HEALTH_WATCH].find_one({"_id": DOC_ID})
    if doc:
        doc.pop("_id", None)
        return doc
    return {"cockpit": {}, "registry": {}, "initialized": False}


def _save_state(state: dict[str, Any]) -> None:
    db = mongo_store.get_db()
    db[COL_HEALTH_WATCH].update_one(
        {"_id": DOC_ID},
        {"$set": {**state, "updated_at": _now_iso()}},
        upsert=True,
    )


def _cockpit_snapshot() -> dict[str, str]:
    from raphiia_openai import service_control

    data = service_control.cockpit_status()
    return {s["id"]: s.get("health", "unknown") for s in data.get("services", [])}


def _registry_snapshot() -> dict[str, str]:
    from raphiia_openai import service_registry

    service_registry.seed_defaults(force=False)
    listed = service_registry.list_services(visible_only=False, limit=200)
    out: dict[str, str] = {}
    for s in listed.get("services", []):
        sid = str(s.get("service_id") or s.get("id") or "")
        if not sid:
            continue
        risk = s.get("risk_level", "")
        if sid in ("ngrok-public-tunnel", "public-gateway", "uipath-copilot"):
            out[sid] = s.get("status", "unknown")
            continue
        if risk not in ("critical", "high") and not sid.startswith(("portal-", "ralfia-")):
            continue
        if s.get("status") == "pending_review":
            continue
        out[str(sid)] = s.get("status", "unknown")
    return out


def _label_for_cockpit(sid: str) -> str:
    from raphiia_openai.service_control import COCKPIT_SERVICES

    for s in COCKPIT_SERVICES:
        if s["id"] == sid:
            return s.get("label", sid)
    return sid


def _send_whatsapp(text: str) -> bool:
    return bool(send_alert_whatsapp(text).get("ok"))


def _log(agent_summary: str, event: str, metadata: dict[str, Any] | None = None) -> None:
    mongo_store.log_coordination(
        agent=AGENT_ID,
        summary=agent_summary,
        event=event,
        project="ralfia-ops",
        metadata=metadata or {},
    )


class ServiceRecoveryAgent(AgentBase):
    agent_id = AGENT_ID
    name = "AG-31 Service Recovery Watchdog"
    risk_level = "medium"
    requires_approval = False

    def capabilities(self) -> list[str]:
        return [
            "run_health_watch",
            "run_post_restart_verify",
            "run_recovery_drill",
            "schedule_post_restart_verify",
        ]

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "run_health_watch":
            return run_health_watch(
                notify=bool(payload.get("notify", True)),
                trigger=str(payload.get("trigger", "mcp")),
            )
        if action == "run_post_restart_verify":
            return run_post_restart_verify(trigger=str(payload.get("trigger", "mcp")))
        if action == "run_recovery_drill":
            return run_recovery_drill(notify=bool(payload.get("notify", True)))
        if action == "schedule_post_restart_verify":
            schedule_post_restart_verify(
                payload.get("restarted"),
                trigger=str(payload.get("trigger", "mcp")),
            )
            return {"ok": True, "scheduled": True}
        return super().execute(action, payload)


service_recovery_agent = ServiceRecoveryAgent()


def run_health_watch(*, notify: bool = True, trigger: str = "periodic") -> dict[str, Any]:
    from raphiia_openai import service_registry

    # Checks frescos en Mongo (incluye ngrok, gateway, uipath)
    try:
        service_registry.run_all_checks()
    except Exception as exc:
        _log(f"run_all_checks error: {exc}"[:200], "health_watch_checks_error")

    # Recuperación ngrok antes de comparar transiciones
    ngrok_recover: dict[str, Any] | None = None
    try:
        from raphiia_openai import ngrok_watch

        ng = ngrok_watch.check_ngrok_tunnel()
        if ng.get("status") not in UP_STATUSES:
            ngrok_recover = ngrok_watch.try_recover_ngrok()
            if ngrok_recover.get("ok"):
                service_registry.run_all_checks()
    except Exception as exc:
        ngrok_recover = {"ok": False, "error": str(exc)[:200]}

    current_cockpit = _cockpit_snapshot()
    current_registry = _registry_snapshot()
    state = _load_state()
    prev_cockpit = state.get("cockpit") or {}
    prev_registry = state.get("registry") or {}
    initialized = state.get("initialized", False)
    transitions: list[dict[str, str]] = []
    whatsapp_sent = 0

    if not initialized:
        state["cockpit"] = current_cockpit
        state["registry"] = current_registry
        state["initialized"] = True
        _save_state(state)
        record_agent_run(
            AGENT_ID,
            action="health_watch_init",
            summary="Baseline cockpit guardado",
            project="ralfia-ops",
            tool_used="run_health_watch",
            metadata={"cockpit": current_cockpit},
        )
        return {
            "ok": all(v in UP_STATUSES for k, v in current_cockpit.items() if k in CRITICAL_IDS),
            "initialized": True,
            "cockpit": current_cockpit,
            "trigger": trigger,
            "agent_id": AGENT_ID,
        }

    for sid, health in current_cockpit.items():
        prev = prev_cockpit.get(sid)
        if prev is None:
            continue
        was_up = prev in UP_STATUSES
        is_up = health in UP_STATUSES
        label = _label_for_cockpit(sid)
        if was_up and not is_up:
            transitions.append({"kind": "down", "scope": "cockpit", "id": sid, "label": label, "status": health})
        elif not was_up and is_up:
            transitions.append({"kind": "recovered", "scope": "cockpit", "id": sid, "label": label, "status": health})

    for sid, status in current_registry.items():
        prev = prev_registry.get(sid)
        if prev is None:
            continue
        was_up = prev in UP_STATUSES
        is_up = status in UP_STATUSES
        if was_up and not is_up:
            transitions.append({"kind": "down", "scope": "registry", "id": sid, "label": sid, "status": status})
        elif not was_up and is_up:
            transitions.append({"kind": "recovered", "scope": "registry", "id": sid, "label": sid, "status": status})

    state["cockpit"] = current_cockpit
    state["registry"] = current_registry
    _save_state(state)

    if notify:
        for tr in transitions:
            if tr["kind"] == "down":
                text = (
                    f"🔴 Ralphi IA — SERVICIO CAÍDO\n"
                    f"{tr['label']} → {tr['status']}\n"
                    f"AG-31 · {trigger}\n"
                    f"{ralfia_time.format_log()}"
                )
            else:
                text = (
                    f"🟢 Ralphi IA — RECUPERADO\n"
                    f"{tr['label']} operativo de nuevo ✅\n"
                    f"AG-31 · {trigger}\n"
                    f"{ralfia_time.format_log()}"
                )
            if _send_whatsapp(text):
                whatsapp_sent += 1

    critical_down = [k for k, v in current_cockpit.items() if k in CRITICAL_IDS and v not in UP_STATUSES]
    registry_down = [k for k, v in current_registry.items() if v not in UP_STATUSES]

    summary = f"Health watch ({trigger}): {len(transitions)} cambios, {whatsapp_sent} WA"
    _log(
        summary,
        "health_watch",
        {
            "trigger": trigger,
            "transitions": transitions,
            "critical_down": critical_down,
            "registry_down": registry_down,
            "ngrok_recover": ngrok_recover,
        },
    )
    record_agent_run(
        AGENT_ID,
        action="health_watch",
        summary=summary,
        project="ralfia-ops",
        tool_used="run_health_watch",
        metadata={"whatsapp_sent": whatsapp_sent, "ok": not critical_down},
    )
    return {
        "ok": not critical_down,
        "agent_id": AGENT_ID,
        "cockpit": current_cockpit,
        "registry": current_registry,
        "transitions": transitions,
        "whatsapp_sent": whatsapp_sent,
        "critical_down": critical_down,
        "trigger": trigger,
    }


def run_post_restart_verify(
    restarted: list[dict[str, Any]] | None = None,
    *,
    trigger: str = "restart",
    max_attempts: int = 6,
    pause_sec: float = 4.0,
) -> dict[str, Any]:
    units = [r.get("unit", "?") for r in (restarted or []) if r.get("unit")]
    unit_txt = ", ".join(u.replace(".service", "") for u in units) if units else "stack Ralphi"

    last: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        if attempt > 1 or pause_sec > 0:
            time.sleep(pause_sec if attempt > 1 else min(pause_sec, 3.0))
        last = run_health_watch(notify=True, trigger=f"{trigger}:intento{attempt}")
        if last.get("ok"):
            summary = (
                f"✅ Ralphi IA — REINICIO OK\n"
                f"AG-31 verificó: {unit_txt}\n"
                f"Intento {attempt}/{max_attempts} — cockpit operativo\n"
                f"{ralfia_time.format_log()}"
            )
            sent = _send_whatsapp(summary)
            _log(f"Post-restart OK: {unit_txt}", "post_restart_ok", {"units": units, "attempt": attempt})
            record_agent_run(
                AGENT_ID,
                action="post_restart_ok",
                summary=f"Reinicio OK — {unit_txt}",
                project="ralfia-ops",
                metadata={"attempt": attempt, "whatsapp": sent},
            )
            return {**last, "post_restart": "ok", "attempts": attempt, "summary_whatsapp": sent}

    down = last.get("critical_down") or []
    still = ", ".join(_label_for_cockpit(x) for x in down) or "revisar panel"
    summary = (
        f"⚠️ Ralphi IA — REINICIO CON PROBLEMAS\n"
        f"AG-31 · {unit_txt}\n"
        f"Siguen caídos: {still}\n"
        f"Vigilancia cada 5 min activa.\n"
        f"{ralfia_time.format_log()}"
    )
    sent = _send_whatsapp(summary)
    _log(f"Post-restart PROBLEMAS: {still}", "post_restart_fail", {"units": units, "down": down})
    record_agent_run(
        AGENT_ID,
        action="post_restart_fail",
        summary=f"Reinicio con problemas — {still}",
        project="ralfia-ops",
        metadata={"down": down, "whatsapp": sent},
    )
    return {**last, "post_restart": "degraded", "attempts": max_attempts, "summary_whatsapp": sent}


def schedule_post_restart_verify(
    restarted: list[dict[str, Any]] | None = None,
    *,
    trigger: str = "restart",
) -> None:
    def _job() -> None:
        try:
            run_post_restart_verify(restarted, trigger=trigger)
        except Exception as exc:
            _log(f"Error post-restart: {exc}"[:200], "post_restart_error")
            record_agent_run(
                AGENT_ID,
                action="post_restart_error",
                summary=str(exc)[:200],
                project="ralfia-ops",
            )

    threading.Thread(target=_job, daemon=True, name="ag31-recovery").start()


def run_recovery_drill(*, notify: bool = True) -> dict[str, Any]:
    """Drill controlado: reinicia stack user Ralphi + verifica + WhatsApp."""
    if notify:
        _send_whatsapp(
            f"🧪 Ralphi IA — DRILL AG-31\n"
            f"Iniciando reinicio controlado del stack Ralphi…\n"
            f"{ralfia_time.format_log()}"
        )
    restarted: list[dict[str, Any]] = []
    for unit, scope in DRILL_UNITS:
        prefix = [] if scope == "system" else ["--user"]
        proc = subprocess.run(
            ["systemctl", *prefix, "restart", unit],
            capture_output=True,
            text=True,
        )
        state = subprocess.run(
            ["systemctl", *prefix, "is-active", unit],
            capture_output=True,
            text=True,
        )
        restarted.append(
            {
                "unit": unit,
                "scope": scope,
                "ok": proc.returncode == 0 and "active" in (state.stdout or ""),
                "state": (state.stdout or "").strip(),
            }
        )
    result = run_post_restart_verify(restarted, trigger="drill_ag31")
    record_agent_run(
        AGENT_ID,
        action="recovery_drill",
        summary=f"Drill completado — {result.get('post_restart', '?')}",
        project="ralfia-ops",
        metadata={"restarted": restarted, "result": result.get("post_restart")},
    )
    return {"ok": result.get("post_restart") == "ok", "agent_id": AGENT_ID, **result}
