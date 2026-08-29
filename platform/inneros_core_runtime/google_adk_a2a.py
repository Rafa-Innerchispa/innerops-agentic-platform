"""Google ADK RemoteA2aAgent / sub-agent contract over InnerOS A2A.

Reuses the existing A2A Agent Cards and RACB bridge. This module does not
duplicate the IDE Task Bridge; it consumes the same A2A dispatch/status
contract so ADK, A2A JSON-RPC and IDE inbox share one lifecycle.

All paths here are NON-LIVE unless a later LIVE Gemini/Vertex invocation
attaches live_mode="LIVE" evidence under the same correlation_id.
"""
from __future__ import annotations

from typing import Any

from inneros_core_runtime import a2a_bridge
from inneros_core_runtime.tracking_envelope import build_envelope

ADK_PATTERN = "RemoteA2aAgent"
LIVE_MODE = "NON-LIVE"
GEMINI_REMOTE_AGENT_ID = "google-gemini"
IDE_TARGETS = ("antigravity", "cursor", "codex", "gemini")

IDE_DELIVERY_STATES = frozenset({"submitted", "proposed", "pending"})
IDE_CLAIMED_STATES = frozenset({"accepted", "dispatched"})
IDE_RUNNING_STATES = frozenset({"in_progress", "working", "verification"})
IDE_TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "cancelled", "rejected", "superseded"})


def _card_to_remote_spec(agent_id: str, card: dict[str, Any]) -> dict[str, Any]:
    metadata = card.get("metadata") or {}
    url = str(card.get("url") or f"inneros://a2a/{agent_id}")
    return {
        "adk_class": ADK_PATTERN,
        "agent_id": agent_id,
        "name": card.get("name"),
        "description": card.get("description"),
        "agent_card_url": url if url.endswith("agent-card.json") else f"{url}/.well-known/agent-card.json",
        "rpc_url": url.replace("inneros://a2a/", "/a2a/"),
        "protocol_version": card.get("protocolVersion") or a2a_bridge.A2A_PROTOCOL_VERSION,
        "capabilities": card.get("capabilities") or {},
        "skills": card.get("skills") or [],
        "metadata": {
            **metadata,
            "adk_pattern": ADK_PATTERN,
            "sub_agent": True,
            "live_mode": LIVE_MODE,
        },
        "live_mode": LIVE_MODE,
    }


def adk_sdk_status() -> dict[str, Any]:
    try:
        import google.adk.agents as adk_agents  # type: ignore

        exports = [name for name in dir(adk_agents) if not name.startswith("_")]
        return {
            "ok": True,
            "sdk": "google-adk",
            "exports": exports[:12],
            "note": "RemoteA2aAgent contract mapped via InnerOS A2A bridge.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "sdk": "google-adk",
            "error": type(exc).__name__,
            "note": "Contract-only ADK path active via InnerOS A2A bridge.",
        }


def adk_live_status() -> dict[str, Any]:
    catalog = remote_a2a_agents()
    sdk = adk_sdk_status()
    sub_agents = catalog.get("sub_agents") or {}
    contract_ok = bool(
        catalog.get("ok")
        and catalog.get("count", 0) > 0
        and all(spec.get("adk_class") == ADK_PATTERN for spec in sub_agents.values())
    )
    return {
        "ok": contract_ok,
        "contract_ok": contract_ok,
        "sdk_installed": bool(sdk.get("ok")),
        "sdk": sdk,
        "sub_agent_count": catalog.get("count"),
        "live_mode": "CONTRACT_LIVE" if contract_ok else LIVE_MODE,
    }


def google_gemini_remote_card() -> dict[str, Any]:
    """ADK remote card for Gemini/Vertex."""
    try:
        from inneros_core_runtime import gemini_runtime as gr

        model = gr.GeminiRuntimeConfig.from_env().model
        live_mode = "LIVE"
        quota_blocked = False
        description = "Google-native intelligence plane via governed InnerOS Gemini runtime."
    except Exception:
        model = "gemini-2.5-flash"
        live_mode = LIVE_MODE
        quota_blocked = True
        description = "Google-native intelligence plane via governed InnerOS Gemini runtime. NON-LIVE until runtime configured."
    return {
        "name": "Google Gemini (Vertex)",
        "description": description,
        "version": a2a_bridge.BRIDGE_VERSION,
        "protocolVersion": a2a_bridge.A2A_PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": "google-gemini", "name": "Google Gemini", "description": "Governed Gemini/Vertex provider behind InnerOS."}],
        "metadata": {
            "inneros_role": "google-gemini",
            "assignee": "gemini",
            "provider": "google-gemini-vertex",
            "model": model,
            "adk_pattern": ADK_PATTERN,
            "quota_blocked": quota_blocked,
            "live_mode": live_mode,
        },
    }


def remote_a2a_agents() -> dict[str, Any]:
    """Map InnerOS fabric cards to ADK RemoteA2aAgent sub-agent specs."""
    cards = dict(a2a_bridge.AGENT_CARDS)
    cards[GEMINI_REMOTE_AGENT_ID] = google_gemini_remote_card()
    specs = {agent_id: _card_to_remote_spec(agent_id, card) for agent_id, card in cards.items()}
    return {
        "ok": True,
        "adk_pattern": ADK_PATTERN,
        "live_mode": LIVE_MODE,
        "root_orchestrator": "inneros-orchestrator",
        "sub_agents": specs,
        "count": len(specs),
        "note": "SDK import of google.adk.agents.RemoteA2aAgent is LIVE-pending; this is the contract RemoteA2aAgent consumes.",
    }


def project_ide_task_bridge(
    *,
    a2a_status: dict[str, Any] | None = None,
    ops_status: str = "",
    target: str = "cursor",
) -> dict[str, Any]:
    """Compatibility projection for the existing IDE Task Bridge.

    Delivery (inbox) is never treated as execution. This does not create a
    second dispatcher; it only maps A2A/RACB state into the IDE contract.
    """
    target_id = (target or "").strip().lower()
    if target_id not in IDE_TARGETS:
        return {"ok": False, "error": "unsupported_ide", "target": target, "supported": list(IDE_TARGETS)}

    a2a_state = ""
    if a2a_status:
        a2a_state = str((a2a_status.get("status") or {}).get("state") or a2a_status.get("state") or "")
    ops = (ops_status or str((a2a_status or {}).get("ops_status") or "")).strip().lower()
    combined = {a2a_state.lower(), ops}

    delivered = bool(a2a_status) or bool(ops)
    claimed = bool(combined & IDE_CLAIMED_STATES)
    running = bool(combined & IDE_RUNNING_STATES)
    terminal = bool(combined & IDE_TERMINAL_STATES)
    completed = "completed" in combined and not (a2a_status or {}).get("integrity_error")

    execution_state = "queued"
    if completed:
        execution_state = "completed"
    elif terminal:
        execution_state = "failed" if "failed" in combined else "canceled"
    elif running:
        execution_state = "running"
    elif claimed:
        execution_state = "claimed"
    elif delivered:
        execution_state = "delivered_to_inbox"

    return {
        "ok": True,
        "target": target_id,
        "transport": "a2a|ide_inbox",
        "delivered_to_inbox": delivered,
        "claimed": claimed or running or terminal,
        "running": running,
        "completed": completed,
        "execution_state": execution_state,
        "a2a_state": a2a_state,
        "ops_status": ops,
        "live_mode": LIVE_MODE,
        "duplicates_ide_bridge": False,
    }


def dispatch_remote_sub_agent(
    bridge: a2a_bridge.A2ABridge,
    *,
    agent_id: str,
    title: str,
    body: str,
    envelope: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Dispatch through the existing A2A bridge (no second lifecycle)."""
    agents = remote_a2a_agents()["sub_agents"]
    if agent_id == GEMINI_REMOTE_AGENT_ID:
        card = google_gemini_remote_card()
        if card.get("metadata", {}).get("quota_blocked"):
            return {
                "ok": False,
                "error": "gemini_quota_blocked",
                "live_mode": LIVE_MODE,
                "agent_id": agent_id,
                "note": "Gemini RemoteA2aAgent remains NON-LIVE until quota recovers. Do not report LIVE PASS.",
            }
    if agent_id not in a2a_bridge.AGENT_CARDS:
        return {"ok": False, "error": "unknown_a2a_agent", "agent_id": agent_id, "known": sorted(agents)}

    tracking = envelope or build_envelope(
        agent=agent_id,
        provider="inneros-a2a",
        simulated=True,
        quota_blocked=False,
        original_task_id="ops_365cfb128303",
        takeover_task_id="ops_8a6159731402",
        extra={"adk_pattern": ADK_PATTERN},
    )
    result = bridge.dispatch(
        agent_id=agent_id,
        title=title,
        body=body,
        correlation_id=str(tracking.get("correlation_id") or ""),
        context_id=str(tracking.get("context_id") or ""),
        dry_run=dry_run,
        envelope=tracking,
        traceparent=str(tracking.get("traceparent") or ""),
    )
    projection = project_ide_task_bridge(
        a2a_status=result,
        ops_status="proposed" if result.get("ok") and not dry_run else "",
        target="cursor",
    )
    return {
        **result,
        "adk_pattern": ADK_PATTERN,
        "envelope": tracking,
        "ide_task_bridge": projection,
        "live_mode": LIVE_MODE,
    }
