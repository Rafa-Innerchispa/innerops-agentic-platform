from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module_name in list(sys.modules):
    if module_name == "inneros_core_runtime" or module_name.startswith("inneros_core_runtime."):
        sys.modules.pop(module_name, None)
    if module_name == "raphiia_openai" or module_name.startswith("raphiia_openai."):
        sys.modules.pop(module_name, None)

from fastmcp.exceptions import ToolError

from inneros_core_runtime import auth_middleware, mcp_profiles


_NOTION_READ_TOOLS = [
    "mcp_version",
    "diagnose_mcp_session",
    "list_mcp_tool_profiles",
    "get_mcp_profile",
    "route_mcp_tools",
    "bootstrap_context",
    "get_coordination_live",
    "get_notion_status",
    "search_notion_pages",
    "get_notion_coordination_contract",
    "get_notion_sync_log",
    "get_notion_webhook_setup",
]


class TestScopedMcpApiKeys(unittest.TestCase):
    def setUp(self) -> None:
        auth_middleware._SCOPED_API_KEYS = None
        auth_middleware._SCOPED_API_KEYS_TS = 0
        self._old_env = {key: os.environ.get(key) for key in (auth_middleware.SCOPED_API_KEYS_ENV, "MCP_TOOL_PROFILE")}

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        auth_middleware._SCOPED_API_KEYS = None
        auth_middleware._SCOPED_API_KEYS_TS = 0

    def _install_env_key(self, secret: str, **overrides) -> None:
        record = auth_middleware.make_scoped_api_key_record(
            identity="notion.claude",
            api_key=secret,
            scopes=["ralfia:read"],
            allowed_profiles=["chatgpt_compact", "notion_mcp_short"],
            allowed_tools=_NOTION_READ_TOOLS,
        )
        record.update(overrides)
        os.environ[auth_middleware.SCOPED_API_KEYS_ENV] = json.dumps({"keys": [record]})

    def _call_tool(self, tool_name: str, api_key: str):
        middleware = auth_middleware.ApiKeyMiddleware("global-owner-key")

        async def call_next(_context):
            return {"ok": True}

        with patch.object(auth_middleware, "_resolve_headers", return_value={"x-api-key": api_key}), patch.object(
            auth_middleware, "_tool_name", return_value=tool_name
        ), patch.object(auth_middleware.mongo_store, "get_db", side_effect=RuntimeError("no mongo in unit test")), patch.object(
            auth_middleware.mongo_store, "log_mcp_error"
        ):
            return asyncio.run(middleware.on_call_tool(object(), call_next))

    def test_scoped_key_allows_read_only_notion_probe_on_short_profile(self) -> None:
        os.environ["MCP_TOOL_PROFILE"] = "chatgpt_compact"
        self._install_env_key("scoped-fixture-key")

        result = self._call_tool("get_notion_status", "scoped-fixture-key")

        self.assertEqual(result, {"ok": True})

    def test_scoped_key_blocks_write_tool_without_scope(self) -> None:
        os.environ["MCP_TOOL_PROFILE"] = "chatgpt_compact"
        self._install_env_key("scoped-fixture-key")

        with self.assertRaises(ToolError) as raised:
            self._call_tool("notion_push_doc", "scoped-fixture-key")

        self.assertIn("key_tool_not_allowed", str(raised.exception))

    def test_scoped_key_is_profile_bound(self) -> None:
        os.environ["MCP_TOOL_PROFILE"] = "owner_dev"
        self._install_env_key("scoped-fixture-key")

        with self.assertRaises(ToolError) as raised:
            self._call_tool("get_notion_status", "scoped-fixture-key")

        self.assertIn("key_profile_not_allowed", str(raised.exception))

    def test_global_api_key_remains_backward_compatible(self) -> None:
        os.environ.pop(auth_middleware.SCOPED_API_KEYS_ENV, None)

        result = self._call_tool("notion_push_doc", "global-owner-key")

        self.assertEqual(result, {"ok": True})

    def test_notion_mcp_short_profile_is_small_and_read_only(self) -> None:
        profile = mcp_profiles.get_profile("notion_mcp_short")

        self.assertTrue(profile["ok"])
        self.assertLessEqual(profile["tool_count"], 12)
        self.assertTrue(mcp_profiles.validate_profiles()["ok"])
        self.assertNotIn("notion_push_doc", profile["tools"])
        self.assertNotIn("owner_vault_store_secret", profile["tools"])


if __name__ == "__main__":
    unittest.main()
