"""Enrutamiento por intención — elige agente y opcionalmente ejecuta."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.agents.agent_catalog import AGENT_CATALOG, resolve_agent

AGENT_ID = "AG-49_LOCAL_DISPATCHER"

# Verbos que implican guardar/registrar (no solo consultar)
_SAVE_VERBS = ("registrar", "registra", "guardar", "guarda", "anotar", "anota", "apuntar", "log", "registro")
_QUERY_VERBS = ("cómo", "como", "qué", "que", "resumen", "historial", "timeline", "estado", "status")


def _wants_save(message: str) -> bool:
    m = message.lower()
    if any(v in m for v in _SAVE_VERBS):
        return True
    # "me siento mal/bien" con contenido sustantivo → save
    if "me siento" in m and len(m.split()) > 3:
        return True
    if any(x in m for x in ("presión", "presion", "glucosa", "dolor", "fiebre", "caminata", "mg/dl")):
        return True
    return False


def _wants_query_only(message: str) -> bool:
    m = message.lower().strip()
    if not m:
        return True
    if any(m.startswith(v) or f" {v} " in f" {m} " for v in _QUERY_VERBS):
        if not _wants_save(m):
            return True
    return False


def _extract_health_body(message: str) -> tuple[str, str]:
    """Devuelve (title, body) para agent_health_save."""
    text = message.strip()
    # Quitar prefijos conversacionales
    for prefix in (
        r"^(?:registra(?:r)?|guarda(?:r)?|anota(?:r)?)\s+(?:mi\s+)?salud\s*[:\-]?\s*",
        r"^(?:cómo|como)\s+me\s+siento\s*[:\-]?\s*",
        r"^salud\s*[:\-]\s*",
    ):
        text = re.sub(prefix, "", text, flags=re.IGNORECASE).strip()
    if not text:
        text = message.strip()
    title = text[:60] if len(text) <= 60 else text[:57] + "..."
    return title, text


def route_agent_request(
    message: str,
    *,
    auto_execute: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Resuelve agente por lenguaje natural y opcionalmente ejecuta.
    Ej: "cómo me siento hoy, algo cansado" → AG-51 Health Memory → agent_health_save
    """
    resolution = resolve_agent(message)
    if not resolution.get("ok"):
        return resolution

    best = resolution.get("best_match")
    if not best:
        return {
            "ok": True,
            "routed": False,
            "reason": "no_match",
            "resolution": resolution,
            "hint": "get_agent_catalog(functional_only=true)",
        }

    agent_id = best["agent_id"]
    meta = AGENT_CATALOG.get(agent_id, {})
    task_kind = meta.get("task_kind")
    result: dict[str, Any] | None = None
    action = "resolve_only"

    if auto_execute:
        action = "executed"
        if agent_id == "AG-51":
            from raphiia_openai.agents import ag51_health_memory_agent as ag51
            if _wants_query_only(message) and not _wants_save(message):
                result = ag51.agent_health_summary()
                action = "health_summary"
            else:
                title, body = _extract_health_body(message)
                result = ag51.agent_health_save(title, body, tags=["salud"])
                action = "health_save"
        elif agent_id == "AG-50":
            from raphiia_openai.agents import ag50_daily_companion as ag50
            result = ag50.run_daily_companion(message)
        elif agent_id == "AG-42":
            from raphiia_openai.agents import ag42_service_guardian as ag42
            m = message.lower()
            if any(k in m for k in ("reparar", "auto-repar", "self heal", "arreglar")):
                result = ag42.run_self_heal_cycle(auto_repair=not dry_run)
                action = "self_heal"
            else:
                result = ag42.run_service_guardian(notify=False)
                action = "guardian"
        elif task_kind:
            from raphiia_openai.agents import ag49_local_dispatcher as ag49
            result = ag49.dispatch_local_agent(task_kind, message=message, dry_run=dry_run)
        elif meta.get("entry_tool") == "invoke_agent":
            from raphiia_openai.agents.pool_agent_runners import invoke_agent as _invoke
            result = _invoke(agent_id, message, dry_run=dry_run)
            action = "invoke_agent"
        elif meta.get("entry_tool") == "ralfia_dispatch":
            from raphiia_openai.agents import ag25_ralfia_orchestrator as ag25
            result = ag25.ralfia_dispatch(message, auto_execute=True, dry_run=dry_run)
        elif meta.get("entry_tool") == "vero_dispatch":
            from raphiia_openai.commercial import vero_orchestrator as vero
            result = vero.vero_dispatch(message=message, channel="mcp", require_approval=dry_run)
        elif meta.get("entry_tool") == "get_coordination_live":
            from raphiia_openai import coordination_live
            result = coordination_live.get_coordination_live()
        elif meta.get("entry_tool"):
            result = {
                "ok": True,
                "delegated": True,
                "entry_tool": meta["entry_tool"],
                "note": f"Invocar tool MCP {meta['entry_tool']} con el mensaje del usuario",
            }
            action = "delegated_tool"

    record_agent_run(
        AGENT_ID,
        action="route_agent_request",
        summary=f"{agent_id}:{action}",
        project=meta.get("domain", "ralfia"),
    )
    return {
        "ok": True,
        "routed": True,
        "agent_id": agent_id,
        "display_name": best.get("display_name"),
        "confidence": best.get("confidence"),
        "action": action,
        "auto_execute": auto_execute,
        "resolution": resolution,
        "result": result,
    }
