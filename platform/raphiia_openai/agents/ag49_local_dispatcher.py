"""AG-49 Local Dispatcher — entrada única local-first sin créditos cloud."""

from __future__ import annotations

from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-49_LOCAL_DISPATCHER"

TASK_ROUTES = {
    "guardian": ("AG-42", "run_service_guardian"),
    "watch": ("AG-42", "run_service_guardian"),
    "quote": ("AG-46", "agent_quote_prepare"),
    "cotizar": ("AG-46", "agent_quote_prepare"),
    "report": ("AG-47", "agent_report_technical"),
    "informe": ("AG-47", "agent_report_technical"),
    "invoice": ("AG-48", "agent_invoice_prepare"),
    "factura": ("AG-48", "agent_invoice_prepare"),
    "reconcile": ("AG-40", "reconcile_runtime_state"),
    "peer_ops": ("AG-41", "peer_ops_snapshot"),
    "vero": ("AG-38", "vero_dispatch"),
    "daily": ("AG-50", "run_daily_companion"),
    "companion": ("AG-50", "run_daily_companion"),
    "health": ("AG-51", "agent_health_summary"),
    "salud": ("AG-51", "agent_health_summary"),
    "iskcon": ("AG-52", "agent_iskcon_status"),
    "hackathon": ("AG-53", "agent_hackathon_status"),
    "funding": ("AG-54", "agent_funding_status"),
    "credits": ("AG-54", "agent_funding_scan_emails"),
    "creditos": ("AG-54", "agent_funding_scan_emails"),
    "browser": ("AG-55", "agent_browser_run_task"),
    "navegador": ("AG-55", "agent_browser_run_task"),
    "playwright": ("AG-55", "agent_browser_run_task"),
    "sandbox": ("AG-56", "agent_sandbox_dispatch"),
    "uncensored": ("AG-56", "agent_sandbox_dispatch"),
    "research": ("AG-56", "agent_sandbox_dispatch"),
    "ingest": ("AG-34", "run_full_ingest"),
    "importar": ("AG-34", "run_full_ingest"),
    "heal": ("AG-42", "run_self_heal_cycle"),
    "reparar": ("AG-42", "run_self_heal_cycle"),
    "self_heal": ("AG-42", "run_self_heal_cycle"),
}


def list_local_agents() -> dict[str, Any]:
    from raphiia_openai.agents.agent_catalog import get_agent_catalog

    catalog = get_agent_catalog(functional_only=True)
    agents_map = {
        a["agent_id"]: f"{a['display_name']} — {a['role']}"
        for a in catalog.get("agents", [])
        if a.get("task_kind") or a["agent_id"] in ("AG-38", "AG-39", "AG-42", "AG-46", "AG-47", "AG-48", "AG-50", "AG-51", "AG-52", "AG-53", "AG-54", "AG-55")
    }
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "model": "local-first — Ollama/servidor, sin créditos Cursor/ChatGPT cloud",
        "execute_default": "dry_run=false — ejecuta de verdad; cotizaciones envían WA solo si mensaje incluye 'enviar'",
        "agents": agents_map,
        "task_kinds": sorted(TASK_ROUTES.keys()),
        "natural_language": "route_agent_request(mensaje, auto_execute=true)",
        "catalog": "get_agent_catalog()",
        "resolve": "resolve_agent(mensaje)",
        "doc": "HUB/AGENTES_ARQUITECTURA.md",
    }


def _commercial_send_explicit(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in ("enviar", "mandar", "aprobar envío", "aprobar envio", "confirmar envío"))


def dispatch_local_agent(
    task_kind: str,
    client_ref: str = "",
    message: str = "",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    kind = (task_kind or "").strip().lower()
    if kind not in TASK_ROUTES:
        return {"ok": False, "error": "unknown_task_kind", "allowed": sorted(TASK_ROUTES.keys())}

    agent_id, _ = TASK_ROUTES[kind]

    if kind in ("guardian", "watch"):
        from raphiia_openai.agents import ag42_service_guardian as ag42
        result = ag42.run_service_guardian(notify=False)
    elif kind in ("quote", "cotizar"):
        from raphiia_openai.agents import ag46_quote_agent as ag46
        quote_dry = dry_run or not _commercial_send_explicit(message)
        result = ag46.agent_quote_prepare(client_ref or message, title=message, dry_run=quote_dry)
    elif kind in ("report", "informe"):
        from raphiia_openai.agents import ag47_report_agent as ag47
        result = ag47.agent_report_technical(client_ref or message, message=message, dry_run=dry_run)
    elif kind in ("invoice", "factura"):
        from raphiia_openai.agents import ag48_billing_agent as ag48
        result = ag48.agent_invoice_prepare(client_ref or message, dry_run=dry_run)
    elif kind == "reconcile":
        from raphiia_openai.agents import ag40_runtime_reconciler as ag40
        result = ag40.reconcile_runtime_state(dry_run=True)
    elif kind == "peer_ops":
        from raphiia_openai.agents import ag41_peer_ops_executor as ag41
        result = ag41.peer_ops_snapshot()
    elif kind == "vero":
        from raphiia_openai.commercial import vero_orchestrator as vero
        approved = _commercial_send_explicit(message) and not dry_run
        result = vero.vero_dispatch(
            message=message or client_ref,
            channel="mcp",
            require_approval=not approved,
        )
    elif kind in ("daily", "companion"):
        from raphiia_openai.agents import ag50_daily_companion as ag50
        result = ag50.run_daily_companion(message or client_ref)
    elif kind in ("health", "salud"):
        from raphiia_openai.agents import ag51_health_memory_agent as ag51
        if message.strip():
            result = ag51.agent_health_save(message[:80], message, tags=["salud"])
        else:
            result = ag51.agent_health_summary()
    elif kind == "iskcon":
        from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52
        result = ag52.agent_iskcon_dispatch("ops" if message.strip() else "status", message, dry_run=dry_run)
    elif kind == "hackathon":
        from raphiia_openai.agents import ag53_hackathon_agent as ag53
        result = ag53.agent_hackathon_scan_emails(message or "hackathon credits devpost") if message.strip() else ag53.agent_hackathon_status()
    elif kind in ("funding", "credits", "creditos"):
        from raphiia_openai.agents import ag54_funding_credits_agent as ag54
        if message.strip().lower() in ("sync", "poll", "escanear", "scan"):
            result = ag54.agent_funding_sync_and_scan(message or "bright data credits grant")
        else:
            result = ag54.agent_funding_scan_emails(message or "credits grant funding cloud") if message.strip() else ag54.agent_funding_status()
    elif kind in ("browser", "navegador", "playwright"):
        from raphiia_openai.agents import ag55_browser_ops_agent as ag55
        if not message.strip():
            result = ag55.agent_browser_status()
        else:
            result = ag55.agent_browser_run_task("navigate", message, dry_run=dry_run)
    elif kind in ("sandbox", "uncensored", "research"):
        from raphiia_openai.agents import ag56_sandbox_fleet_agent as ag56
        result = ag56.agent_sandbox_dispatch(message or "estado")
    elif kind in ("heal", "reparar", "self_heal"):
        from raphiia_openai.agents import ag42_service_guardian as ag42
        result = ag42.run_self_heal_cycle(auto_repair=not dry_run)
    elif kind in ("ingest", "importar"):
        from raphiia_openai.agents import ag34_kb_ingest_agent as ag34
        result = ag34.run_full_ingest(email_limit=25, chatgpt_limit=150, dry_run=dry_run)
    else:
        result = {"ok": False, "error": "not_implemented"}

    record_agent_run(AGENT_ID, action="dispatch_local_agent", summary=f"{kind}->{agent_id}", project="ralfia-ops")
    return {"ok": bool(result.get("ok", True)), "dispatcher": AGENT_ID, "task_kind": kind, "routed_to": agent_id, "result": result}
