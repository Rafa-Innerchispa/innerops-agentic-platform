from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import RouterConfig

_CACHE_TTL_SECONDS = 15.0


def health_url_for_mcp(mcp_url: str) -> str:
    base = mcp_url.rstrip("/")
    if base.endswith("/mcp"):
        base = base[: -len("/mcp")]
    return f"{base}/health"


def probe_backend_health(mcp_url: str, *, timeout: float = 3.0) -> bool:
    url = health_url_for_mcp(mcp_url)
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(getattr(resp, "status", 200)) < 300
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


class BackendHealthCache:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, bool]] = {}

    def is_healthy(self, backend_name: str, config: "RouterConfig") -> bool:
        target = config.backends.get(backend_name)
        if not target or not target.enabled:
            return False
        now = time.time()
        cached = self._cache.get(backend_name)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        ok = probe_backend_health(target.url)
        self._cache[backend_name] = (now, ok)
        return ok

    def snapshot(self, config: "RouterConfig") -> dict[str, bool]:
        return {name: self.is_healthy(name, config) for name in config.backends if config.backends[name].enabled}
