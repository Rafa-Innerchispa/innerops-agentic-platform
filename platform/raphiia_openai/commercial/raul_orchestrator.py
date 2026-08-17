"""RAUL (AG-39) — catálogo local Contifico→Mongo (0 créditos cloud).

Invocable desde WhatsApp, voz, MCP o ChatGPT: "dile a Raul que hidrate el catálogo".
"""

from __future__ import annotations

import re
from typing import Any

RAUL_AGENT_ID = "AG-39"
RAUL_DISPLAY_NAME = "Raul"
RAUL_ALIASES = frozenset({"raul", "raúl", "atlas", "catalogo", "catálogo", "contifico"})

RAUL_PREFIX_RE = re.compile(
    r"(?:dile\s+a\s+|p[ií]dele\s+a\s+|llama\s+a\s+|por\s+favor\s+)?"
    r"(?:raul|raúl|atlas)\s+(?:que\s+)?",
    re.I,
)

HYDRATE_RE = re.compile(
    r"\b(hidrata\w*|extrae\w*|sincroniza\w*|actualiza\w*|importa\w*|trae\w*|saca\w*)\b.*\b(cat[aá]logo|productos|contifico)\b",
    re.I,
)
STATUS_RE = re.compile(
    r"\b(estado|status|cu[aá]ntos|progreso|avance)\b.*\b(cat[aá]logo|productos|contifico|raul)\b",
    re.I,
)
SEARCH_RE = re.compile(
    r"\b(busca|encuentra|dame|mu[eé]strame)\b.*\b(producto|c[aá]mara|camara|hikvision|dahua)\b",
    re.I,
)


def _strip_raul_prefix(text: str) -> str:
    return RAUL_PREFIX_RE.sub("", text or "", count=1).strip()


def mentions_raul(message: str) -> bool:
    text = (message or "").lower()
    if RAUL_PREFIX_RE.search(message or ""):
        return True
    if any(alias in text for alias in RAUL_ALIASES) and re.search(
        r"\b(cat[aá]logo|productos|contifico|hidrata|extrae)\b", text, re.I
    ):
        return True
    return bool(re.search(r"\bdile\s+a\s+raul\b", text, re.I))


def detect_intent(message: str) -> str:
    cleaned = _strip_raul_prefix(message)
    if HYDRATE_RE.search(cleaned) or re.search(r"\b(hidrata\w*|extrae\w*)\b", cleaned, re.I):
        return "hydrate"
    if STATUS_RE.search(cleaned) or re.search(r"\b(estado|status|cu[aá]ntos)\b", cleaned, re.I):
        return "status"
    if SEARCH_RE.search(cleaned):
        return "search"
    if RAUL_PREFIX_RE.search(message or ""):
        return "status"
    return "status"


def _extract_search_query(message: str) -> str:
    cleaned = _strip_raul_prefix(message)
    for pat in (
        r"(?:busca|encuentra|dame|mu[eé]strame)\s+(?:productos?\s+)?(?:de\s+)?(.+)",
        r"(?:c[aá]maras?|productos?)\s+(.+)",
    ):
        m = re.search(pat, cleaned, re.I)
        if m:
            q = m.group(1).strip(" .?!")
            if len(q) >= 3:
                return q
    return "camara"


def format_raul_reply(result: dict[str, Any]) -> str:
    intent = result.get("intent", "status")
    if intent == "status":
        p = result.get("status") or {}
        lines = [
            f"*{RAUL_DISPLAY_NAME} · catálogo local*",
            f"Referenciados: **{p.get('referenced_product_ids', '?')}**",
            f"Ficha completa: **{p.get('local_products_full_hydrated', p.get('hydrated_in_catalog', '?'))}**",
            f"Índice ligero: **{p.get('local_products_indexed', '?')}**",
            f"Estado job: `{p.get('status', 'idle')}`",
        ]
        prog = (p.get("progress") or {})
        if prog.get("fetched_this_run"):
            lines.append(
                f"Última corrida: +{prog.get('fetched_this_run')} "
                f"({prog.get('errors', 0)} errores, {prog.get('elapsed_sec', '?')}s)"
            )
        if p.get("local_products_full_hydrated", 0) < p.get("referenced_product_ids", 0):
            lines.append("Dime *hidrata el catálogo* para completar fichas Contifico en local.")
        return "\n".join(lines)

    if intent == "hydrate":
        if result.get("started_background"):
            return (
                f"*{RAUL_DISPLAY_NAME} · hidratación* 🚀\n"
                f"{result.get('message', 'Corrida lanzada en AMD .5.')}\n"
                f"Pregunta *estado del catálogo* para ver progreso."
            )
        if result.get("dry_run"):
            return (
                f"*{RAUL_DISPLAY_NAME}* — simulación: pendientes **{result.get('pending', '?')}**, "
                f"~**{result.get('estimated_minutes', '?')} min** en AMD local (0 créditos cloud)."
            )
        if result.get("ok"):
            return (
                f"*{RAUL_DISPLAY_NAME} · hidratación* ✅\n"
                f"Extraídos: **{result.get('fetched_this_run', result.get('fetched', '?'))}** "
                f"| Total fichas: **{result.get('hydrated_after', '?')}** "
                f"| Errores: {result.get('errors', 0)} "
                f"| Tiempo: {result.get('elapsed_sec', '?')}s"
            )
        if result.get("error") == "hydration_already_running":
            prog = (result.get("progress") or {})
            return (
                f"*{RAUL_DISPLAY_NAME}* — ya estoy hidratando en AMD. "
                f"Progreso: {prog.get('fetched_this_run', prog.get('current', '?'))}…"
            )
        return f"*{RAUL_DISPLAY_NAME}* — no pude hidratar: {result.get('error', 'error')}"

    if intent == "search":
        items = result.get("items") or []
        lines = [f"*{RAUL_DISPLAY_NAME} · búsqueda catálogo local* ({len(items)} hits)"]
        for item in items[:5]:
            code = item.get("codigo") or item.get("sku") or "?"
            price = item.get("unit_price")
            ptxt = f" — ${price}" if price else ""
            desc = (item.get("descripcion") or "")[:80]
            lines.append(f"• `{code}` {item.get('name')}{ptxt}")
            if desc:
                lines.append(f"  _{desc}_")
        return "\n".join(lines)

    return f"*{RAUL_DISPLAY_NAME}* — {result.get('message', 'listo')}"


def raul_dispatch(
    message: str,
    *,
    channel: str = "mcp",
    phone: str | None = None,
    max_fetch: int | None = None,
    dry_run: bool = False,
    background: bool = True,
) -> dict[str, Any]:
    """Entrada única RAUL — estado, hidratación o búsqueda local."""
    from raphiia_openai.local_catalog_hydrator import get_hydration_state, run_local_hydration
    from raphiia_openai.contifico_bridge import search_contifico_products

    intent = detect_intent(message)
    cleaned = _strip_raul_prefix(message)

    if intent == "status":
        status = get_hydration_state()
        return {"ok": True, "agent": RAUL_AGENT_ID, "intent": "status", "status": status, "channel": channel}

    if intent == "search":
        query = _extract_search_query(cleaned or message)
        res = search_contifico_products(query, limit=8)
        return {
            "ok": True,
            "agent": RAUL_AGENT_ID,
            "intent": "search",
            "query": query,
            "items": res.get("items") or [],
            "count": res.get("count", 0),
            "channel": channel,
        }

    # hydrate
    if dry_run or re.search(r"\b(simula|dry|prueba)\b", message, re.I):
        result = run_local_hydration(max_fetch=max_fetch, dry_run=True)
        return {"ok": True, "agent": RAUL_AGENT_ID, "intent": "hydrate", **result, "channel": channel}

    state = get_hydration_state()
    if state.get("status") == "running":
        return {
            "ok": False,
            "agent": RAUL_AGENT_ID,
            "intent": "hydrate",
            "error": "hydration_already_running",
            "progress": state.get("progress"),
            "channel": channel,
        }

    if background and max_fetch is None:
        import subprocess
        import sys
        from pathlib import Path

        script = Path(__file__).resolve().parents[2] / "scripts" / "run_ag39_raul_hydrator.sh"
        subprocess.Popen(
            ["/bin/bash", str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        status = get_hydration_state()
        status["status"] = "running"
        return {
            "ok": True,
            "agent": RAUL_AGENT_ID,
            "intent": "hydrate",
            "started_background": True,
            "message": "Hidratación completa lanzada en AMD .5 (~19 min, 0 créditos cloud).",
            "status": status,
            "channel": channel,
        }

    result = run_local_hydration(max_fetch=max_fetch, dry_run=False, resume=True)
    return {"ok": result.get("ok", False), "agent": RAUL_AGENT_ID, "intent": "hydrate", **result, "channel": channel}
