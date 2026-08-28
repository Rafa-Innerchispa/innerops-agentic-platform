"""Gemini REST client — soporta claves AIza (legacy) y AQ. (AI Studio 2026)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from config import GEMINI_API_KEY

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def _extract_text(data: dict) -> str:
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def gemini_generate_text(prompt: str, extra_body: dict | None = None) -> str:
    """Llamada REST nativa — claves AQ. fallan con algunos SDKs."""
    key = (GEMINI_API_KEY or "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY missing")

    body: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    if extra_body:
        body.update(extra_body)

    headers = {"Content-Type": "application/json", "User-Agent": "innerspark-swarm-os/1.0"}
    fetch_url = f"{GEMINI_URL}?key={key}" if key.startswith("AIza") else GEMINI_URL

    auth_attempts: list[dict[str, str]] = (
        [{"x-goog-api-key": key}, {"Authorization": f"Bearer {key}"}] if key.startswith("AQ.") else [{}]
    )

    last_err = "Gemini fetch failed"
    for auth in auth_attempts:
        res = requests.post(fetch_url, headers={**headers, **auth}, json=body, timeout=60)
        data = res.json()
        if res.ok:
            text = _extract_text(data)
            return text or "No response from Gemini."
        last_err = data.get("error", {}).get("message") or res.text
        if res.status_code != 401:
            break

    raise RuntimeError(f"[Gemini] {last_err}")


def _parse_json_block(text: str, fallback: dict) -> dict:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return fallback


def gemini_plan_mission(voice_text: str) -> dict[str, Any]:
    """
    Step 0 — Gemini plans the multi-droid mission from field voice text.
    Returns structured plan JSON for activity log + Devpost visibility.
    """
    prompt = f"""You are Cosmos Central orchestrator for InnerOS PC Doctor (Ecuador IT services).
Analyze this field technician voice note and output ONLY valid JSON (no markdown):
{{
  "mission_summary": "one sentence in English",
  "client_hint": "inferred client or site name",
  "equipment": ["list of equipment mentioned"],
  "droid_steps": [
    {{"droid": "D1", "action": "what Mail Gatekeeper does"}},
    {{"droid": "D2", "action": "what Voice Field does"}},
    {{"droid": "D3", "action": "what Cosmos Central does"}},
    {{"droid": "D4", "action": "what Care-Taker does"}},
    {{"droid": "D5", "action": "what Financial Ledger does"}},
    {{"droid": "D8", "action": "what Media Agent does"}}
  ],
  "quote_focus": "main item to quote",
  "urgency": "low|medium|high"
}}

Voice note: {voice_text.strip()}
"""
    fallback = {
        "mission_summary": f"Field quote request: {voice_text[:120]}",
        "client_hint": "Client site from voice note",
        "equipment": ["Network equipment"],
        "droid_steps": [
            {"droid": "D1", "action": "Classify incoming request"},
            {"droid": "D2", "action": "Structure voice findings"},
            {"droid": "D3", "action": "Orchestrate MongoDB workflow"},
            {"droid": "D4", "action": "Generate technical report"},
            {"droid": "D5", "action": "Build quote with VAT"},
            {"droid": "D8", "action": "Notify client via WhatsApp"},
        ],
        "quote_focus": "Technical service",
        "urgency": "medium",
        "source": "fallback",
    }

    key = (GEMINI_API_KEY or "").strip()
    if not key or key in ("MY_GEMINI_API_KEY", "your-key-here"):
        fallback["source"] = "no_api_key"
        return fallback

    try:
        text = gemini_generate_text(prompt)
        plan = _parse_json_block(text, fallback)
        plan["source"] = "gemini"
        plan["model"] = GEMINI_MODEL
        return plan
    except Exception as exc:
        fallback["source"] = "error"
        fallback["error"] = str(exc)[:200]
        return fallback
