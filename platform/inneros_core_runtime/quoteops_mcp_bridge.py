"""Authenticated local bridge from the shared RalfIA MCP to QuoteOps."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def call(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("QUOTEOPS_MCP_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    api_key = os.getenv("QUOTEOPS_MCP_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "quoteops_mcp_not_configured"}

    body = json.dumps(
        {"name": tool_name, "arguments": dict(payload or {})},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/mcp/call",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "error": "quoteops_http_error",
            "status_code": exc.code,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": "quoteops_unavailable",
            "detail": type(exc).__name__,
        }
    if not isinstance(result, dict):
        return {"ok": False, "error": "quoteops_invalid_response"}
    return result
