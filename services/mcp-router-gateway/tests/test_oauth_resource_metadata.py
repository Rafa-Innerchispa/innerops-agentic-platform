from __future__ import annotations

import unittest

from mcp_router_gateway.config import BackendTarget, RouterConfig, ToolProfile
from mcp_router_gateway.server import RouterHttpHandler


class _FakeRouter:
    profile_name = "chatgpt_compact"

    def __init__(self, config: RouterConfig) -> None:
        self.config = config

    def health_snapshot(self) -> dict:
        return {}


class OAuthResourceMetadataTests(unittest.TestCase):
    def test_oauth_metadata_resource_matches_public_router_mcp(self) -> None:
        config = RouterConfig(
            host="127.0.0.1",
            port=8250,
            active_profile="chatgpt_compact",
            default_backend="default",
            backends={"default": BackendTarget(name="default", url="http://127.0.0.1:8000")},
            profiles={"chatgpt_compact": ToolProfile(name="chatgpt_compact", prefixes=("git_",))},
            public_url="https://mcp.pcdoctor.ai/router/mcp",
            oauth_resource="https://mcp.pcdoctor.ai/mcp",
        )
        RouterHttpHandler.router = _FakeRouter(config)  # type: ignore[attr-defined]
        handler = RouterHttpHandler.__new__(RouterHttpHandler)
        meta = handler._oauth_metadata()
        self.assertEqual(meta["resource"], "https://mcp.pcdoctor.ai/router/mcp")
        self.assertEqual(meta["mcp_public_url"], "https://mcp.pcdoctor.ai/router/mcp")


if __name__ == "__main__":
    unittest.main()
