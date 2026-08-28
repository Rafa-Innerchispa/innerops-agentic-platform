"""AG-30 WhatsApp — Evolution API (delegado desde MCP)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agents.base import AgentBase
from raphiia_openai.notifications.evolution_client import connection_open, dual_whatsapp_status, send_whatsapp


class WhatsAppAgent(AgentBase):
    agent_id = "AG-30_WHATSAPP"
    name = "WhatsApp Evolution Agent"

    def capabilities(self) -> list[str]:
        return [
            "send_whatsapp_draft",
            "send_whatsapp_message",
            "get_whatsapp_status",
        ]

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "get_whatsapp_status":
            if payload.get("dual") or payload.get("all_nodes"):
                return {"ok": True, "lines": dual_whatsapp_status()}
            node = payload.get("node")
            return {"ok": True, "connected": connection_open(node=node), "node": node or "primary"}
        if action in ("send_whatsapp_message", "send_whatsapp_draft"):
            if payload.get("requires_approval") and not payload.get("approved_by"):
                return {"ok": False, "error": "approval_required", "status": "pending_approval"}
            text = payload.get("message") or payload.get("text") or ""
            number = payload.get("number") or payload.get("recipient")
            node = payload.get("node")
            return send_whatsapp(text, number=number, node=node)
        return super().execute(action, payload)


whatsapp_agent = WhatsAppAgent()
