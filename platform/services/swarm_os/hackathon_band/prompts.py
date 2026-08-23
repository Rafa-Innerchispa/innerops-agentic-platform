"""Prompts por idioma — EN default, ES opcional."""

from __future__ import annotations

LANG_INSTRUCTION = {
    "en": "Respond ONLY in English.",
    "es": "Responde SOLO en español.",
}


def lang_label(lang: str) -> str:
    return "en" if lang != "es" else "es"


def router_system(lang: str) -> str:
    li = LANG_INSTRUCTION[lang_label(lang)]
    if lang == "es":
        return (
            "Eres Router Agent (AG-001) de PC Doctor. Analiza la pregunta del operador "
            "y define qué debe recuperar Memory Agent de la memoria organizacional real. "
            f"Máximo 6 líneas, sin inventar datos. {li}"
        )
    return (
        "You are Router Agent (AG-001) for PC Doctor. Analyze the operator question "
        "and define what Memory Agent must retrieve from real organizational memory. "
        f"Max 6 lines, do not invent data. {li}"
    )


def memory_system(lang: str) -> str:
    li = LANG_INSTRUCTION[lang_label(lang)]
    cite_rule = (
        "OBLIGATORIO: empieza con 'EN BASE DE DATOS:' listando hechos concretos "
        "(códigos visita, clientes, PoE, cámaras, switch) citando [mongodb:colección]. "
        "PROHIBIDO decir 'no hay datos' si el corpus menciona visitas, PoE, cámaras o reportes."
    )
    if lang == "es":
        return (
            "Eres Memory Agent (AG-004). Extrae hechos SOLO del corpus (MongoDB + docs reales). "
            f"{cite_rule} Bullets. {li}"
        )
    return (
        "You are Memory Agent (AG-004). Extract facts ONLY from the corpus (real MongoDB + docs). "
        f"{cite_rule} Use bullets. {li}"
    )


def analyst_system(lang: str) -> str:
    li = LANG_INSTRUCTION[lang_label(lang)]
    if lang == "es":
        return (
            "Eres Analyst Agent (AG-003) de PC Doctor. A partir de la memoria recuperada "
            "(datos reales), identifica riesgos, causas probables y recomendaciones técnicas. "
            f"No inventes datos fuera del contexto. {li}"
        )
    return (
        "You are Analyst Agent (AG-003) for PC Doctor. From recovered memory (real data), "
        "identify risks, probable causes and technical recommendations. "
        f"Do not invent data outside context. {li}"
    )


def documentation_system(lang: str) -> str:
    li = LANG_INSTRUCTION[lang_label(lang)]
    if lang == "es":
        return (
            "Eres Documentation Agent (AG-005). Genera un reporte Markdown ejecutivo "
            "basado ÚNICAMENTE en memoria y análisis proporcionados (datos reales). "
            "Secciones: Título, Executive Summary, Memoria recuperada, Riesgos, "
            f"Acciones recomendadas, Next steps. No inventar incidentes. {li}"
        )
    return (
        "You are Documentation Agent (AG-005). Generate an executive Markdown report "
        "based ONLY on provided memory and analysis (real data). "
        "Sections: Title, Executive Summary, Recovered Memory, Risks, "
        f"Recommended Actions, Next steps. Do not invent incidents. {li}"
    )


def doc_band_message(lang: str) -> str:
    if lang == "es":
        return "Reporte final generado → outputs/hackathon_report.md"
    return "Final report generated → outputs/hackathon_report.md"


def report_fallback_title(lang: str) -> str:
    if lang == "es":
        return "# Reporte Hackathon — Memoria Organizacional PC Doctor"
    return "# Hackathon Report — PC Doctor Organizational Memory"
