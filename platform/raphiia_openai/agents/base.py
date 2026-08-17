"""Base agent — MCP delega aquí, no lógica directa en tools."""

from __future__ import annotations

from typing import Any


class AgentBase:
    agent_id: str = "base"
    name: str = "Base Agent"
    risk_level: str = "medium"
    requires_approval: bool = True

    def capabilities(self) -> list[str]:
        return []

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": "not_implemented", "agent": self.agent_id, "action": action}
