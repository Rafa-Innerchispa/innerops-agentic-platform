from __future__ import annotations

import unittest
from pathlib import Path

from inneros_core_runtime.mcp_gateway.federation import BackendEndpoint
from inneros_core_runtime.mcp_gateway.gateway import MCPGateway
from inneros_core_runtime.mcp_gateway.profiles import ProfileManager


class FakeFederation:
    def __init__(self) -> None:
        self.backend = BackendEndpoint(
            name="fake",
            url="http://127.0.0.1:9/mcp",
            is_default=True,
        )
        self.calls: list[dict] = []

    def get_default_backend(self) -> BackendEndpoint:
        return self.backend

    def resolve_backend_for_tool(self, tool_name: str) -> BackendEndpoint:
        return self.backend

    async def forward_jsonrpc_post(
        self,
        backend: BackendEndpoint,
        payload: dict,
        headers: dict | None = None,
    ) -> dict:
        self.calls.append(payload)
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {
                "content": [{"type": "text", "text": "forwarded"}],
            },
        }


def profile_manager() -> ProfileManager:
    return ProfileManager(
        inline_config={
            "default_profile": "profile_minimal",
            "allow_admin_profile": True,
            "profiles": {
                "profile_minimal": {
                    "allow_all": False,
                    "max_tools": 15,
                    "tools": ["safe_tool"],
                },
                "profile_admin": {
                    "allow_all": True,
                    "max_tools": 1000,
                    "requires_auth": True,
                    "tools": [],
                },
            },
        },
        allow_admin_profile=True,
        admin_secret="test-admin-secret",
    )


class MCPGatewaySecurityP0Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.federation = FakeFederation()
        self.gateway = MCPGateway(
            profile_manager=profile_manager(),
            federation_manager=self.federation,
        )

    async def test_invoke_capability_denies_unlisted_target(self) -> None:
        response = await self.gateway.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "invoke_capability",
                    "arguments": {
                        "capability_id": "dangerous_tool",
                        "arguments": {},
                    },
                },
            },
            client_profile="profile_minimal",
        )

        self.assertEqual(response["error"]["code"], -32003)
        self.assertEqual(self.federation.calls, [])

    async def test_direct_call_denies_unlisted_target(self) -> None:
        response = await self.gateway.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "dangerous_tool",
                    "arguments": {},
                },
            },
            client_profile="profile_minimal",
        )

        self.assertEqual(response["error"]["code"], -32003)
        self.assertEqual(self.federation.calls, [])

    async def test_allowlisted_target_is_forwarded(self) -> None:
        response = await self.gateway.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "invoke_capability",
                    "arguments": {
                        "capability_id": "safe_tool",
                        "arguments": {"value": 1},
                    },
                },
            },
            client_profile="profile_minimal",
        )

        self.assertIn("result", response)
        self.assertEqual(len(self.federation.calls), 1)
        self.assertEqual(
            self.federation.calls[0]["params"]["name"],
            "safe_tool",
        )

    async def test_admin_profile_requires_secret(self) -> None:
        response = await self.gateway.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "dangerous_tool",
                    "arguments": {},
                },
            },
            client_profile="profile_admin",
        )

        self.assertEqual(response["error"]["code"], -32003)
        self.assertEqual(self.federation.calls, [])

    async def test_authenticated_admin_may_use_full_catalog(self) -> None:
        response = await self.gateway.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "dangerous_tool",
                    "arguments": {},
                },
            },
            client_profile="profile_admin",
            admin_secret="test-admin-secret",
        )

        self.assertIn("result", response)
        self.assertEqual(len(self.federation.calls), 1)

    def test_admin_secret_is_not_accepted_from_query_string(self) -> None:
        source = Path(
            "platform/inneros_core_runtime/mcp_gateway/server.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            'request.query_params.get("admin_secret")',
            source,
        )


if __name__ == "__main__":
    unittest.main()
