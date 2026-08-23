"""AG-003 Analyst — analiza riesgos vía AIML API real."""

from __future__ import annotations

from typing import Any

from hackathon_band import band_adapter, llm_client
from hackathon_band import prompts


def run(chat_id: str, question: str, memory_text: str, *, lang: str = "en") -> dict[str, Any]:
    system = prompts.analyst_system(lang)
    user = f"Pregunta original: {question}\n\nMemoria recuperada:\n{memory_text[:10000]}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    llm = llm_client.chat("analyst", messages)

    msg = band_adapter.send_message(
        chat_id,
        agent_key="analyst",
        content=llm["text"],
        mention_keys=["documentation"],
    )
    return {"agent": "analyst", "message": msg, "llm": llm}
