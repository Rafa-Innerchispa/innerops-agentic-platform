"""MCP Tool Execution Throttling and Concurrency Control."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger("mcp_gateway.throttling")

DEFAULT_CONCURRENCY_LIMITS = {
    "profile_minimal": 5,
    "profile_coding": 10,
    "profile_admin": 50,
}


class ToolThrottledError(Exception):
    """Raised when concurrency semaphore pool is saturated."""

    def __init__(self, profile: str, limit: int) -> None:
        self.profile = profile
        self.limit = limit
        self.error_code = -32004
        self.message = (
            f"ToolThrottledError: Concurrency limit of {limit} active calls reached for profile '{profile}'. "
            "Please retry after existing calls complete."
        )
        super().__init__(self.message)


class ThrottlingManager:
    def __init__(self, limits: dict[str, int] | None = None) -> None:
        self.limits = limits or dict(DEFAULT_CONCURRENCY_LIMITS)
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._active_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def _get_semaphore(self, profile: str) -> tuple[asyncio.Semaphore, int]:
        limit = self.limits.get(profile, self.limits.get("profile_minimal", 5))
        if profile not in self._semaphores:
            self._semaphores[profile] = asyncio.Semaphore(limit)
            self._active_counts[profile] = 0
        return self._semaphores[profile], limit

    @asynccontextmanager
    async def acquire(self, profile: str, timeout: float = 0.05) -> AsyncIterator[None]:
        """Try to acquire a concurrency slot for the given profile.
        
        If immediate acquisition fails within timeout, raises ToolThrottledError without blocking connection.
        """
        sem, limit = self._get_semaphore(profile)
        
        # Check if already fully saturated
        if sem.locked():
            try:
                # Give a very brief window for quick turnarounds
                await asyncio.wait_for(sem.acquire(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Concurrency throttled for profile '%s' (limit=%d)", profile, limit)
                raise ToolThrottledError(profile=profile, limit=limit) from None
        else:
            await sem.acquire()

        self._active_counts[profile] = self._active_counts.get(profile, 0) + 1
        try:
            yield
        finally:
            self._active_counts[profile] = max(0, self._active_counts.get(profile, 1) - 1)
            sem.release()

    def get_stats(self) -> dict[str, dict[str, int]]:
        return {
            prof: {
                "limit": self.limits.get(prof, 5),
                "active": self._active_counts.get(prof, 0),
            }
            for prof in set(self.limits.keys()).union(self._active_counts.keys())
        }
