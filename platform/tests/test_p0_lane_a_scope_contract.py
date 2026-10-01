"""Carril A — catálogo vs tools visibles vs scopes efectivos del token (offline)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from inneros_core_runtime import auth_middleware as am
from inneros_core_runtime import mcp_diagnostics
from inneros_core_runtime import mcp_profiles
from inneros_core_runtime.oauth_metadata import build_oauth_www_authenticate, protected_resource_metadata


class EffectiveScopeContractTests(unittest.TestCase):
    def test_compact_read_write_expands_agents_for_orchestration_tools(self) -> None:
        token = {
            "scope": "ralfia:read ralfia:write openid profile",
            "mcp_profile": "chatgpt_compact",
            "resource": "https://mcp.pcdoctor.ai/router/mcp",
        }
        for tool in (
            "poll_agent_inbox",
            "dev_swarm_launch_task",
            "dev_swarm_scheduler_tick",
        ):
            scopes = am._effective_token_scopes(token, tool, {})
            self.assertIn("ralfia:agents", scopes, msg=tool)

    def test_non_orchestration_tool_keeps_raw_scopes_without_agents(self) -> None:
        token = {"scope": "ralfia:read openid", "mcp_profile": "chatgpt_compact"}
        scopes = am._effective_token_scopes(token, "search", {})
        self.assertNotIn("ralfia:agents", scopes)

    def test_resolve_bearer_exposes_raw_and_effective_scopes(self) -> None:
        token = {
            "scope": "ralfia:read ralfia:write",
            "mcp_profile": "chatgpt_compact",
        }
        with patch.object(am, "validate_access_token", return_value=token):
            ctx = am.resolve_bearer_auth_context(
                {"authorization": "Bearer test-token"},
            )
        self.assertTrue(ctx["ok"])
        self.assertIn("ralfia:read", ctx["token_scopes_raw"])
        scopes_for_swarm = am._effective_token_scopes(token, "dev_swarm_launch_task", {})
        self.assertIn("ralfia:agents", scopes_for_swarm)

    def test_router_oauth_challenge_matches_public_metadata_url(self) -> None:
        meta_url = "https://mcp.pcdoctor.ai/router/mcp/.well-known/oauth-protected-resource"
        challenge = build_oauth_www_authenticate(meta_url)
        self.assertIn(meta_url, challenge)
        meta = protected_resource_metadata(
            "mcp.pcdoctor.ai",
            resource_override="https://mcp.pcdoctor.ai/router/mcp",
        )
        self.assertEqual(meta["resource"], "https://mcp.pcdoctor.ai/router/mcp")

    def test_diagnose_session_separates_server_catalog_from_client_projection(self) -> None:
        profile = mcp_profiles.get_profile("chatgpt_compact")
        profile_tools = profile["tools"]
        with patch.object(
            mcp_diagnostics.mongo_store,
            "get_coordination_state",
            return_value={"ok": False, "state": {}},
        ):
            result = mcp_diagnostics.diagnose_mcp_session(
                client_tool_count=len(profile_tools),
                client_seen_tools=profile_tools,
                profile="chatgpt_compact",
                session_id="lane-a-contract",
            )
        self.assertEqual(result["profile"], "chatgpt_compact")
        self.assertEqual(result["this_client_sees_tools"], len(profile_tools))
        self.assertEqual(result["expected_tool_count"], len(profile_tools))
        self.assertFalse(result["stale_catalog"])
        self.assertGreaterEqual(result["tool_count_global"], result["expected_tool_count"])


class TemporalHeartbeatCanaryTests(unittest.TestCase):
    def test_heartbeat_legacy_positional_actor_signals_temporal(self) -> None:
        from inneros_core_runtime import coordination_live

        with patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True, "backend": "temporal", "task_id": "ops_canary_a"},
        ) as signal:
            result = coordination_live.heartbeat_ops_task(
                "ops_canary_a",
                "dev_swarm",
                next_action="verification",
                files_touched=["platform/tests/test_p0_lane_a_scope_contract.py"],
            )
        self.assertTrue(result["ok"])
        signal.assert_called_once()
        payload = signal.call_args[0][2]
        self.assertEqual(payload["actor"], "dev_swarm")
        self.assertEqual(payload["next_action"], "verification")


if __name__ == "__main__":
    unittest.main()
