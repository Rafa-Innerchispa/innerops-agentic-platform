"""AG-005 Documentation — compila reporte Markdown final vía AIML."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hackathon_band import band_adapter, config, llm_client
from hackathon_band import prompts


def run(
    chat_id: str,
    question: str,
    memory_text: str,
    analyst_text: str,
    audit_trail: list[dict[str, Any]],
    memory_hits: list[dict[str, Any]] | None = None,
    *,
    lang: str = "en",
) -> dict[str, Any]:
    system = prompts.documentation_system(lang)
    user = (
        f"Pregunta: {question}\n\n"
        f"Memoria:\n{memory_text[:5000]}\n\n"
        f"Análisis:\n{analyst_text[:5000]}"
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    llm = llm_client.chat("documentation", messages)

    report = _ensure_sections(
        llm["text"], question, memory_text, analyst_text, audit_trail, llm,
        memory_hits=memory_hits or [],
        lang=lang,
    )
    config.REPORT_PATH.write_text(report, encoding="utf-8")

    msg = band_adapter.send_message(
        chat_id,
        agent_key="documentation",
        content=prompts.doc_band_message(lang),
        mention_keys=["analyst"],
    )
    return {
        "agent": "documentation",
        "message": msg,
        "llm": llm,
        "report_path": str(config.REPORT_PATH),
        "report_markdown": report,
    }


def _ensure_sections(
    draft: str,
    question: str,
    memory_text: str,
    analyst_text: str,
    audit_trail: list[dict[str, Any]],
    llm: dict[str, Any],
    memory_hits: list[dict[str, Any]] | None = None,
    *,
    lang: str = "en",
) -> str:
    from hackathon_band.memory_source import format_evidence_block

    evidence = format_evidence_block(memory_hits or [], lang=lang)
    title = prompts.report_fallback_title(lang)
    q_label = "Pregunta" if lang == "es" else "Question"
    mem_heading = "## Recovered Memory (agent synthesis)" if lang == "en" else "## Memoria recuperada (síntesis agente)"
    base = draft if draft.strip().startswith("#") else (
        f"{title}\n\n"
        f"**{q_label}:** {question}\n\n"
        f"## Executive Summary\n{draft[:800]}\n\n"
        f"{evidence}\n\n"
        f"{mem_heading}\n{memory_text[:2000]}\n\n"
        f"## {'Análisis' if lang == 'es' else 'Analysis'}\n{analyst_text[:2000]}\n"
    )

    if "MongoDB Evidence" not in base and "Evidencia MongoDB" not in base:
        base = base.replace(
            f"## {'Memoria recuperada' if lang == 'es' else 'Recovered Memory'}",
            f"{evidence}\n\n## {'Memoria recuperada' if lang == 'es' else 'Recovered Memory'}",
            1,
        ) if ("Recovered Memory" in base or "Memoria recuperada" in base) else f"{base}\n\n{evidence}\n"

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    audit_lines = "\n".join(
        f"- `{m.get('timestamp', '')}` **{m.get('agent_name', '?')}**: "
        f"{(m.get('content') or '')[:120]}..."
        for m in audit_trail[-8:]
    )
    tech = (
        f"\n\n## Audit trail Band\n{audit_lines or '- (sin mensajes)'}\n\n"
        f"## Technologies used\n"
        f"- Band: LIVE\n"
        f"- LLM documentation: {llm.get('provider')} / {llm.get('model')}\n"
        f"- Memoria: MongoDB pcdoctor_swarm + {config.RALPHI_DATA_DOCS}\n"
        f"- Generado: {ts}\n"
    )
    if "## Technologies used" not in base:
        base += tech
    return base
