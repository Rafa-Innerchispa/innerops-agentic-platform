"""Dynamic A2A Agent Card projection from the canonical InnerOS agent catalog."""
from __future__ import annotations

from typing import Any


def _slug_skill(agent: dict[str, Any]) -> str:
    return str(agent.get("task_kind") or agent.get("domain") or "agent").strip().lower().replace(" ", "_")


def _catalog_snapshot() -> tuple[list[dict[str, Any]], str]:
    """Prefer runtime-verified agents without making A2A depend on every optional import."""
    try:
        from raphiia_openai.agents import agent_catalog
    except Exception:
        return [], "catalog_unavailable"
    try:
        verified = agent_catalog.get_agent_catalog(functional_only=True)
        return list(verified.get("agents") or []), "runtime_verified"
    except Exception:
        # Fail soft: A2A discovery itself must stay available if an optional
        # runner dependency is temporarily unavailable. Dispatch still goes
        # through the runner registry and fails closed for an unusable target.
        items: list[dict[str, Any]] = []
        for agent_id, meta in sorted(agent_catalog.AGENT_CATALOG.items()):
            if str(meta.get("status") or "").lower() != "functional":
                continue
            items.append({
                "agent_id": agent_id,
                "display_name": meta.get("display_name"),
                "role": meta.get("role"),
                "entry_tool": meta.get("entry_tool"),
                "task_kind": meta.get("task_kind"),
                "mcp_profile": meta.get("mcp_profile"),
                "domain": meta.get("domain"),
            })
        return items, "catalog_fallback"


def catalog_agent_cards(protocol_version: str = "1.0", bridge_version: str = "1.0.0") -> dict[str, dict[str, Any]]:
    """Return one discoverable A2A card for every functional InnerOS agent."""
    agents, verification = _catalog_snapshot()
    cards: dict[str, dict[str, Any]] = {}
    for agent in agents:
        agent_id = str(agent.get("agent_id") or "").strip().upper()
        if not agent_id:
            continue
        skill_id = _slug_skill(agent)
        cards[agent_id] = {
            "name": str(agent.get("display_name") or agent_id),
            "description": str(agent.get("role") or "InnerOS agent"),
            "url": f"inneros://a2a/{agent_id.lower()}",
            "version": bridge_version,
            "protocolVersion": protocol_version,
            "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [{"id": skill_id, "name": str(agent.get("display_name") or agent_id), "description": str(agent.get("role") or "Execute bounded InnerOS capability")}],
            "metadata": {
                "inneros_role": "root_orchestrator" if agent_id == "AG-25" else "catalog_agent",
                "agent_id": agent_id,
                "domain": agent.get("domain"),
                "entry_tool": agent.get("entry_tool"),
                "task_kind": agent.get("task_kind"),
                "mcp_profile": agent.get("mcp_profile"),
                "assignee": "ralfia",
                "runnable": verification == "runtime_verified",
                "runtime_verification": verification,
                "local_first": True,
                "root_orchestrator": agent_id == "AG-25",
            },
        }
    return cards


def merged_agent_cards(static_cards: dict[str, dict[str, Any]], protocol_version: str, bridge_version: str) -> dict[str, dict[str, Any]]:
    cards = dict(static_cards)
    cards.update(catalog_agent_cards(protocol_version, bridge_version))
    return cards


def normalize_agent_key(agent_id: str) -> str:
    value = str(agent_id or "").strip()
    if value.upper().startswith("AG-"):
        return value.upper()
    return value.lower()
