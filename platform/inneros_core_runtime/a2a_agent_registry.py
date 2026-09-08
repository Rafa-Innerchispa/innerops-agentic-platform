"""A2A Agent Card projection from the canonical InnerOS agent catalog."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_agent_key(value: str) -> str:
    """Normalize A2A/card identifiers while preserving canonical AG-xx ids."""
    raw = (value or "").strip()
    if not raw:
        return ""
    upper = raw.upper().replace("_", "-")
    ag = re.search(r"AG-?0*(\d+)", upper)
    if ag:
        return f"AG-{int(ag.group(1)):02d}"
    text = unicodedata.normalize("NFKD", raw.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    aliases = {
        "inneros-orchestrator": "AG-25",
        "ralfia": "AG-25",
        "ralphi-ia": "AG-25",
        "browser-qa": "AG-55",
        "qwen-coding": "AG-45",
        "codex-repair": "codex-repair",
        "integration-guardian": "integration-guardian",
    }
    return aliases.get(text, text)


def _card_from_catalog(entry: dict[str, Any], protocol_version: str, bridge_version: str) -> dict[str, Any]:
    agent_id = normalize_agent_key(str(entry.get("agent_id") or ""))
    name = str(entry.get("display_name") or entry.get("name") or agent_id)
    role = str(entry.get("role") or entry.get("description") or name)
    domain = str(entry.get("domain") or "platform")
    entry_tool = entry.get("entry_tool") or "invoke_agent"
    task_kind = entry.get("task_kind")
    metadata = {
        "inneros_role": agent_id,
        "agent_id": agent_id,
        "assignee": "ralfia",
        "domain": domain,
        "entry_tool": entry_tool,
        "task_kind": task_kind,
        "mcp_profile": entry.get("mcp_profile"),
        "local_first": True,
        "catalog_source": "inneros_core_runtime.agents.agent_catalog",
    }
    if agent_id == "AG-25":
        metadata.update({"root_orchestrator": True, "assignee": "ralfia"})
    return {
        "name": name,
        "description": role,
        "url": f"inneros://a2a/{agent_id.lower()}",
        "version": bridge_version,
        "protocolVersion": protocol_version,
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{"id": agent_id, "name": name, "description": role}],
        "metadata": metadata,
    }


def _catalog_cards(protocol_version: str, bridge_version: str) -> dict[str, dict[str, Any]]:
    try:
        from inneros_core_runtime.agents.agent_catalog import get_agent_catalog
        result = get_agent_catalog(functional_only=False)
        entries = result.get("agents") if isinstance(result, dict) else []
    except Exception:
        entries = []
    cards: dict[str, dict[str, Any]] = {}
    for entry in entries or []:
        agent_id = normalize_agent_key(str(entry.get("agent_id") or ""))
        if agent_id:
            cards[agent_id] = _card_from_catalog(entry, protocol_version, bridge_version)
    return cards


def merged_agent_cards(base_cards: dict[str, dict[str, Any]], protocol_version: str, bridge_version: str) -> dict[str, dict[str, Any]]:
    """Return base bridge cards plus the canonical AG catalog as A2A cards."""
    merged = _catalog_cards(protocol_version, bridge_version)
    for key, card in (base_cards or {}).items():
        canonical = normalize_agent_key(str((card.get("metadata") or {}).get("agent_id") or key)) or normalize_agent_key(key)
        if canonical in merged:
            existing = dict(merged[canonical])
            existing_meta = dict(existing.get("metadata") or {})
            existing_meta.update(card.get("metadata") or {})
            existing.update(card)
            existing["metadata"] = existing_meta
            merged[canonical] = existing
        else:
            merged[canonical] = card
    return dict(sorted(merged.items(), key=lambda item: (0 if re.match(r"AG-\d+", item[0]) else 1, item[0])))
