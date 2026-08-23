"""Cliente LLM hackathon — Featherless (Memory/Router) y AIML (Analyst/Doc) obligatorios."""

from __future__ import annotations

from typing import Any

import requests

from hackathon_band import config
from hackathon_band.console_log import log as clog
from hackathon_band.exceptions import HackathonIntegrationError
from hackathon_band.validate import require_config


def _openai_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: int = 120,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.3}
    provider = "featherless" if "featherless" in base_url else "aiml" if "aiml" in base_url else "llm"
    clog("api", provider, f"POST {url} model={model}", role=messages[0].get("role") if messages else "")
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        clog("error", provider, f"Request failed: {exc}")
        raise HackathonIntegrationError("LLM", str(exc)) from exc
    if not res.ok:
        clog("error", provider, f"HTTP {res.status_code}: {res.text[:200]}")
        raise HackathonIntegrationError(
            "LLM", f"HTTP {res.status_code} {url}: {res.text[:400]}"
        )
    data = res.json()
    text = data["choices"][0]["message"]["content"]
    clog("success", provider, f"Response OK ({len(text)} chars)", model=model)
    return text


def _featherless(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not config.FEATHERLESS_API_KEY:
        raise HackathonIntegrationError(
            "Featherless", "FEATHERLESS_API_KEY no configurada en .env"
        )
    text = _openai_chat(
        config.FEATHERLESS_BASE_URL,
        config.FEATHERLESS_API_KEY,
        config.FEATHERLESS_MODEL,
        messages,
    )
    return {"text": text, "provider": "featherless", "model": config.FEATHERLESS_MODEL}


def _aiml(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not config.AIML_API_KEY:
        raise HackathonIntegrationError("AIML", "AIML_API_KEY no configurada en .env")
    text = _openai_chat(
        config.AIML_BASE_URL,
        config.AIML_API_KEY,
        config.AIML_MODEL,
        messages,
    )
    return {"text": text, "provider": "aiml", "model": config.AIML_MODEL}


def chat(role: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """
    role: router | memory → Featherless
          analyst | documentation → AIML
    """
    require_config()
    if role in ("router", "memory"):
        return _featherless(messages)
    if role in ("analyst", "documentation"):
        return _aiml(messages)
    raise ValueError(f"Rol LLM desconocido: {role}")


def providers_status() -> dict[str, bool]:
    band_ok = bool(config.BAND_API_KEY) or all(
        (config.BAND_AGENT_API_KEYS.get(k) or "").strip()
        for k in ("router", "memory", "analyst", "documentation")
    )
    return {
        "band": band_ok,
        "featherless": bool(config.FEATHERLESS_API_KEY),
        "aiml": bool(config.AIML_API_KEY),
        "gemini": bool(config.GEMINI_API_KEY),
    }
