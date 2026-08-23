"""AG-47 Report Agent — informes técnicos y supervisor (delega AG-13 + store)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-47_REPORT_AGENT"


def agent_report_technical(
    client_ref: str,
    message: str = "",
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator as vero

    result = vero.technical_report_client(
        client_ref=client_ref,
        message=message or f"Informe técnico {client_ref}",
        channel="mcp",
    )
    record_agent_run(AGENT_ID, action="agent_report_technical", summary=f"client={client_ref}", project="pcdoctor")
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, "dry_run": dry_run, **result}


def agent_report_supervisor(
    client_id: str,
    site_id: str | None = None,
    visit_id: str | None = None,
) -> dict[str, Any]:
    from raphiia_openai import pcdoctor_store

    result = pcdoctor_store.generate_supervisor_report(client_id, site_id=site_id, visit_id=visit_id)
    record_agent_run(AGENT_ID, action="agent_report_supervisor", summary=f"client={client_id}", project="pcdoctor")
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}
