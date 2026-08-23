"""AG-001 Router — enruta la pregunta vía Band hacia Memory (Featherless)."""

from __future__ import annotations

from typing import Any

from hackathon_band import band_adapter, llm_client
from hackathon_band import prompts


def run(chat_id: str, question: str, *, lang: str = "en") -> dict[str, Any]:
    system = prompts.router_system(lang)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    llm = llm_client.chat("router", messages)

    msg = band_adapter.send_message(
        chat_id,
        agent_key="router",
        content=llm["text"],
        mention_keys=["memory"],
    )
    return {
        "agent": "router",
        "message": msg,
        "llm": llm,
        "routing_hint": llm["text"],
    }
