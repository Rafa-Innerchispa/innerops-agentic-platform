"""Agents registry and runtime helpers."""

from raphiia_openai.agents.registry import MAP_FILES, get_agent, list_agents, list_project_bindings, seed_mongo_registry

RALPHIA_AGENTS = {agent["agent_id"]: agent for agent in list_agents()}

__all__ = [
    "RALPHIA_AGENTS",
    "MAP_FILES",
    "list_agents",
    "get_agent",
    "list_project_bindings",
    "seed_mongo_registry",
]
