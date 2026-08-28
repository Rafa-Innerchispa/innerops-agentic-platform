"""AG-25 RalfIA — orquestador principal. Ve todo, enruta a cualquier agente."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-25_RALFIA_ORCHESTRATOR"
DISPLAY_NAME = "RalfIA"


def ralfia_status() -> dict[str, Any]:
    from raphiia_openai import coordination_live
    from raphiia_openai.agents import agent_catalog
    from raphiia_openai.agents.pool_agent_runners import get_runner_registry

    live = coordination_live.get_coordination_live()
    catalog = agent_catalog.get_agent_catalog(functional_only=False)
    runners = get_runner_registry()
    functional = [a for a in catalog.get("agents", []) if a.get("status") == "functional"]
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "role": "Orquestador principal — ve catálogo, coordinación y enruta",
        "coordination": {
            "revision": live.get("revision"),
            "open_ops": live.get("open_ops_count"),
            "mandatory_reads": live.get("mandatory_reads", [])[:5],
        },
        "agents_total": catalog.get("count"),
        "agents_functional": len(functional),
        "agents_runnable": len(runners),
        "entry_points": {
            "natural_language": "ralfia_dispatch(mensaje, auto_execute=true)",
            "by_id": "invoke_agent('AG-51', mensaje)",
            "by_intent": "resolve_agent(mensaje)",
            "catalog": "get_agent_catalog()",
        },
    }


def ralfia_dispatch(
    message: str,
    *,
    auto_execute: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Entrada principal RalfIA: interpreta intención → agente → ejecuta.
    Si el mensaje nombra un AG-xx explícito, invoca directo.
    """
    text = (message or "").strip()
    if not text:
        return ralfia_status()

    import re
    from raphiia_openai.agents import agent_catalog, agent_intent_router
    from raphiia_openai.agents.pool_agent_runners import invoke_agent

    explicit = re.search(r"\bAG-?\s*(\d{1,2})\b", text, re.I)
    if explicit and auto_execute:
        num = int(explicit.group(1))
        aid = f"AG-{num}"
        result = invoke_agent(aid, text, dry_run=dry_run)
        record_agent_run(AGENT_ID, action="ralfia_dispatch_explicit", summary=aid, project="ralfia")
        return {"ok": True, "orchestrator": AGENT_ID, "mode": "explicit", "agent_id": aid, "result": result}

    resolution = agent_catalog.resolve_agent(text)
    best = resolution.get("best_match")
    if auto_execute and best:
        routed = agent_intent_router.route_agent_request(text, auto_execute=True, dry_run=dry_run)
        record_agent_run(AGENT_ID, action="ralfia_dispatch_intent", summary=best.get("agent_id", ""), project="ralfia")
        return {"ok": True, "orchestrator": AGENT_ID, "mode": "intent", **routed}

    record_agent_run(AGENT_ID, action="ralfia_dispatch_status", summary="no_match", project="ralfia")
    return {
        "ok": True,
        "orchestrator": AGENT_ID,
        "mode": "catalog",
        "resolution": resolution,
        "status": ralfia_status(),
        "hint": "ralfia_dispatch(mensaje, auto_execute=true)",
    }
