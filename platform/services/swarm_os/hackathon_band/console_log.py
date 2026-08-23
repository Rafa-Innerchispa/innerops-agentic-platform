"""Bus de logs estructurados para Live Command Console (WebSocket)."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

MAX_HISTORY = 600
_lock = threading.Lock()
_history: list[dict[str, Any]] = []
_listeners: list[Callable[[dict[str, Any]], None]] = []


def log(
    level: str,
    category: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "category": category,
        "message": message,
        **extra,
    }
    with _lock:
        _history.append(entry)
        if len(_history) > MAX_HISTORY:
            _history.pop(0)
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(entry)
        except Exception:
            pass
    return entry


def get_history(limit: int = MAX_HISTORY) -> list[dict[str, Any]]:
    with _lock:
        return list(_history[-limit:])


def subscribe(fn: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
    _listeners.append(fn)

    def unsubscribe() -> None:
        if fn in _listeners:
            _listeners.remove(fn)

    return unsubscribe


def clear() -> None:
    with _lock:
        _history.clear()
