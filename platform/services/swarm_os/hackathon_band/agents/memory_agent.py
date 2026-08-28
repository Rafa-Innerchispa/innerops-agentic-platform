"""AG-004 Memory — memoria REAL (MongoDB + docs) sintetizada vía Featherless."""

from __future__ import annotations

from typing import Any

from hackathon_band import band_adapter, llm_client
from hackathon_band import prompts
from hackathon_band.memory_source import search_organizational_memory


def run(chat_id: str, question: str, routing_hint: str = "", *, lang: str = "en") -> dict[str, Any]:
    memory = search_organizational_memory(question)
    corpus = memory["corpus"]
    if not corpus.strip():
        raise RuntimeError(
            "Memoria organizacional vacía: revisa MongoDB (pcdoctor_swarm) "
            f"y docs en {memory.get('sources')}"
        )

    system = prompts.memory_system(lang)
    user = (
        f"Pregunta: {question}\n\n"
        f"Contexto router: {routing_hint}\n\n"
        f"Corpus real ({memory['corpus_chars']} chars, {len(memory['sources'])} fuentes):\n"
        f"{corpus}"
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    llm = llm_client.chat("memory", messages)

    msg = band_adapter.send_message(
        chat_id,
        agent_key="memory",
        content=llm["text"],
        mention_keys=["analyst"],
    )
    return {
        "agent": "memory",
        "message": msg,
        "llm": llm,
        "sources": memory["sources"],
        "hits": memory["hits"],
        "memory_hits": len(memory["hits"]),
    }
