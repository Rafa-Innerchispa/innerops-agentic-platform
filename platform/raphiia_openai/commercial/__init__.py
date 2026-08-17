"""Pipeline comercial PC Doctor — orquestación Vero."""

from raphiia_openai.commercial.vero_orchestrator import (
    COMMERCIAL_DELEGATES,
    VERO_AGENT_ID,
    VERO_ALIASES,
    VERO_DISPLAY_NAME,
    detect_intent,
    emit_contifico_invoice,
    get_commercial_mission,
    invoice_client,
    list_commercial_missions,
    mentions_vero,
    quote_client,
    technical_report_client,
    vero_dispatch,
    vero_proactive_briefing,
)

__all__ = [
    "VERO_AGENT_ID",
    "VERO_DISPLAY_NAME",
    "VERO_ALIASES",
    "COMMERCIAL_DELEGATES",
    "vero_dispatch",
    "vero_proactive_briefing",
    "quote_client",
    "invoice_client",
    "technical_report_client",
    "emit_contifico_invoice",
    "get_commercial_mission",
    "list_commercial_missions",
    "detect_intent",
    "mentions_vero",
]
