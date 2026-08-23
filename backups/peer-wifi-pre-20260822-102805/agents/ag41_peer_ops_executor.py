"""AG-41 Peer Ops Executor — mutaciones allowlisted en nodos .4/.5 vía MCP."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.notifications import whatsapp_service_ops

AGENT_ID = "AG-41_PEER_OPS_EXECUTOR"

ALLOWLIST_SERVICES = tuple(sorted(whatsapp_service_ops.SERVICE_BY_ID.keys()))
ALLOWLIST_ACTIONS = frozenset({"start", "restart", "recover"})
# Servicios que normalmente corren solo en Intel — down en AMD no es incidente
INTEL_ONLY_SERVICES = frozenset({"portal", "app", "whatsapp"})


def _annotate_warm_standby(snap: dict[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    for item in snap.get("items") or []:
        if item.get("node") == "amd" and item.get("service_id") in INTEL_ONLY_SERVICES and not item.get("healthy"):
            item["warm_standby"] = True
            item["note"] = "Intel-only en warm-standby; down en AMD es esperado"
            notes.append(item.get("service_id", ""))
    if notes:
        snap["warm_standby_amd"] = {
            "intel_only_down_expected": notes,
            "note": "Failover --execute levantaría estos servicios en .5",
        }
    return snap


def list_peer_ops_services() -> dict[str, Any]:
    services = []
    for sid, spec in whatsapp_service_ops.SERVICE_BY_ID.items():
        services.append({
            "service_id": sid,
            "label": spec.label,
            "kind": spec.kind,
            "aliases": list(spec.aliases),
        })
    return {"ok": True, "agent_id": AGENT_ID, "services": services}


def peer_ops_snapshot(node: str | None = None) -> dict[str, Any]:
    snap = whatsapp_service_ops.status_snapshot(node)
    snap = _annotate_warm_standby(snap)
    unhealthy = [
        i for i in (snap.get("items") or [])
        if i.get("ok") and not i.get("healthy") and not i.get("warm_standby")
    ]
    snap["ok"] = len(unhealthy) == 0
    record_agent_run(AGENT_ID, action="peer_ops_snapshot", summary=f"nodes={snap.get('nodes')} ok={snap['ok']}", project="ralfia-ops")
    return {"ok": snap["ok"], "agent_id": AGENT_ID, **snap}


def peer_ops_status(service_id: str, node: str = "primary") -> dict[str, Any]:
    result = whatsapp_service_ops.service_status(service_id, node)
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}


def peer_ops_action(
    service_id: str,
    node: str = "primary",
    action: str = "restart",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    action = (action or "restart").strip().lower()
    if action not in ALLOWLIST_ACTIONS:
        return {"ok": False, "error": "action_not_allowlisted", "allowed": sorted(ALLOWLIST_ACTIONS)}
    if service_id not in whatsapp_service_ops.SERVICE_BY_ID:
        return {"ok": False, "error": "service_not_allowlisted", "allowed": ALLOWLIST_SERVICES}
    if dry_run:
        before = whatsapp_service_ops.service_status(service_id, node)
        return {
            "ok": True,
            "dry_run": True,
            "agent_id": AGENT_ID,
            "would_execute": {"service_id": service_id, "node": node, "action": action},
            "current": before,
        }
    result = whatsapp_service_ops.execute_service_action(service_id, node, action)
    record_agent_run(
        AGENT_ID,
        action="peer_ops_action",
        summary=f"{service_id}@{node} {action} ok={result.get('ok')}",
        project="ralfia-ops",
        metadata={"service_id": service_id, "node": node, "action": action},
    )
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, **result}


def peer_ops_logs(service_id: str, node: str = "primary", lines: int = 30) -> dict[str, Any]:
    result = whatsapp_service_ops.recent_logs(service_id, node, lines=max(1, min(lines, 50)))
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}
