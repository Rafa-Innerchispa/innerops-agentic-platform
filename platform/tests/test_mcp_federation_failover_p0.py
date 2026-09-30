from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from inneros_core_runtime.mcp_gateway.federation import FederationManager


BACKENDS = {
    "intel": {
        "name": "Intel",
        "url": "http://127.0.0.1:18102/mcp",
        "default": True,
        "prefixes": ["*"],
    },
    "amd": {
        "name": "AMD",
        "url": "http://127.0.0.1:18202/mcp",
        "default": False,
        "prefixes": [],
    },
}


class StubFederation(FederationManager):
    def __init__(self, outcomes: dict[str, object]) -> None:
        self.outcomes = outcomes
        self.attempts: list[str] = []
        super().__init__(BACKENDS)

    async def _forward_once(self, backend, payload, headers):
        self.attempts.append(backend.name)
        outcome = self.outcomes[backend.name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class MCPFederationFailoverP0Tests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_protocol_request_fails_over(self) -> None:
        with patch.dict(os.environ, {"INNEROS_MCP_FAILOVER_ENABLED": "true"}):
            manager = StubFederation({
                "Intel": httpx.ConnectError("offline"),
                "AMD": {"jsonrpc": "2.0", "result": {"tools": []}},
            })
        response = await manager.forward_jsonrpc_post(
            manager.get_default_backend(),
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        self.assertIn("result", response)
        self.assertEqual(manager.attempts, ["Intel", "AMD"])

    async def test_read_only_tool_call_fails_over(self) -> None:
        with patch.dict(os.environ, {"INNEROS_MCP_FAILOVER_ENABLED": "true"}):
            manager = StubFederation({
                "Intel": httpx.ReadTimeout("timeout"),
                "AMD": {"jsonrpc": "2.0", "result": {"ok": True}},
            })
        response = await manager.forward_jsonrpc_post(
            manager.get_default_backend(),
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_coordination_status", "arguments": {}},
            },
        )
        self.assertIn("result", response)
        self.assertEqual(manager.attempts, ["Intel", "AMD"])

    async def test_mutation_without_idempotency_fails_closed(self) -> None:
        with patch.dict(os.environ, {"INNEROS_MCP_FAILOVER_ENABLED": "true"}):
            manager = StubFederation({
                "Intel": httpx.ConnectError("offline"),
                "AMD": {"jsonrpc": "2.0", "result": {"ok": True}},
            })
        with self.assertRaises(RuntimeError):
            await manager.forward_jsonrpc_post(
                manager.get_default_backend(),
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "create_agent_message", "arguments": {}},
                },
            )
        self.assertEqual(manager.attempts, ["Intel"])

    async def test_idempotent_mutation_may_fail_over(self) -> None:
        with patch.dict(os.environ, {"INNEROS_MCP_FAILOVER_ENABLED": "true"}):
            manager = StubFederation({
                "Intel": httpx.ConnectError("offline"),
                "AMD": {"jsonrpc": "2.0", "result": {"ok": True}},
            })
        response = await manager.forward_jsonrpc_post(
            manager.get_default_backend(),
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "create_agent_message",
                    "arguments": {"idempotency_key": "p0-test-key"},
                },
            },
        )
        self.assertIn("result", response)
        self.assertEqual(manager.attempts, ["Intel", "AMD"])

    async def test_client_error_never_fails_over(self) -> None:
        request = httpx.Request("POST", "http://intel/mcp")
        response = httpx.Response(401, request=request)
        error = httpx.HTTPStatusError("unauthorized", request=request, response=response)
        with patch.dict(os.environ, {"INNEROS_MCP_FAILOVER_ENABLED": "true"}):
            manager = StubFederation({
                "Intel": error,
                "AMD": {"jsonrpc": "2.0", "result": {"ok": True}},
            })
        with self.assertRaises(httpx.HTTPStatusError):
            await manager.forward_jsonrpc_post(
                manager.get_default_backend(),
                {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}},
            )
        self.assertEqual(manager.attempts, ["Intel"])

    async def test_disabled_failover_uses_only_primary(self) -> None:
        with patch.dict(os.environ, {"INNEROS_MCP_FAILOVER_ENABLED": "false"}):
            manager = StubFederation({
                "Intel": httpx.ConnectError("offline"),
                "AMD": {"jsonrpc": "2.0", "result": {"ok": True}},
            })
        with self.assertRaises(RuntimeError):
            await manager.forward_jsonrpc_post(
                manager.get_default_backend(),
                {"jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": {}},
            )
        self.assertEqual(manager.attempts, ["Intel"])


if __name__ == "__main__":
    unittest.main()
