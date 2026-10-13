"""GitLab read surfaces via capability_gateway (chatgpt_compact stays at 25 tools)."""

from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import capability_gateway as cg
from inneros_core_runtime import capability_gateway_lep as cgl
from inneros_core_runtime import capability_router as cr
from inneros_core_runtime import mcp_profiles as mp


def test_gitlab_read_capabilities_registered_and_searchable():
    cgl.register_local_execution_capabilities()
    search = cg.capability_search("gitlab", max_results=20)
    assert search["ok"] is True
    ids = {row["capability_id"] for row in search["capabilities"]}
    assert "local_gitlab.get_merge_request.v1" in ids
    assert "local_gitlab.list_merge_request_discussions.v1" in ids
    assert "local_gitlab.list_merge_request_pipelines.v1" in ids
    assert len(ids) >= 5

    describe = cg.capability_describe("local_gitlab.get_merge_request.v1")
    assert describe["ok"] is True
    assert describe["capability"]["mode"] == "read_only"

    alias = cg.capability_describe("local_gitlab_get_merge_request")
    assert alias["ok"] is True


def test_route_mcp_tools_recommends_gitlab_capabilities():
    routed = cr.route_tools(
        title="Inspect GitLab MR read feedback CI gitlab-org/gitlab !257991",
        granted_scopes=["ralfia:read", "ralfia:agents"],
    )
    assert routed["ok"] is True
    rec = {row["capability_id"] for row in routed["recommended_capabilities"]}
    assert "local_gitlab.get_merge_request.v1" in rec

    compact = mp.get_profile("chatgpt_compact")
    assert len(compact["tools"]) == 25
