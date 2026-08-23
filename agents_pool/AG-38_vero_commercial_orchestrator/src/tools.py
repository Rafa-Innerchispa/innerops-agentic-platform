# Herramientas AG-38 Vero
from __future__ import annotations

from typing import Any


def get_tools() -> list[str]:
    return [
        "vero_dispatch",
        "quote_client",
        "invoice_client",
        "technical_report_client",
        "resolve_client",
        "create_quote_draft",
        "send_quote_delivery",
        "create_receivable_from_quote",
        "generate_supervisor_report",
    ]


def dispatch(message: str, **kwargs: Any) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.vero_dispatch(message, **kwargs)
