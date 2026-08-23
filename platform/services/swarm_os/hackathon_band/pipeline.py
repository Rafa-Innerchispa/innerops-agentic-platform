"""Orquestación colaborativa real: Router → Memory → Analyst → Documentation vía Band."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from hackathon_band import band_adapter, config
from hackathon_band.agents import analyst_agent, documentation_agent, memory_agent, router_agent
from hackathon_band.console_log import log as clog
from hackathon_band.validate import require_config

ProgressCallback = Callable[[dict[str, Any]], None]


def run_collaboration(
    question: str | None = None,
    *,
    lang: str = "en",
    notify_phones: list[str] | None = None,
    notify_emails: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    require_config()
    lang = "es" if lang == "es" else "en"
    q = (question or config.DEFAULT_QUESTION).strip()
    clog("info", "system", f"Pipeline start ({lang}): {q[:100]}")

    def emit(step: str, payload: dict[str, Any]) -> None:
        if on_progress:
            on_progress({"step": step, **payload})

    chat = band_adapter.create_chat(title=f"Hackathon: {q[:60]}")
    chat_id = chat["chat_id"]
    emit("chat_created", {"chat_id": chat_id, "band": band_adapter.status()})

    clog("info", "system", "Router agent → Featherless", step="router")
    router_out = router_agent.run(chat_id, q, lang=lang)
    emit("router_done", {"agent": "router", "llm": router_out["llm"]})

    clog("info", "system", "Memory agent → MongoDB + Featherless", step="memory")
    memory_out = memory_agent.run(chat_id, q, router_out.get("routing_hint", ""), lang=lang)
    memory_text = memory_out["llm"]["text"]
    emit("memory_done", {
        "agent": "memory",
        "llm": memory_out["llm"],
        "sources": memory_out.get("sources", []),
        "memory_hits": memory_out.get("memory_hits", 0),
    })

    clog("info", "system", "Analyst agent → AIML (deepseek-r1, puede tardar 1–3 min)", step="analyst")
    analyst_out = analyst_agent.run(chat_id, q, memory_text, lang=lang)
    analyst_text = analyst_out["llm"]["text"]
    emit("analyst_done", {"agent": "analyst", "llm": analyst_out["llm"]})

    messages = band_adapter.get_messages(chat_id)
    for m in messages:
        m["band_mode"] = "LIVE"

    clog("info", "system", "Documentation agent → AIML (deepseek-r1, puede tardar 1–3 min)", step="documentation")
    doc_out = documentation_agent.run(
        chat_id, q, memory_text, analyst_text, messages,
        memory_hits=memory_out.get("hits", []),
        lang=lang,
    )
    emit("documentation_done", {"agent": "documentation", "report_path": doc_out["report_path"]})

    from hackathon_band.delivery import deliver_report

    deliver_report(
        q,
        doc_out["report_path"],
        doc_out.get("report_markdown", ""),
        memory_hits=memory_out.get("hits", []),
        memory_hits_count=memory_out.get("memory_hits", 0),
        lang=lang,
        extra_phones=notify_phones,
        extra_emails=notify_emails,
    )
    clog("success", "system", "Pipeline complete", chat_id=chat_id)

    from hackathon_band import llm_client

    return {
        "ok": True,
        "question": q,
        "chat_id": chat_id,
        "band_mode": "LIVE",
        "messages": band_adapter.get_messages(chat_id),
        "report_path": doc_out["report_path"],
        "report_markdown": doc_out["report_markdown"],
        "providers": llm_client.providers_status(),
        "steps": {
            "router": router_out,
            "memory": memory_out,
            "analyst": analyst_out,
            "documentation": doc_out,
        },
    }


# Compat: tests / imports antiguos
def _parse_phone_list(*parts: str | None) -> list[str]:
    from hackathon_band.phone_utils import parse_phone_list

    return parse_phone_list(*parts)
