"""Runners delgados AG-01..54 — reutilizan módulos MCP existentes (sin CrewAI en runtime)."""

from __future__ import annotations

from typing import Any, Callable

from raphiia_openai.agent_auto_log import record_agent_run

Runner = Callable[..., dict[str, Any]]


def _ok(agent_id: str, action: str, **payload: Any) -> dict[str, Any]:
    ok = payload.pop("ok", True)
    payload.pop("agent_id", None)
    record_agent_run(agent_id, action=action, summary=action[:40], project="ralfia-agents")
    return {"ok": bool(ok), "agent_id": agent_id, **payload}


def _merge(agent_id: str, action: str, result: dict[str, Any]) -> dict[str, Any]:
    """Envuelve resultado de módulo ag*.py sin colisión agent_id en **kwargs."""
    payload = dict(result)
    payload.pop("agent_id", None)
    return _ok(agent_id, action, **payload)


def run_ag01(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import mcp_fleet
    return _ok("AG-01", "network_status", fleet=mcp_fleet.fleet_status())


def run_ag02(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import daily_memory
    q = message.strip() or "contexto reciente"
    return _ok("AG-02", "search_memory", **daily_memory.search_memory({"query": q, "limit": 10, "actor": "RAFAEL", "owner_id": "RAFAEL"}))


def run_ag03(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import local_model_router
    return _ok("AG-03", "ai_usage", report=local_model_router.get_ai_usage_report())


def run_ag04(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import coordination_docs
    path = message.strip() or "HUB/ESTADO_VIVO.md"
    doc = coordination_docs.read_coordination_file(path, max_chars=4000)
    return _ok("AG-04", "read_doc", path=path, doc=doc)


def run_ag05(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive, email_review

    q = (message or "").strip()
    ql = q.lower()
    if not q or ql in ("inbox", "bandeja", "estado", "status", "review"):
        reviews = email_review.list_reviews(limit=8)
        status = email_archive.get_email_archive_status()
        return _ok(
            "AG-05",
            "email_inbox",
            archive_status=status,
            count=len(reviews),
            previews=[email_review.format_review_text(r)[:500] for r in reviews[:5]],
        )
    if ql.startswith("mail:") or (len(q) > 24 and "@" not in q):
        mail_id = q.replace("mail:", "").strip()
        return _ok("AG-05", "email_detail", **email_review.get_review(mail_id))
    return _ok("AG-05", "search_email", **email_archive.search_email_archive(query=q or None, limit=15))


def run_ag06(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator
    return _ok("AG-06", "field_voice", **vero_orchestrator.technical_report_client(client_ref=message or "campo", message=message))


def run_ag07(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import notion_bridge

    q = (message or "").strip()
    ql = q.lower()
    if not q or ql == "status":
        return _ok("AG-07", "notion_status", **notion_bridge.get_notion_status())
    if "sync" in ql or "docs" in ql or "document" in ql:
        return _ok("AG-07", "notion_sync", **notion_bridge.sync_documentation_to_notion(mode="dry_run", limit=20))
    if ql.startswith("search:") or len(q) > 2:
        query = q.replace("search:", "").strip() or q
        return _ok("AG-07", "notion_search", **notion_bridge.search_notion_pages(query, limit=10))
    return _ok("AG-07", "notion_status", **notion_bridge.get_notion_status())


def run_ag08(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.operational import accounting_store
    return _ok("AG-08", "accounting_summary", **accounting_store.accounting_summary())


def run_ag09(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import hybrid_context
    q = message.strip() or "ralfia"
    return _ok("AG-09", "hybrid_search", **hybrid_context.hybrid_search(q, limit=10))


def run_ag10(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import contifico_bridge
    return _ok("AG-10", "contifico_status", **contifico_bridge.get_contifico_status())


def run_ag11(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    items = mongo_store.list_pipeline(limit=10)
    return _ok("AG-11", "list_pipeline", count=len(items), items=items)


def run_ag12(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import registry
    return _ok("AG-12", "project_bindings", **registry.list_project_bindings())


def run_ag13(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator
    return _ok("AG-13", "technical_report", **vero_orchestrator.technical_report_client(client_ref=message or "inspección", message=message))


def run_ag14(message: str = "", *, dry_run: bool = False, **_: Any) -> dict[str, Any]:
    import re

    from raphiia_openai.operational import pcdoctor_store

    name = message.strip() or "Nuevo cliente"
    client_match = re.search(r"\bclient_[0-9a-f]{24}\b", message or "", re.I)
    site_match = re.search(r"\bsite_[0-9a-f]{24}\b", message or "", re.I)
    payload = {
        "display_name": name,
        "source": "ag14_runner",
    }
    if client_match:
        payload["client_id"] = client_match.group(0)
    if site_match:
        payload["site_id"] = site_match.group(0)
    if dry_run:
        plan = {
            "ok": True,
            "dry_run": True,
            "would_call": "create_client_draft",
            "available_msp_tools": [
                "build_client_360_snapshot",
                "register_client_document",
                "list_client_documents",
                "record_site_network_snapshot",
                "list_site_network_snapshots",
            ],
            "payload": payload,
            "idempotency_keys": {k: v for k, v in payload.items() if k in ("client_id", "site_id")},
            "next_steps": [
                "resolve existing client/site",
                "collect missing fields",
                "attach historical documents as unverified with register_client_document",
                "record historical CCTV/network evidence as field_verified=false with record_site_network_snapshot",
            ],
        }
        return _ok("AG-14", "client_draft_plan", **plan)
    return _ok("AG-14", "client_draft", **pcdoctor_store.create_client_draft(payload))


def run_ag15(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.operational import inventory_store
    return _ok("AG-15", "list_inventory", **inventory_store.list_inventory(query=message or None, limit=20))


def run_ag16(message: str = "", *, dry_run: bool = True, **_: Any) -> dict[str, Any]:
    from raphiia_openai.commercial import vero_orchestrator
    return _ok("AG-16", "quote", **vero_orchestrator.quote_client(client_ref=message or "cliente", dry_run=dry_run))


def run_ag17(message: str = "", *, dry_run: bool = True, **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag17_contifico_bridge_agent as ag17

    msg = (message or "").strip()
    tax = ag17.extract_tax_id_from_message(msg)
    digits_only = msg.isdigit()
    if tax or (digits_only and len(msg) in (10, 13)):
        tid = tax or msg
        return _merge("AG-17", "fiscal_validate", ag17.validate_ecuador_tax_id(tid))
    if digits_only and len(msg) < 10:
        return _merge("AG-17", "fiscal_validate", ag17.validate_ecuador_tax_id(msg))
    client_ref = msg or "cliente"
    return _merge(
        "AG-17",
        "invoice",
        ag17.run_contifico_invoice(client_ref, message=msg, require_approval=dry_run),
    )


def run_ag18(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.operational import accounting_store
    return _ok("AG-18", "receivables", **accounting_store.list_receivables_open())


def run_ag19(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.operational import pcdoctor_store
    return _ok("AG-19", "list_clients", **pcdoctor_store.list_clients(limit=20))


def run_ag20(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import coordination_live, mcp_fleet
    from raphiia_openai.agents import agent_catalog
    from raphiia_openai.agents.pool_agent_runners import get_runner_registry

    live = coordination_live.get_coordination_live()
    fleet = mcp_fleet.fleet_status()
    cat = agent_catalog.get_agent_catalog(functional_only=True)
    runners = get_runner_registry()
    return _ok(
        "AG-20",
        "hub_dashboard",
        coordination=live,
        fleet=fleet,
        agents_functional=cat.get("count", 0),
        agents_runnable=len(runners),
        hub_doc="HUB/AGENT_FLEET_STATUS.md",
    )


def run_ag21(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag53_hackathon_agent as ag53
    return _ok("AG-21", "hackathon_harvest", **ag53.agent_hackathon_status())


def run_ag22(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag54_funding_credits_agent as ag54
    q = message.strip() or "grant opportunity funding"
    return _ok("AG-22", "scan_opportunities", **ag54.agent_funding_scan_emails(q))


def run_ag23(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag53_hackathon_agent as ag53
    q = message.strip() or "hackathon devpost"
    return _ok("AG-23", "analyze_opportunities", **ag53.agent_hackathon_scan_emails(q))


def run_ag24(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import funding_registry
    title = message.strip() or "Borrador postulación"
    return _ok("AG-24", "draft_application", **funding_registry.save_funding_application(title=title, body=message, status="draft"))


def run_ag26(message: str = "", **_: Any) -> dict[str, Any]:
    """Discord/SRE — invoke rápido; lógica completa requiere DISCORD_BOT_TOKEN."""
    import os
    if not os.getenv("DISCORD_BOT_TOKEN"):
        return _ok("AG-26", "discord_status", configured=False, note="Pool logic disponible; token Discord no configurado en host")
    if not (message or "").strip():
        return _ok("AG-26", "discord_ready", configured=True, note="Pasa message para comando SRE")
    import importlib.util
    from pathlib import Path
    logic = Path(__file__).resolve().parents[3] / "agents_pool" / "AG-26_discord_voice_bridge" / "src" / "logic.py"
    if not logic.is_file():
        return {"ok": False, "agent_id": "AG-26", "error": "discord_logic_missing"}
    spec = importlib.util.spec_from_file_location("ag26_logic", logic)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    agent = mod.DiscordVoiceBridgeAgent()
    result = agent.execute_local_system_command(message)
    return _ok("AG-26", "discord_sre", result=result)


def run_ag27(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    if not (message or "").strip():
        return _ok("AG-27", "ping", mongo=mongo_store.ping_mongo(), ready=True)
    from raphiia_openai.agents import ag42_service_guardian as ag42
    return _ok("AG-27", "system_health", mongo=mongo_store.ping_mongo(), guardian=ag42.run_service_guardian(notify=False))


def run_ag28(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag43_platform_sync_agent as ag43
    return _ok("AG-28", "platform_sync", **ag43.sync_platform_to_intel(dry_run=True))


def run_ag29(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41
    svc = message.strip() or "ralfia-mcp"
    return _ok("AG-29", "peer_ops_logs", **ag41.peer_ops_logs(service_id=svc, lines=50))


def run_ag33(message: str = "", **_: Any) -> dict[str, Any]:
    if not (message or "").strip():
        return _ok("AG-33", "ping", ready=True, note="sync on demand with message=apply")
    from raphiia_openai.documentary_daemon import run_once
    from raphiia_openai import notion_bridge
    changes = run_once()
    notion = notion_bridge.sync_documentation_to_notion(mode="dry_run", limit=20)
    return _ok("AG-33", "sync_docs", documentary_changes=changes, notion_sync=notion)


def run_ag34(message: str = "", *, dry_run: bool = True, **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag34_kb_ingest_agent as ag34
    return ag34.run_kb_ingest(message or "kb seed", dry_run=dry_run)


def run_ag35(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag35_ecosystem_pulse_agent as ag35
    return ag35.run_ecosystem_pulse()


def run_ag36(message: str = "", **kw: Any) -> dict[str, Any]:
    from raphiia_openai.agents import ag36_deferred_tasks_agent as ag36
    auto = kw.get("auto_escalate", False) or (message or "").strip().lower() in ("escalate", "escalar", "auto")
    if auto:
        return ag36.run_deferred_ops_cycle(auto_escalate=True)
    return ag36.run_deferred_ops_scan()


def run_ag45(message: str = "", **_: Any) -> dict[str, Any]:
    from raphiia_openai import local_execution_plane
    repo = message.strip() or "inneros/inneros_core/platform"
    return _ok("AG-45", "local_exec_inspect", **local_execution_plane.local_exec_inspect_repo(repo))


# Agentes con módulo dedicado ag*.py — reexport runners
def _import_dedicated() -> dict[str, Runner]:
    from raphiia_openai.agents import (
        ag40_runtime_reconciler as ag40,
        ag41_peer_ops_executor as ag41,
        ag42_service_guardian as ag42,
        ag43_platform_sync_agent as ag43,
        ag44_cloud_deployer as ag44,
        ag46_quote_agent as ag46,
        ag47_report_agent as ag47,
        ag48_billing_agent as ag48,
        ag50_daily_companion as ag50,
        ag51_health_memory_agent as ag51,
        ag52_iskcon_ops_agent as ag52,
        ag53_hackathon_agent as ag53,
        ag54_funding_credits_agent as ag54,
        ag55_browser_ops_agent as ag55,
    )
    from raphiia_openai.commercial import raul_orchestrator, vero_orchestrator
    from raphiia_openai.agents import ag25_ralfia_orchestrator as ag25, ag49_local_dispatcher as ag49

    return {
        "AG-25": lambda message="", **kw: ag25.ralfia_status() if not (message or "").strip() else ag25.ralfia_dispatch(message, auto_execute=True, dry_run=kw.get("dry_run", False)),
        "AG-49": lambda message="", **kw: ag49.list_local_agents() if not (message or "").strip() else ag49.dispatch_local_agent("daily", message=message, dry_run=kw.get("dry_run", True)),
        "AG-30": lambda message="", **kw: _merge("AG-30", "whatsapp_status", _whatsapp_status()),
        "AG-31": lambda message="", **kw: _merge("AG-31", "health_watch", _run_ag31()),
        "AG-32": lambda message="", **kw: _merge("AG-32", "home_ops", _home_ops(message)),
        "AG-37": lambda message="", **kw: _merge("AG-37", "disk", _disk_status()),
        "AG-38": lambda message="", dry_run=True, **kw: _merge("AG-38", "vero", vero_orchestrator.vero_dispatch(message=message, channel="mcp", require_approval=dry_run)),
        "AG-39": lambda message="", **kw: _merge("AG-39", "raul", raul_orchestrator.raul_dispatch(message=message or "catálogo")),
        "AG-40": lambda message="", **kw: _merge("AG-40", "reconcile", ag40.reconcile_runtime_state(dry_run=True)),
        "AG-41": lambda message="", **kw: _merge("AG-41", "peer_ops", ag41.peer_ops_snapshot()),
        "AG-42": lambda message="", **kw: _merge("AG-42", "guardian", ag42.run_self_heal_cycle(auto_repair=kw.get("auto_repair", False)) if (message or "").strip().lower() in ("heal", "self_heal", "reparar") else ag42.run_service_guardian(notify=False)),
        "AG-43": lambda message="", **kw: _merge("AG-43", "platform_sync", ag43.sync_platform_to_intel(dry_run=True)),
        "AG-44": lambda message="", **kw: _merge("AG-44", "cloud_deploy", ag44.cloud_deploy_status()),
        "AG-46": lambda message="", dry_run=True, **kw: _merge("AG-46", "quote", ag46.agent_quote_prepare(message or "cliente", dry_run=dry_run)),
        "AG-47": lambda message="", dry_run=True, **kw: _merge("AG-47", "report", ag47.agent_report_technical(message or "cliente", message=message, dry_run=dry_run)),
        "AG-48": lambda message="", dry_run=True, **kw: _merge("AG-48", "invoice", ag48.agent_invoice_prepare(message or "cliente", dry_run=dry_run)),
        "AG-50": lambda message="", **kw: _merge("AG-50", "companion", ag50.run_daily_companion(message, include_brief=bool((message or "").strip()))),
        "AG-51": lambda message="", **kw: _merge("AG-51", "health", ag51.agent_health_save(message[:60], message) if message.strip() else ag51.agent_health_summary()),
        "AG-52": lambda message="", dry_run=True, **kw: _merge("AG-52", "iskcon", ag52.agent_iskcon_status()),
        "AG-53": lambda message="", **kw: _merge("AG-53", "hackathon", ag53.agent_hackathon_status()),
        "AG-54": lambda message="", **kw: _merge("AG-54", "funding", ag54.agent_funding_sync_and_scan() if (message or "").strip().lower() in ("sync", "poll", "scan") else ag54.agent_funding_status()),
        "AG-55": lambda message="", dry_run=True, **kw: _merge("AG-55", "browser", ag55.agent_browser_status() if not (message or "").strip() else ag55.agent_browser_run_task("screenshot", message, dry_run=dry_run)),
    }


def _run_ag31() -> dict[str, Any]:
    from raphiia_openai.agents import ag31_service_recovery_agent as ag31
    return ag31.run_health_watch(notify=False, trigger="invoke")


def _home_ops(message: str) -> dict[str, Any]:
    from raphiia_openai import homeassistant_client
    return homeassistant_client.run_home_ops_cycle(trigger=message or "mcp")


def _whatsapp_status() -> dict[str, Any]:
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.get_whatsapp_status()


def _disk_status() -> dict[str, Any]:
    from raphiia_openai import disk_steward
    return disk_steward.build_status(include_candidates=False)


POOL_RUNNERS: dict[str, Runner] = {
    "AG-01": run_ag01,
    "AG-02": run_ag02,
    "AG-03": run_ag03,
    "AG-04": run_ag04,
    "AG-05": run_ag05,
    "AG-06": run_ag06,
    "AG-07": run_ag07,
    "AG-08": run_ag08,
    "AG-09": run_ag09,
    "AG-10": run_ag10,
    "AG-11": run_ag11,
    "AG-12": run_ag12,
    "AG-13": run_ag13,
    "AG-14": run_ag14,
    "AG-15": run_ag15,
    "AG-16": run_ag16,
    "AG-17": run_ag17,
    "AG-18": run_ag18,
    "AG-19": run_ag19,
    "AG-20": run_ag20,
    "AG-21": run_ag21,
    "AG-22": run_ag22,
    "AG-23": run_ag23,
    "AG-24": run_ag24,
    "AG-26": run_ag26,
    "AG-27": run_ag27,
    "AG-28": run_ag28,
    "AG-29": run_ag29,
    "AG-33": run_ag33,
    "AG-34": run_ag34,
    "AG-35": run_ag35,
    "AG-36": run_ag36,
    "AG-45": run_ag45,
}


def get_runner_registry() -> dict[str, Runner]:
    reg = dict(POOL_RUNNERS)
    reg.update(_import_dedicated())
    from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59
    reg["AG-59"] = lambda message="", dry_run=True, **kw: _merge("AG-59", "dmx", ag59.run_dmx_orchestrator(message, dry_run=dry_run))
    return reg


def invoke_agent(agent_id: str, message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    aid = agent_id.strip().upper()
    if not aid.startswith("AG-"):
        aid = f"AG-{aid}"
    runners = get_runner_registry()
    if aid not in runners:
        return {"ok": False, "error": "unknown_agent", "agent_id": aid, "available": sorted(runners.keys())}
    # Ping rápido: invoke vacío + dry_run → no ejecutar ciclos pesados (guardian, health watch, Ollama)
    if dry_run and not (message or "").strip():
        from raphiia_openai.agents.agent_catalog import get_catalog_entry
        meta = get_catalog_entry(aid) or {}
        return {
            "ok": True,
            "agent_id": aid,
            "ping": True,
            "display_name": meta.get("display_name", aid),
            "role": meta.get("role", ""),
            "entry_tool": meta.get("entry_tool"),
            "hint": "Pasa message para ejecución completa",
        }
    try:
        return runners[aid](message=message, dry_run=dry_run)
    except Exception as exc:
        return {"ok": False, "agent_id": aid, "error": str(exc)}
