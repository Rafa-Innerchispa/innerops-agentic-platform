"""AG-50 Daily Companion — conversación día a día + brief local (sin créditos cloud)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-50_DAILY_COMPANION"


def run_daily_companion(message: str = "", *, include_brief: bool = True) -> dict[str, Any]:
    """Brief del día + memoria reciente + respuesta local vía Ollama."""
    from raphiia_openai import daily_memory
    from raphiia_openai import local_model_router

    brief = local_model_router.generate_daily_brief(limit=15) if include_brief else {"ok": True, "skipped": True}
    recent = daily_memory.search_memory({
        "query": message or "hoy pendientes",
        "limit": 8,
        "owner_id": "RAFAEL",
        "actor": "RAFAEL",
    })
    pending = daily_memory.get_current_state({"owner_id": "RAFAEL", "actor": "RAFAEL"})

    prompt = (
        f"Mensaje Rafael: {message or '¿Cómo va mi día?'}\n\n"
        f"Brief:\n{(brief.get('brief_markdown') or '')[:1500]}\n\n"
        f"Memoria reciente: {recent.get('count', 0)} items\n"
        f"Estado: {(pending.get('state') or pending) if isinstance(pending, dict) else pending}"
    )
    route = local_model_router.route_ai_task(
        title="daily_companion",
        body=message or "companion check-in",
        task_type="daily_companion",
    )
    reply = ""
    if route.get("runtime") == "local_model" and message.strip():
        r = local_model_router.run_local_model(
            task_type="daily_companion",
            prompt=prompt,
            max_tokens=400,
            temperature=0.4,
        )
        reply = (r.get("response") or "") if r.get("ok") else ""
    record_agent_run(AGENT_ID, action="run_daily_companion", summary=f"brief={brief.get('ok')}", project="daily-life")
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "brief": brief.get("brief_markdown", "")[:2000] if include_brief else None,
        "memory_hits": recent.get("count", 0),
        "reply_local": reply or "Usa route_ai_task o WhatsApp/voz para conversación extendida.",
        "routing": route,
        "profile_mcp": "daily_companion",
    }


def agent_daily_save_note(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    from raphiia_openai import daily_memory

    result = daily_memory.save_memory({
        "type": "summary",
        "kind": "summary",
        "title": title,
        "body": body,
        "visibility": "PRIVATE_PERSONAL",
        "privacy_scope": "PRIVATE_PERSONAL",
        "tags": tags or ["daily", "companion"],
        "owner_id": "RAFAEL",
        "actor": AGENT_ID,
    })
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}
