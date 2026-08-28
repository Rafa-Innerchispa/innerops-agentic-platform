"""Metadatos de agentes para UI del jurado."""

from __future__ import annotations

from typing import Any

from hackathon_band import config, llm_client


def get_agents_catalog() -> list[dict[str, Any]]:
    llm_map = {
        "router": ("Featherless", config.FEATHERLESS_MODEL),
        "memory": ("Featherless", config.FEATHERLESS_MODEL),
        "analyst": ("AIML", config.AIML_MODEL),
        "documentation": ("AIML", config.AIML_MODEL),
    }
    descriptions_en = {
        "router": "Routes the operator question and defines what Memory must retrieve.",
        "memory": "Queries real MongoDB + server docs; synthesizes organizational memory.",
        "analyst": "Identifies risks, root causes and technical recommendations.",
        "documentation": "Compiles executive Markdown report + Band audit trail.",
    }
    descriptions_es = {
        "router": "Enruta la pregunta y define qué debe recuperar Memory.",
        "memory": "Consulta MongoDB + docs reales; sintetiza memoria organizacional.",
        "analyst": "Identifica riesgos, causas y recomendaciones técnicas.",
        "documentation": "Genera reporte ejecutivo MD + audit trail Band.",
    }
    tags = {
        "router": ["route", "plan"],
        "memory": ["mongo", "RAG"],
        "analyst": ["risk", "AIML"],
        "documentation": ["report", "MD"],
    }
    handles = {
        "router": "rafagye/router",
        "memory": "rafagye/memory",
        "analyst": "rafagye/analyst",
        "documentation": "rafagye/docmaker",
    }
    order = ["router", "memory", "analyst", "documentation"]
    out: list[dict[str, Any]] = []
    for key in order:
        agent = config.AGENTS[key]
        provider, model = llm_map[key]
        out.append(
            {
                "key": key,
                "code": agent["id"],
                "name": agent["name"],
                "handle": handles[key],
                "band_id": agent.get("band_id") or "",
                "provider": provider,
                "model": model,
                "tags": tags[key],
                "description_en": descriptions_en[key],
                "description_es": descriptions_es[key],
            }
        )
    return out


def get_suggested_questions() -> dict[str, list[str]]:
    return {
        "en": [
            "What do we know about the PoE switch for Torres de la Merced?",
            "Which SOP visits mention PoE switches or camera infrastructure?",
            "What findings exist in technical reports about PoE and cameras?",
        ],
        "es": [
            "¿Qué sabemos del switch PoE en Torres de la Merced?",
            "¿Qué visitas SOP mencionan switch PoE o infraestructura de cámaras?",
            "¿Qué hallazgos hay en reportes técnicos sobre PoE y cámaras?",
        ],
    }


def get_mongo_stats() -> dict[str, Any]:
    try:
        from tools.mongo import get_db

        db = get_db()
        cols = ["sop_visits", "technical_reports", "reports", "inspections", "clients"]
        return {c: db[c].count_documents({}) for c in cols if c in db.list_collection_names()}
    except Exception:
        return {}


def get_status_payload() -> dict[str, Any]:
    import os

    from hackathon_band import band_adapter
    from hackathon_band.validate import readiness

    return {
        "agents": get_agents_catalog(),
        "suggested_questions": get_suggested_questions(),
        "band": band_adapter.status(),
        "providers": llm_client.providers_status(),
        "readiness": readiness(),
        "mongo_db": os.getenv("MONGO_DB", "pcdoctor_swarm"),
        "docs_root": str(config.RALPHI_DATA_DOCS),
        "mongo_stats": get_mongo_stats(),
        "evolution": {
            "base_url": config.EVOLUTION_BASE_URL,
            "configured": bool(config.EVOLUTION_API_KEY),
            "instance": config.EVOLUTION_INSTANCE or "(auto)",
            "hackathon_notify_to": config.HACKATHON_WHATSAPP_TO or None,
            "hackathon_email_to": config.HACKATHON_EMAIL_TO or None,
            "note": "Comparte .env con InnerOS; alerta al terminar pipeline si HACKATHON_WHATSAPP_TO está definido",
        },
    }
