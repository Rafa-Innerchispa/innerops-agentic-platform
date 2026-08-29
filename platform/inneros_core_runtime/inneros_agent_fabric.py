"""Unified InnerOS agent fabric — MCP + ACP + IDE bridge + KPI (one stack)."""
from __future__ import annotations

from typing import Any

from inneros_core_runtime import ide_task_bridge, kpi_telemetry
from inneros_core_runtime.agents import ag58_acp_deliverable_tracker as ag58


def fabric_status(*, ops_task_id: str = "") -> dict[str, Any]:
    """Single harmonized status surface for coordination agents."""
    acp = ag58.deliverable_status(ops_task_id=ops_task_id or "ops_608d9780a8dd")
    return {
        "ok": True,
        "fabric_version": "inneros_agent_fabric_v1",
        "layers": {
            "mcp_inbox": {"ok": True, "transport": "create_agent_message"},
            "ide_task_bridge": {
                "ok": True,
                "version": ide_task_bridge.BRIDGE_VERSION,
                "targets": list(ide_task_bridge.SUPPORTED_TARGETS),
            },
            "acp": acp,
            "a2a_projection": {"ok": True, "module": "google_adk_a2a.project_ide_task_bridge"},
        },
        "integration_note": "Layers complement each other; none replace MCP coordination.",
        "blockers": acp.get("blockers") or [],
        "status": acp.get("status", "PARTIAL"),
    }


def harmonized_dispatch(
    *,
    title: str,
    body: str,
    target: str,
    correlation_id: str = "",
    ops_task_id: str = "",
    dry_run: bool = True,
    store: ide_task_bridge.DispatchStore | None = None,
) -> dict[str, Any]:
    """Dispatch via IDE bridge and attach ACP + KPI correlation."""
    dispatch = ide_task_bridge.dispatch_ide_task(
        title=title,
        body=body,
        target=target,
        correlation_id=correlation_id or ag58.CORRELATION_ID,
        ops_task_id=ops_task_id,
        dry_run=dry_run,
        store=store,
    )
    if not dispatch.get("ok"):
        return dispatch

    correlated = ag58.correlate_a2a_acp(
        a2a_status={
            "status": {"state": "submitted"},
            "correlation_id": dispatch["correlation_id"],
        },
        ops_status="proposed",
        target=dispatch["target"],
    )
    kpi = kpi_telemetry.record_task_kpi(
        task_id=ops_task_id or "dispatch",
        agent=dispatch["target"],
        outcome="delivered" if dispatch.get("delivered_to_inbox") else "PARTIAL",
        correlation_id=dispatch["correlation_id"],
        task_type="ide_dispatch",
        estimated_manual_minutes=5.0,
        human_minutes_spent=0.0,
        energy_source="UNAVAILABLE",
    )
    return {
        "ok": True,
        "fabric_version": "inneros_agent_fabric_v1",
        "dispatch": dispatch,
        "acp_correlation": correlated,
        "kpi": kpi,
    }
