"""Optional live read-only InnerOS MCP bridge (no device mutation).

Requires an owner-authorized MCP token kept in a local environment or vault.
The route invokes ONLY the allowlisted read-only network coverage capability.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit


class InnerOSLiveError(RuntimeError):
    pass


class InnerOSLiveReader:
    def __init__(self, url: str, token: str, site_id: str = "home_pcdoctor_lab"):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("INNEROS_MCP_URL requires an HTTPS endpoint without credentials")
        if not token.strip():
            raise ValueError("INNEROS_MCP_TOKEN is required")
        if site_id != "home_pcdoctor_lab":
            raise ValueError("Only the owner-authorized home lab site is supported")
        self.url = url
        self._token = token
        self.site_id = site_id

    def read_summary(self) -> dict:
        """Call MCP capability; do not expose full device registry to Switch chat."""
        try:
            return asyncio.run(self._read())
        except Exception as exc:
            raise InnerOSLiveError("InnerOS MCP live read failed: " + type(exc).__name__) from None

    async def _read(self) -> dict:
        try:
            import httpx2
            from mcp import Client
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise InnerOSLiveError("Install project with [inneros] optional dependencies") from exc
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + self._token},
            timeout=httpx2.Timeout(10.0, read=15.0),
        ) as http_client:
            async with Client(streamable_http_client(self.url, http_client=http_client)) as client:
                value = await client.call_tool("capability_invoke", {
                    "capability_id": "network.communication.coverage.v1",
                    "parameters": {"site_id": self.site_id},
                })
        if value.is_error:
            raise InnerOSLiveError("MCP rejected read-only capability call")
        payload = value.structured_content
        if not isinstance(payload, dict):
            for block in value.content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    payload = json.loads(text)
                    break
        if not isinstance(payload, dict):
            raise InnerOSLiveError("Unexpected MCP response type")
        result = payload.get("result") or {}
        data = result.get("result", result) if isinstance(result, dict) else {}
        if not (payload.get("ok", True) and isinstance(data, dict) and data.get("ok")):
            raise InnerOSLiveError("InnerOS capability did not complete successfully")
        devices = data.get("devices") or []
        counts = {"VERIFIED": 0, "STALE": 0, "UNKNOWN": 0}
        for device in devices:
            if not isinstance(device, dict):
                continue
            status = "VERIFIED" if device.get("verified") else device.get("connectivity_status", "UNKNOWN")
            counts[status if status in counts else "UNKNOWN"] += 1
        return {"source": "INNEROS_MCP_LIVE_READ", "registered_devices": data.get("registered_devices"),
                "observed_at": data.get("observed_at", "unknown"),
                "live_telemetry_verified": bool(data.get("live_telemetry_verified", False)),
                "status_counts": counts}