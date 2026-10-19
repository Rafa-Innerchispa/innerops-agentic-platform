"""AG-50 Daily Companion — conversación día a día + brief local, sin créditos cloud."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-50_DAILY_COMPANION"
DEFAULT_TIMEZONE = "America/Guayaquil"


def _is_english(language: str) -> bool:
    return str(language or "").lower().startswith("en")


def _greeting(language: str, now: datetime | None = None) -> str:
    local_now = now or datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    hour = local_now.hour
    if _is_english(language):
        if hour < 12:
            return "Good morning"
        if hour < 18:
            return "Good afternoon"
        return "Good evening"
    if hour < 12:
        return "Buenos días"
    if hour < 18:
        return "Buenas tardes"
    return "Buenas noches"


def _spoken_task_count(count: int, language: str) -> str:
    """Avoid large raw numbers that Alexa reads digit-by-digit in announcements."""
    if count > 100:
        return "more than one hundred" if _is_english(language) else "más de cien"
    return str(max(0, count))


def _spoken_snapshot(
    live: dict[str, Any],
    current_state: dict[str, Any],
    *,
    language: str = "es-US",
) -> str:
    """Build a deterministic owner brief before any model is involved."""
    parts: list[str] = []

    priority = live.get("current_priority") or {}
    title = str(priority.get("title") or "").strip()
    summary = str(priority.get("summary") or "").strip()
    english = _is_english(language)
    if title:
        label = "Main priority" if english else "Prioridad principal"
        parts.append(f"{label}: {title}.")
    if summary:
        parts.append(summary[:360].rstrip(".") + ".")

    tasks = live.get("open_ops_tasks") or []
    if tasks:
        task_lines = []
        for task in tasks[:5]:
            task_title = str(task.get("title") or "").strip()
            if not task_title:
                continue
            status = str(task.get("status") or ("pending" if english else "pendiente")).replace("_", " ")
            priority_name = str(task.get("priority") or "").upper()
            prefix = f"{priority_name} " if priority_name else ""
            task_lines.append(f"{prefix}{task_title} ({status})")
        if task_lines:
            count = int(live.get("open_ops_count") or len(tasks))
            spoken_count = _spoken_task_count(count, language)
            if english:
                parts.append(
                    f"There are {spoken_count} open development tasks. "
                    + "The main ones are: "
                    + "; ".join(task_lines)
                    + "."
                )
            else:
                parts.append(
                    f"Tienes {spoken_count} tareas de desarrollo abiertas. "
                    + "Las principales son: "
                    + "; ".join(task_lines)
                    + "."
                )
    else:
        parts.append(
            "There are no open development orders in coordination."
            if english
            else "No hay órdenes de desarrollo abiertas en coordinación."
        )

    state = current_state.get("state") if isinstance(current_state, dict) else None
    if isinstance(state, dict):
        pending = state.get("pending_items") or state.get("pending") or []
        if isinstance(pending, list) and pending:
            labels = []
            for item in pending[:3]:
                if isinstance(item, dict):
                    label = item.get("title") or item.get("summary") or item.get("text")
                else:
                    label = item
                if label:
                    labels.append(str(label).strip())
            if labels:
                label = "Personal reminders" if english else "Pendientes personales"
                parts.append(label + ": " + "; ".join(labels) + ".")

    return " ".join(parts).strip()


def _polish_spoken_brief(
    snapshot: str,
    local_model_router: Any,
    *,
    language: str = "es-US",
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Use local inference only as a presentation layer; deterministic text remains fallback."""
    greeting = _greeting(language, now)
    english = _is_english(language)
    if not snapshot:
        empty = (
            f"{greeting}. I found no priority items right now."
            if english
            else f"{greeting}. No encontré pendientes prioritarios en este momento."
        )
        return empty, {"ok": True, "fallback": True}

    if english:
        prompt = (
            "Turn this snapshot into a natural spoken English briefing for Rafael. "
            f"Use United States English and begin exactly with '{greeting}'. Maximum 90 words. "
            "Be concrete and do not invent facts. Do not mention internal IDs, telemetry, model names, "
            "or infrastructure details unless they block the project. Avoid reading long numbers or lists; "
            "summarize large counts naturally. Order: main priority, up to four items, and one closing focus sentence.\n\n"
            f"SNAPSHOT:\n{snapshot}"
        )
    else:
        prompt = (
            "Convierte este snapshot en un brief hablado en español natural para Rafael. "
            f"Empieza exactamente con '{greeting}'. Máximo 90 palabras. Sé concreto, no inventes datos, "
            "no menciones IDs internos, telemetría, nombres de modelos ni detalles de infraestructura "
            "salvo que sean un bloqueo del proyecto. Evita números largos y listas extensas; resume los "
            "conteos grandes de forma natural. Ordena: prioridad principal, hasta cuatro pendientes, "
            "y una frase final de enfoque.\n\n"
            f"SNAPSHOT:\n{snapshot}"
        )
    result = local_model_router.run_local_model(
        task_type="daily_brief",
        prompt=prompt,
        max_tokens=220,
        temperature=0.2,
    )
    if result.get("ok"):
        text = str(result.get("response") or "").strip()
        if text:
            return text[:900], result
    return f"{greeting}. {snapshot[:820]}", result


def run_daily_companion(
    message: str = "",
    *,
    include_brief: bool = True,
    language: str = "es-US",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Brief real de proyectos + memoria personal + conversación local."""
    from raphiia_openai import coordination_live
    from raphiia_openai import daily_memory
    from raphiia_openai import local_model_router

    live = coordination_live.get_coordination_live()
    recent = daily_memory.search_memory({
        "query": message or "hoy pendientes proyectos desarrollo",
        "limit": 8,
        "owner_id": "RAFAEL",
        "actor": "RAFAEL",
    })
    current_state = daily_memory.get_current_state({
        "owner_id": "RAFAEL",
        "actor": "RAFAEL",
    })

    snapshot = _spoken_snapshot(live, current_state, language=language) if include_brief else ""
    spoken_brief, brief_model = (
        _polish_spoken_brief(snapshot, local_model_router, language=language, now=now)
        if include_brief
        else ("", {"ok": True, "skipped": True})
    )

    reply = ""
    route = local_model_router.route_ai_task(
        title="daily_companion",
        body=message or "daily owner brief",
        task_type="daily_brief",
    )
    if message.strip():
        instruction = (
            "Answer as Rafael's operational companion using only this real context. "
            "If information is missing, say so. Be brief."
            if _is_english(language)
            else "Responde como compañero operativo de Rafael usando solo este contexto real. "
            "Si falta información, dilo. Sé breve."
        )
        prompt = (
            f"{instruction}\n\n"
            f"Mensaje: {message}\n"
            f"Brief actual: {spoken_brief}\n"
            f"Memoria reciente encontrada: {recent.get('count', 0)} items\n"
            f"Estado personal disponible: {bool(current_state.get('state') if isinstance(current_state, dict) else current_state)}"
        )
        response = local_model_router.run_local_model(
            task_type="daily_brief",
            prompt=prompt,
            max_tokens=300,
            temperature=0.3,
        )
        if response.get("ok"):
            reply = str(response.get("response") or "").strip()

    record_agent_run(
        AGENT_ID,
        action="run_daily_companion",
        summary=f"ops={live.get('open_ops_count', 0)} memory={recent.get('count', 0)}",
        project="daily-life",
    )
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "spoken_brief": spoken_brief,
        "brief": spoken_brief if include_brief else None,
        "snapshot": snapshot,
        "open_ops_count": int(live.get("open_ops_count") or 0),
        "current_priority": live.get("current_priority"),
        "memory_hits": recent.get("count", 0),
        "reply_local": reply or spoken_brief or "No hay novedades prioritarias.",
        "routing": route,
        "brief_model": {
            "ok": bool(brief_model.get("ok")),
            "backend": brief_model.get("backend"),
            "model": brief_model.get("model"),
        },
        "profile_mcp": "daily_companion",
        "language": language,
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
