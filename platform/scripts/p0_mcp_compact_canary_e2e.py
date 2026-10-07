#!/usr/bin/env python3
"""Lane A canary: compact 25 tools + capability LEP/runtime + infralens registry."""

from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def offline_checks() -> dict:
    from inneros_core_runtime import capability_gateway as cg
    from inneros_core_runtime import local_execution_plane as lep
    from inneros_core_runtime import project_runtime_registry as prr
    from inneros_core_runtime import mcp_profiles

    profile = mcp_profiles.get_profile("chatgpt_compact")
    lep_search = cg.capability_search("local execution", max_results=15)
    rt_search = cg.capability_search("project runtime", max_results=10)
    peer_search = cg.capability_search("peer observability", max_results=10)
    resolve = prr.resolve_project(project_id="infralens-ocr-amd", node="amd")
    scope = lep.dev_swarm_scope_status(repo="Rafa-Innerchispa/infralens-ocr-amd")
    bootstrap = prr.bootstrap_runtime(
        node="amd",
        project_id="infralens-ocr-amd",
        dry_run=True,
        actor="p0_canary",
        task_id="ops_lane_a_canary",
        correlation_id="p0-mcp-compact-canary-20261006",
    )
    lep_ids = {c["capability_id"] for c in lep_search.get("capabilities") or []}
    rt_ids = {c["capability_id"] for c in rt_search.get("capabilities") or []}
    peer_ids = {c["capability_id"] for c in peer_search.get("capabilities") or []}
    return {
        "ok": (
            profile.get("tool_count") == 25
            and "local_exec.write_file.v1" in lep_ids
            and "local_exec.push_branch.v1" in lep_ids
            and "project_runtime.resolve.v1" in rt_ids
            and "peer.observability_snapshot.v1" in peer_ids
            and resolve.get("ok")
            and scope.get("ok")
            and bootstrap.get("ok")
        ),
        "profile_tool_count": profile.get("tool_count"),
        "lep_capabilities": sorted(lep_ids),
        "runtime_capabilities": sorted(rt_ids),
        "peer_capabilities": sorted(peer_ids),
        "infralens_resolve_ok": resolve.get("ok"),
        "infralens_scope_ok": scope.get("ok"),
        "infralens_bootstrap_ok": bootstrap.get("ok"),
    }


async def live_tools(url: str, api_key: str) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"X-API-Key": api_key}
    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            caps = getattr(getattr(init, "capabilities", None), "tools", None)
            list_changed = bool(getattr(caps, "listChanged", False))
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            need = {
                "capability_search",
                "capability_invoke",
                "project_runtime_bootstrap",
                "dev_swarm_scope_status",
            }
            return {
                "ok": len(names) == 25 and need.issubset(names) and list_changed,
                "listed": len(names),
                "list_changed": list_changed,
                "missing": sorted(need - names),
            }


def main() -> int:
    out = {"offline": offline_checks()}
    url = os.getenv("COORD_E2E_MCP_URL", "http://127.0.0.1:8112/mcp").strip()
    key = os.getenv("MCP_API_KEY", "").strip()
    if key:
        try:
            out["live"] = asyncio.run(live_tools(url, key))
        except Exception as exc:
            out["live"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    else:
        out["live"] = {"ok": True, "skipped": True}
    out["ok"] = bool(out["offline"].get("ok")) and (
        out.get("live", {}).get("skipped") or out.get("live", {}).get("ok")
    )
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
