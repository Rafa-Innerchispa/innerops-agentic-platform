"""AG-35 Ecosystem Pulse — pulso flota MCP + stack local."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-35_ECOSYSTEM_PULSE"


def run_ecosystem_pulse() -> dict[str, Any]:
    from raphiia_openai import mcp_fleet, mongo_store

    fleet = mcp_fleet.fleet_status(force_probe=False)
    mongo = mongo_store.ping_mongo()
    record_agent_run(AGENT_ID, action="ecosystem_pulse", summary="pulse", project="ralfia-ops")
    return {
        "ok": bool(mongo.get("ok")),
        "agent_id": AGENT_ID,
        "mongo": mongo,
        "fleet": fleet,
        "local_only": True,
    }
