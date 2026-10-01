#!/usr/bin/env python3
"""Runtime canary (Lane A): MCP compact scopes + Temporal heartbeat (local MCP optional).

Usage (AMD/Intel with MCP profile on :8112):
  export MCP_API_KEY=...
  export COORD_E2E_MCP_URL=http://127.0.0.1:8112/mcp
  PYTHONPATH=. python scripts/p0_lane_a_runtime_canary.py

Full-tool E2E (heartbeat/update_ops_task_state on catalog) requires full MCP (:8102), not chatgpt_compact.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import patch

from inneros_core_runtime import auth_middleware as am
from inneros_core_runtime import coordination_live
from inneros_core_runtime import durable_coordination_spine as spine
from inneros_core_runtime import mcp_diagnostics
from inneros_core_runtime import mcp_profiles


def offline_canary() -> dict:
    token = {
        "scope": "ralfia:read ralfia:write",
        "mcp_profile": "chatgpt_compact",
        "resource": "https://mcp.pcdoctor.ai/router/mcp",
    }
    scopes = am._effective_token_scopes(token, "dev_swarm_launch_task", {})
    profile = mcp_profiles.get_profile("chatgpt_compact")
    with patch.object(
        mcp_diagnostics.mongo_store,
        "get_coordination_state",
        return_value={"ok": False, "state": {}},
    ):
        diag = mcp_diagnostics.diagnose_mcp_session(
            client_tool_count=len(profile["tools"]),
            client_seen_tools=profile["tools"],
            profile="chatgpt_compact",
            session_id="lane-a-runtime-offline",
        )
    with patch.object(
        spine,
        "signal_task_workflow",
        return_value={"ok": True, "backend": "temporal", "task_id": "ops_lane_a_canary"},
    ):
        hb = coordination_live.heartbeat_ops_task(
            "ops_lane_a_canary",
            "dev_swarm",
            next_action="verification",
        )
    return {
        "ok": "ralfia:agents" in scopes and diag.get("stale_catalog") is False and hb.get("ok"),
        "effective_scopes_dev_swarm": sorted(scopes),
        "diagnose": {
            "stale_catalog": diag.get("stale_catalog"),
            "expected_tool_count": diag.get("expected_tool_count"),
            "this_client_sees_tools": diag.get("this_client_sees_tools"),
        },
        "heartbeat_authority": hb.get("authority"),
    }


async def mcp_compact_probe() -> dict:
    url = os.getenv("COORD_E2E_MCP_URL", "").strip()
    if not url:
        return {"ok": True, "skipped": True, "reason": "COORD_E2E_MCP_URL unset"}
    api_key = os.getenv("MCP_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "MCP_API_KEY required for live probe"}

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"X-API-Key": api_key}
    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            need = {"poll_agent_inbox", "dev_swarm_launch_task", "diagnose_mcp_session", "capability_invoke"}
            missing = sorted(need - names)
            ctx = am.resolve_bearer_auth_context({"X-API-Key": api_key})
            return {
                "ok": not missing,
                "mcp_url": url,
                "tool_count": len(names),
                "missing_compact_tools": missing,
                "auth_context_ok": ctx.get("ok"),
            }


def main() -> int:
    out = {"offline": offline_canary()}
    try:
        out["live_compact"] = asyncio.run(mcp_compact_probe())
    except Exception as exc:
        out["live_compact"] = {"ok": False, "error": str(exc)}
    out["ok"] = bool(out["offline"].get("ok")) and (
        out.get("live_compact", {}).get("skipped") or out.get("live_compact", {}).get("ok")
    )
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
