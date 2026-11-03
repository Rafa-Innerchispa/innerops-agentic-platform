"""Clasificación de turnos owner (Telegram/WhatsApp) — infra, finanzas, correo, web, chat."""

from __future__ import annotations

import re
from typing import Any

_STATUS_OVERVIEW_RE = re.compile(
    r"\b("
    r"c[oó]mo\s+(?:va|est[aá]|van)|qu[eé]\s+tal|"
    r"estado\s+(?:del?\s+)?servidor|servidor\s+est[aá]|"
    r"resumen\s+(?:del?\s+)?(?:servidor|servicios)|"
    r"c[oó]mo\s+est[aá]n?\s+(?:los\s+)?servidores?"
    r")\b",
    re.I,
)
_STATUS_DETAIL_RE = re.compile(
    r"\b("
    r"cu[aá]les?\s+(?:son|eran|fueron)|lista|listame|enumera|nombra|detalle|"
    r"los\s+otros|el\s+resto|esos\s+\d+|los\s+\d+|"
    r"qu[eé]\s+servicios|cu[aá]ntos\s+servicios|"
    r"especific(a|ar)|desglosa|cu[aá]l\s+es\s+cada"
    r")\b",
    re.I,
)
_WEB_RE = re.compile(
    r"\b("
    r"busca(?:r)?\s+(?:en\s+)?(?:internet|la\s+web|google)|"
    r"noticias?\s+(?:de|sobre)|precio\s+(?:de|del)|"
    r"qu[eé]\s+es\s+(?:un|una|el|la)\s+\w|"
    r"investiga(?:r)?\s+(?:sobre|en)"
    r")\b",
    re.I,
)
_DINEROS_RE = re.compile(
    r"\b(cont[ií]fico|dineros|factura|cotizaci[oó]n|banco|pichincha|produbanco|"
    r"ledger|transacci[oó]n|saldo|pago\s+de)\b",
    re.I,
)
_INFRA_HINTS = (
    "servidor",
    "servicios",
    "intel",
    "amd",
    "evolution",
    "verde",
    "rojo",
    "mcp",
    "panel",
    "ralfia",
    "nodo",
)


def _last_assistant_text(history: list[dict[str, str]]) -> str:
    for turn in reversed(history or []):
        if str(turn.get("role") or "") == "assistant":
            return str(turn.get("text") or "")
    return ""


def _recent_infra_thread(history: list[dict[str, str]]) -> bool:
    blob = _last_assistant_text(history).lower()
    return any(h in blob for h in _INFRA_HINTS)


def classify_owner_turn(
    message: str,
    *,
    intents: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Devuelve una ruta coarse:
    infra_overview | infra_detail | finance | email | web | general
    """
    text = (message or "").strip()
    intents = list(intents or [])
    history = history or []

    if _WEB_RE.search(text) and "status" not in intents:
        return "web"

    if any(i in intents for i in ("contifico", "bank", "ledger", "payment_hint")) or _DINEROS_RE.search(text):
        return "finance"

    if any(i in intents for i in ("emails", "poll", "notifications")):
        return "email"

    infra_context = "status" in intents or _recent_infra_thread(history)
    if infra_context and _STATUS_DETAIL_RE.search(text):
        return "infra_detail"
    if _STATUS_OVERVIEW_RE.search(text) and "status" in intents:
        return "infra_overview"
    if infra_context and re.search(r"\bservicios?\b", text, re.I) and len(text.split()) <= 14:
        return "infra_detail"

    if "status" in intents and _STATUS_OVERVIEW_RE.search(text):
        return "infra_overview"

    return "general"


def route_system_hint(route: str) -> str:
    hints = {
        "infra_overview": "Responde un resumen breve del servidor; no listes todo salvo que lo pidan.",
        "infra_detail": "El usuario pide detalle o lista; usa CONTEXTO de servicios y el historial; no repitas el resumen anterior.",
        "finance": "Pregunta de contabilidad/Contífico/DinerOS: usa datos del CONTEXTO financiero.",
        "email": "Pregunta de correo: usa CONTEXTO de bandejas; acciones sensibles piden confirmación.",
        "web": "Pregunta de información externa: responde con prudencia; si no hay datos en CONTEXTO, dilo y no inventes URLs.",
        "general": "Conversación natural: interpreta la pregunta actual usando el historial; no repitas la respuesta anterior.",
    }
    return hints.get(route, hints["general"])
