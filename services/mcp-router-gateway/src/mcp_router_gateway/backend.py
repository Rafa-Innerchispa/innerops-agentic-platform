from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .errors import BackendError


@dataclass(frozen=True, slots=True)
class BackendResponse:
    payload: dict[str, Any] | list[Any]
    session_id: str = ""
    content_type: str = "application/json"


def parse_sse_json(raw: bytes) -> dict[str, Any] | list[Any]:
    text = raw.decode("utf-8", "replace")
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        return json.loads("\n".join(data_lines))
    return json.loads(text)


class JsonRpcBackendClient:
    def __init__(self, backend_url: str, *, timeout_seconds: float = 30.0) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        payload: dict[str, Any] | list[Any],
        *,
        session_id: str = "",
        authorization: str = "",
    ) -> BackendResponse:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "mcp-router-gateway/0.2",
        }
        if authorization:
            headers["Authorization"] = authorization
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(
            self.backend_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                backend_session_id = response.headers.get("Mcp-Session-Id", "")
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise BackendError(f"backend HTTP {exc.code}", data={"detail": detail}) from exc
        except OSError as exc:
            raise BackendError(f"backend connection failed: {type(exc).__name__}") from exc

        try:
            return BackendResponse(
                payload=parse_sse_json(raw),
                session_id=backend_session_id,
                content_type=content_type,
            )
        except json.JSONDecodeError as exc:
            raise BackendError("backend returned non-JSON response") from exc
