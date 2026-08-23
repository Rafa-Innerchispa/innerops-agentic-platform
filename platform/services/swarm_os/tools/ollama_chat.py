"""Cliente simple Ollama /api/chat."""

from __future__ import annotations

import json
from typing import Any

import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


def ollama_chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    format_json: bool = False,
    timeout: int = 120,
    temperature: float = 0.2,
) -> str:
    payload: dict[str, Any] = {
        "model": model or OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if format_json:
        payload["format"] = "json"
    r = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
