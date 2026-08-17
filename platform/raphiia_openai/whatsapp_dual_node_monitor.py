"""Highly available dual-node monitor with transition alerts and failover delivery."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from raphiia_openai import mongo_store, ralfia_time, whatsapp_identity, whatsapp_service_ops
from raphiia_openai.notifications.evolution_client import send_whatsapp
from raphiia_openai.notifications.settings import NOTIFY_WHATSAPP_TO, WHATSAPP_AMD_SEND_ENABLED

STATE_COLLECTION = "ralfia_dual_node_monitor_state"
LEASE_COLLECTION = "ralfia_dual_node_monitor_lease"
AUDIT_COLLECTION = "ralfia_dual_node_monitor_audit"
LEASE_SECONDS = 75
FAILURES_BEFORE_ALERT = 2
PERSISTENT_REMINDER_SECONDS = 1800


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def monitor_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire_lease(holder: str | None = None) -> bool:
    holder = holder or monitor_id()
    db = mongo_store.get_db()
    now = _now()
    current = db[LEASE_COLLECTION].find_one({"_id": "dual-node-leader"})
    if current and current.get("holder") != holder and str(current.get("expires_at") or "") > now:
        return False
    db[LEASE_COLLECTION].update_one(
        {"_id": "dual-node-leader"},
        {
            "$set": {
                "holder": holder,
                "heartbeat_at": now,
                "expires_at": (_now_dt() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            }
        },
        upsert=True,
    )
    return True


def _probe_snapshot() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    snapshot = whatsapp_service_ops.status_snapshot()
    reachable_by_node: dict[str, bool] = {}
    for node in ("primary", "amd"):
        reachable = whatsapp_service_ops.node_reachable(node)
        reachable_by_node[node] = reachable
        output[f"node:{node}"] = {
            "healthy": reachable,
            "node": node,
            "label": f"Servidor {whatsapp_service_ops.NODE_LABELS[node]}",
            "state": "reachable" if reachable else "unreachable",
        }
    for item in snapshot.get("items", []):
        # Si un nodo completo cayó, una sola alerta de nodo evita una tormenta de
        # alertas por cada servicio. Si solo falta telemetría SSH, tampoco se
        # interpreta como caída sin una prueba externa concluyente.
        if not reachable_by_node.get(str(item.get("node")), False) or not item.get("ok"):
            continue
        key = f"service:{item.get('node')}:{item.get('service_id')}"
        output[key] = {
            "healthy": bool(item.get("healthy")),
            "node": item.get("node"),
            "label": f"{item.get('label')} {item.get('node_label')}",
            "state": f"{item.get('system_state')} / {item.get('health')}",
            "service_id": item.get("service_id"),
        }
    return output


def _destinations() -> list[str]:
    configured = whatsapp_identity.notification_destinations()
    if configured:
        return configured
    fallback = "".join(char for char in str(NOTIFY_WHATSAPP_TO or "") if char.isdigit())
    return [fallback] if fallback else []


def _send_failover(text: str, destination: str, affected_node: str) -> bool:
    preferred = "amd" if affected_node == "primary" else "primary"
    secondary = "primary" if preferred == "amd" else "amd"
    if preferred == "amd" and not WHATSAPP_AMD_SEND_ENABLED:
        return bool(send_whatsapp(text, number=destination, node="primary").get("ok"))
    first = send_whatsapp(text, number=destination, node=preferred)
    if first.get("ok"):
        return True
    if secondary == "amd" and not WHATSAPP_AMD_SEND_ENABLED:
        return False
    return bool(send_whatsapp(text, number=destination, node=secondary).get("ok"))


def _should_remind(last_alert_at: str | None) -> bool:
    if not last_alert_at:
        return True
    try:
        previous = datetime.fromisoformat(last_alert_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    return (_now_dt() - previous).total_seconds() >= PERSISTENT_REMINDER_SECONDS


def run_monitor_cycle(
    *,
    holder: str | None = None,
    notify: bool = True,
    require_leader: bool = True,
    probe: Callable[[], dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    holder = holder or monitor_id()
    if require_leader and not acquire_lease(holder):
        return {"ok": True, "leader": False, "holder": holder, "status": "standby"}
    db = mongo_store.get_db()
    current = (probe or _probe_snapshot)()
    transitions: list[dict[str, Any]] = []
    reminders: list[dict[str, Any]] = []
    sent = 0
    for probe_id, value in current.items():
        previous = db[STATE_COLLECTION].find_one({"_id": probe_id}) or {}
        healthy = bool(value.get("healthy"))
        failures = 0 if healthy else int(previous.get("consecutive_failures") or 0) + 1
        alerted_down = bool(previous.get("alerted_down"))
        transition: str | None = None
        if not healthy and failures >= FAILURES_BEFORE_ALERT and not alerted_down:
            transition = "down"
            alerted_down = True
        elif healthy and alerted_down:
            transition = "recovered"
            alerted_down = False
        elif not healthy and alerted_down and _should_remind(previous.get("last_alert_at")):
            reminders.append({"kind": "persistent_down", "probe_id": probe_id, **value})
        patch = {
            **value,
            "consecutive_failures": failures,
            "alerted_down": alerted_down,
            "last_check_at": _now(),
        }
        if transition:
            event = {"kind": transition, "probe_id": probe_id, **value}
            transitions.append(event)
            patch["last_alert_at"] = _now()
        elif reminders and reminders[-1].get("probe_id") == probe_id:
            patch["last_alert_at"] = _now()
        db[STATE_COLLECTION].update_one({"_id": probe_id}, {"$set": patch}, upsert=True)

    events = transitions + reminders
    if notify:
        destinations = _destinations()
        for event in events:
            kind = event["kind"]
            if kind == "recovered":
                text = (
                    f"🟢 RalfIA — RECUPERADO\n{event.get('label')} volvió a estar operativo.\n"
                    f"Estado: {event.get('state')}\n{ralfia_time.format_log()}"
                )
            elif kind == "persistent_down":
                text = (
                    f"🟠 RalfIA — FALLA PERSISTENTE\n{event.get('label')} continúa caído.\n"
                    f"Estado: {event.get('state')}\nPuedes consultar: “estado del servidor {whatsapp_service_ops.NODE_LABELS.get(str(event.get('node')), '')}”."
                )
            else:
                text = (
                    f"🔴 RalfIA — ALERTA DE SERVICIO\n{event.get('label')} dejó de responder.\n"
                    f"Estado: {event.get('state')}\nPuedes pedir diagnóstico o recuperación segura.\n{ralfia_time.format_log()}"
                )
            for destination in destinations:
                sent += int(_send_failover(text, destination, str(event.get("node") or "primary")))
            db[AUDIT_COLLECTION].insert_one(
                {
                    "event": kind,
                    "probe_id": event.get("probe_id"),
                    "node": event.get("node"),
                    "service_id": event.get("service_id"),
                    "state": event.get("state"),
                    "destinations": len(destinations),
                    "sent": sent,
                    "at": _now(),
                    "holder": holder,
                }
            )
    mongo_store.log_coordination(
        agent="DUAL_NODE_MONITOR",
        summary=f"Dual-node: {len(current)} probes, {len(transitions)} transitions, {sent} alertas",
        event="dual_node_health_watch",
        project="ralfia-ops",
        metadata={
            "holder": holder,
            "transition_count": len(transitions),
            "reminder_count": len(reminders),
            "sent": sent,
        },
    )
    return {
        "ok": not any(not item.get("healthy") for item in current.values()),
        "leader": True,
        "holder": holder,
        "probe_count": len(current),
        "transitions": transitions,
        "reminders": reminders,
        "whatsapp_sent": sent,
        "snapshot": current,
    }
