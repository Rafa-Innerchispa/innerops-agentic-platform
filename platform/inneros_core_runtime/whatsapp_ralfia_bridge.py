"""Puente WhatsApp → ralfia_dispatch (agentes locales, sin cloud)."""

from __future__ import annotations

import os
import re
from typing import Any

_MAX_WA = 520

# Intenciones que deben ir a agentes (no solo Ollama chitchat)
_AGENT_INTENT_RE = re.compile(
    r"\b("
    r"compañero|companion|salud|presi[oó]n|iskcon|ffl|panihati|hackathon|cr[eé]dito|grant|"
    r"cotiz|factur|informe|guardian|repar|self.?heal|servicios?\s+ca[ií]dos?|"
    r"deferred|pendientes|brief|flota|agente|ralfia|vero|ra[uú]l|contifico|notion|correo"
    r")\b",
    re.I,
)


def should_ralfia_dispatch(message: str, *, identity: dict[str, Any] | None = None) -> bool:
    if os.getenv("WHATSAPP_RALFIA_DISPATCH", "1").strip() in ("0", "false", "no"):
        return False
    text = (message or "").strip()
    if not text or len(text) < 3:
        return False
    from raphiia_openai import whatsapp_identity

    if identity and whatsapp_identity.is_owner(identity):
        return bool(_AGENT_INTENT_RE.search(text)) or len(text.split()) >= 4
    return bool(_AGENT_INTENT_RE.search(text))


def format_ralfia_result(routed: dict[str, Any]) -> str:
    """Texto WhatsApp compacto desde resultado de ralfia_dispatch."""
    if not routed.get("ok"):
        return f"No pude enrutar: {routed.get('error', 'sin match')[:200]}"

    inner = routed.get("result") or routed
    if isinstance(inner, dict) and inner.get("result"):
        inner = inner.get("result") or inner

    parts: list[str] = []
    agent = routed.get("agent_id") or routed.get("display_name") or inner.get("agent_id", "")
    if agent:
        parts.append(f"*{agent}*")

    for key in ("reply_local", "reply_text", "text", "brief", "summary", "message"):
        val = inner.get(key) if isinstance(inner, dict) else None
        if val and isinstance(val, str) and val.strip():
            parts.append(val.strip()[:400])
            break

    if isinstance(inner, dict):
        if inner.get("entries") is not None:
            parts.append(f"Registros salud: {inner.get('entries')}")
        if inner.get("deferred_count") is not None:
            parts.append(f"Ops deferred: {inner.get('deferred_count')}")
        if inner.get("hackathon_programs") is not None:
            parts.append(f"Programas hackathon: {len(inner.get('hackathon_programs') or [])}")
        if inner.get("unhealthy_services"):
            n = len(inner["unhealthy_services"])
            parts.append(f"Servicios unhealthy: {n}")
        elif inner.get("ok") is True and "guardian" in str(agent).lower():
            parts.append("Guardian OK — sin servicios caídos.")

    if not parts:
        mode = routed.get("mode") or "intent"
        parts.append(f"Ejecutado ({mode}). Usa status para detalle.")

    text = "\n".join(parts)
    return text[:_MAX_WA] if len(text) > _MAX_WA else text


def dispatch_and_format(message: str, *, dry_run: bool = False) -> dict[str, Any]:
    from raphiia_openai.agents import ag25_ralfia_orchestrator as ag25

    routed = ag25.ralfia_dispatch(message, auto_execute=True, dry_run=dry_run)
    body = format_ralfia_result(routed)
    return {
        "ok": bool(routed.get("ok", True)),
        "text": body,
        "source": "ralfia_dispatch",
        "routed": routed,
    }


def try_ralfia_dispatch_wa(
    message: str,
    *,
    identity: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    if not should_ralfia_dispatch(message, identity=identity):
        return None
    return dispatch_and_format(message, dry_run=dry_run)
