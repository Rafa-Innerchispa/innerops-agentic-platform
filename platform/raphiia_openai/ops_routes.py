"""Panel operaciones RalfIA — :2002 (alias memorable del :8800)."""

from __future__ import annotations

from typing import Any
import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from raphiia_openai import coordination_auto_sync, mongo_store, orchestration_store, service_registry
from raphiia_openai.mcp_catalog import tool_catalog
from raphiia_openai.mcp_diagnostics import mcp_version
from raphiia_openai.settings import MCP_API_KEY, OPS_PANEL_PUBLIC_URL, PORTAL_LEGACY_URL

router = APIRouter()


def _memory_review_authorized(request: Request) -> bool:
    expected = os.getenv("DAILY_MEMORY_REVIEW_TOKEN", "") or MCP_API_KEY
    supplied = request.headers.get("X-RalfIA-Memory-Review", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _ops_authorized(request: Request) -> bool:
    expected = os.getenv("DAILY_MEMORY_REVIEW_TOKEN", "") or MCP_API_KEY
    supplied = request.headers.get("X-RalfIA-Memory-Review", "") or request.headers.get("X-API-Key", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


@router.get("/api/ops/rag-preview")
def ops_rag_preview(request: Request, q: str = "", limit: int = 8, entity_id: str | None = None):
    """Vista debug del RAG híbrido — solo owner/admin con token MCP."""
    if not _ops_authorized(request):
        return JSONResponse({"ok": False, "error": "rag_preview_unauthorized"}, status_code=403)
    from raphiia_openai import hybrid_context

    result = hybrid_context.hybrid_search(q, limit=max(1, min(limit, 20)), entity_id=entity_id)
    chunks = []
    for hit in (result.get("results") or [])[:limit]:
        chunks.append(
            {
                "source": hit.get("source"),
                "score": hit.get("score"),
                "title": hit.get("title"),
                "text": (hit.get("text") or "")[:600],
                "url": hit.get("url"),
                "project": hit.get("project"),
                "memory_id": hit.get("memory_id"),
            }
        )
    return {
        "ok": bool(result.get("ok", True)),
        "query": q,
        "count": len(chunks),
        "qdrant": result.get("qdrant"),
        "chunks": chunks,
        "sources": sorted({c.get("source") for c in chunks if c.get("source")}),
    }


@router.get("/daily-memory", response_class=HTMLResponse)
def daily_memory_panel():
    """Panel shell only; private data is fetched through a protected endpoint."""
    path = Path(__file__).resolve().parent / "static" / "daily_memory_review.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/api/ops/daily-memory/review")
def daily_memory_review(request: Request, status: str = "active", limit: int = 50):
    if not _memory_review_authorized(request):
        return JSONResponse({"ok": False, "error": "memory_review_unauthorized"}, status_code=403)
    from raphiia_openai import daily_memory

    return daily_memory.review_queue(actor="RAFAEL", status=status, limit=limit)


@router.post("/api/ops/daily-memory/correct")
async def daily_memory_correct(request: Request):
    if not _memory_review_authorized(request):
        return JSONResponse({"ok": False, "error": "memory_review_unauthorized"}, status_code=403)
    from raphiia_openai import daily_memory

    payload = await request.json()
    return daily_memory.correct_memory({**payload, "actor": "RAFAEL"})


@router.post("/api/ops/daily-memory/forget")
async def daily_memory_forget(request: Request):
    if not _memory_review_authorized(request):
        return JSONResponse({"ok": False, "error": "memory_review_unauthorized"}, status_code=403)
    from raphiia_openai import daily_memory

    payload = await request.json()
    return daily_memory.forget_memory({**payload, "actor": "RAFAEL"})


@router.post("/api/ops/daily-memory/resolve-pending")
async def daily_memory_resolve_pending(request: Request):
    if not _memory_review_authorized(request):
        return JSONResponse({"ok": False, "error": "memory_review_unauthorized"}, status_code=403)
    from raphiia_openai import daily_memory

    payload = await request.json()
    return daily_memory.resolve_pending_item({**payload, "actor": "RAFAEL"})


class ApproveServiceBody(BaseModel):
    name: str = ""
    owner: str = "RAFAEL"


@router.get("/api/ops/fleet")
def ops_fleet():
    """Vista unificada Intel (.4) + AMD (.5) — servicios, GPU, salud."""
    from raphiia_openai.fleet_overview import fleet_overview

    return fleet_overview()


@router.get("/api/ops/node")
def ops_node():
    from raphiia_openai import portal_bridge

    return portal_bridge.detect_node()


@router.get("/api/ops/gpu")
def ops_gpu():
    from raphiia_openai import portal_bridge

    return portal_bridge.gpu_resources()


@router.get("/api/ops/version")
def ops_version():
    from raphiia_openai import portal_bridge

    return portal_bridge.version_info()


@router.get("/api/ops/vllm")
def ops_vllm():
    from raphiia_openai import portal_bridge

    return portal_bridge.vllm_models_info()


@router.get("/api/ops/unified-services")
def ops_unified_services():
    from raphiia_openai import portal_bridge

    return portal_bridge.unified_services_list()


@router.get("/api/ops/processes")
def ops_processes():
    from raphiia_openai import portal_bridge

    return portal_bridge.processes_overview()


@router.get("/api/ops/health")
def ops_health():
    return {"ok": True, "service": "ralfia-ops-panel", "url": OPS_PANEL_PUBLIC_URL}


@router.get("/api/ops/overview")
def ops_overview():
    mcp = mcp_version()
    service_registry.seed_defaults(force=False)
    service_registry.maybe_run_stale_checks()
    services = service_registry.list_services(visible_only=True, limit=50)
    tasks = orchestration_store.list_tasks(limit=15)
    activity = orchestration_store.list_recent_activity(limit=15)
    changes = mongo_store.list_recent_changes(limit=10)
    from raphiia_openai import handoff_detector

    handoffs = handoff_detector.detect_missing_handoff(hours=72)
    pending = service_registry.list_services(visible_only=False, status="pending_review")
    svc_results = [
        {
            "service_id": s.get("service_id"),
            "name": s.get("name"),
            "status": s.get("status", "unknown"),
            "port": s.get("port"),
            "last_error": s.get("last_error", ""),
        }
        for s in services.get("services", [])
    ]
    return {
        "ok": True,
        "mcp": mcp,
        "catalog_version": tool_catalog.MCP_VERSION,
        "portal_legacy": PORTAL_LEGACY_URL,
        "services": {"results": svc_results, "summary": {}},
        "tasks": tasks,
        "activity": activity,
        "recent_changes": changes,
        "missing_handoffs": handoffs,
        "pending_review": pending,
    }


@router.post("/api/ops/watchdog/run")
def ops_watchdog_run():
    from raphiia_openai.recovery_agent import run_health_watch

    result = service_registry.run_all_checks()
    hw = run_health_watch(notify=True, trigger="watchdog")
    result["health_watch"] = hw
    return result


@router.post("/api/ops/recovery/verify")
def ops_recovery_verify():
    from raphiia_openai.recovery_agent import run_post_restart_verify

    return run_post_restart_verify(trigger="manual_panel")


@router.post("/api/ops/recovery/drill")
def ops_recovery_drill():
    from raphiia_openai.recovery_agent import run_recovery_drill

    return run_recovery_drill(notify=True)


@router.post("/api/ops/registry/approve/{service_id}")
def ops_registry_approve(service_id: str, body: ApproveServiceBody | None = None):
    body = body or ApproveServiceBody()
    return service_registry.approve_discovered_service(service_id, name=body.name, owner=body.owner)


class CreateProjectBody(BaseModel):
    name: str
    slug: str = ""
    project_type: str = "web"
    port: int | None = None
    start_command: str = ""
    hackathon_name: str = ""
    hackathon_url: str = ""
    health_endpoint: str = ""
    path: str = ""


class ActivateProjectBody(BaseModel):
    start_command: str
    port: int | None = None
    health_endpoint: str = ""


class ConfigPatchBody(BaseModel):
    values: dict[str, str] = {}


class EntityPatchBody(BaseModel):
    name: str | None = None
    linkedin_author_urn: str | None = None
    linkedin_publish_as: str | None = None
    notes: str | None = None
    status: str | None = None


@router.get("/api/ops/config")
def ops_config_get():
    from raphiia_openai import config_store

    return {"ok": True, **config_store.status_catalog()}


@router.patch("/api/ops/config")
def ops_config_patch(body: ConfigPatchBody):
    from raphiia_openai import config_store

    return config_store.set_values(body.values, updated_by="PANEL")


@router.get("/api/ops/entities")
def ops_entities_list():
    from raphiia_openai import config_store

    return {"ok": True, "entities": config_store.list_entities_editorial()}


@router.patch("/api/ops/entities/{entity_id}")
def ops_entity_patch(entity_id: str, body: EntityPatchBody):
    from raphiia_openai import config_store

    return config_store.patch_entity(
        entity_id,
        body.model_dump(exclude_none=True),
        updated_by="PANEL",
    )


@router.get("/api/ops/cockpit")
def ops_cockpit():
    from raphiia_openai import service_control

    return service_control.cockpit_status()


class ServiceRestartBody(BaseModel):
    unit: str = ""
    scope: str = "user"
    container: str = ""


@router.post("/api/ops/services/restart")
def ops_service_restart(body: ServiceRestartBody):
    from raphiia_openai import service_control

    if body.container.strip():
        allowed = {s["container"] for s in service_control.DOCKER_COCKPIT_SERVICES if s.get("container")}
        name = body.container.strip()
        if name not in allowed:
            return {"ok": False, "error": f"contenedor no permitido: {name}"}
        result = service_control.restart_docker(name)
        return {"ok": result.get("ok"), **result}

    unit = body.unit.strip()
    scope = body.scope.strip() or "user"
    allowed = {s["unit"] for s in service_control.COCKPIT_SERVICES if s.get("unit")}
    allowed |= {s["unit"] for s in service_control.DOCKER_COCKPIT_SERVICES if s.get("unit")}
    allowed |= {spec["unit"] for specs in service_control.CONFIG_RESTART_MAP.values() for spec in specs}
    if unit not in allowed:
        return {"ok": False, "error": f"unidad no permitida: {unit}"}
    result = service_control.restart_unit(unit, scope=scope)
    return {"ok": result.get("ok"), **result}


@router.post("/api/ops/projects/create")
def ops_project_create(body: CreateProjectBody):
    from raphiia_openai import project_lifecycle

    return project_lifecycle.create_project(
        name=body.name,
        slug=body.slug or None,
        project_type=body.project_type,
        port=body.port,
        start_command=body.start_command,
        hackathon_name=body.hackathon_name,
        hackathon_url=body.hackathon_url,
        health_endpoint=body.health_endpoint,
        adopt_path=body.path,
        created_by="PANEL",
    )


@router.post("/api/ops/projects/{slug}/activate")
def ops_project_activate(slug: str, body: ActivateProjectBody):
    from raphiia_openai import project_lifecycle

    return project_lifecycle.activate_project(
        slug=slug,
        start_command=body.start_command,
        port=body.port,
        health_endpoint=body.health_endpoint,
    )


@router.post("/api/ops/projects/adopt-all")
def ops_projects_adopt_all():
    from raphiia_openai import project_lifecycle

    return project_lifecycle.adopt_legacy_stack(created_by="PANEL")


@router.get("/api/ops/projects/verify")
def ops_projects_verify():
    from raphiia_openai import project_lifecycle

    return project_lifecycle.verify_projects()


@router.get("/api/ops/projects")
def ops_projects_list():
    from raphiia_openai.settings import COL_RALFIA_PROJECTS

    db = mongo_store.get_db()
    rows = list(db[COL_RALFIA_PROJECTS].find({}, {"_id": 0}).sort("slug", 1))
    return {"ok": True, "count": len(rows), "projects": rows}


@router.post("/api/ops/discovery/run")
def ops_discovery_run():
    return service_registry.discover_new_services()


@router.get("/api/ops/pending")
def ops_pending():
    return service_registry.list_services(visible_only=False, status="pending_review", limit=50)


@router.get("/api/ops/services")
def ops_services():
    service_registry.maybe_run_stale_checks()
    return service_registry.list_services(visible_only=True)


@router.get("/api/ops/tasks")
def ops_tasks(status: str | None = None, agent: str | None = None):
    return orchestration_store.list_tasks(status=status, agent=agent)


@router.get("/api/ops/activity")
def ops_activity(agent: str | None = None):
    return orchestration_store.list_recent_activity(agent=agent)


@router.post("/api/whatsapp/evolution/webhook")
async def whatsapp_evolution_webhook(payload: dict[str, Any], request: Request):
    from raphiia_openai import whatsapp_automation

    secret_path = Path("/home/rlopez/projects/raphiia-openai/data/whatsapp_webhook_secret")
    expected = secret_path.read_text(encoding="utf-8").strip() if secret_path.is_file() else ""
    supplied = request.headers.get("X-RalfIA-Webhook-Secret", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return JSONResponse({"ok": False, "error": "invalid_webhook_signature"}, status_code=401)
    return whatsapp_automation.ingest_inbound_event(payload)


@router.get("/api/whatsapp/reminders")
def whatsapp_list_reminders(limit: int = 20):
    from raphiia_openai import whatsapp_automation

    return whatsapp_automation.list_reminders(limit=limit)


@router.post("/api/whatsapp/reminders/run")
def whatsapp_run_reminders():
    from raphiia_openai import whatsapp_automation

    return whatsapp_automation.run_due_reminders()


@router.get("/api/ops/feed")
def ops_feed():
    from raphiia_openai.settings import COORD_ROOT

    feed = COORD_ROOT / "HUB" / "feed.jsonl"
    lines = feed.read_text(encoding="utf-8").strip().splitlines()[-30:] if feed.is_file() else []
    return {"ok": True, "lines": lines}


@router.get("/api/accounting/payables")
def accounting_list_payables(entity_id: str | None = None, status: str | None = None, limit: int = 50):
    from raphiia_openai.operational import accounting_store

    return accounting_store.list_payables(entity_id=entity_id, status=status, limit=limit)


@router.get("/api/accounting/payables/due")
def accounting_payables_due(entity_id: str | None = None, days_ahead: int = 14, limit: int = 50):
    from raphiia_openai.operational import accounting_store

    return accounting_store.list_payables_due(entity_id=entity_id, days_ahead=days_ahead, limit=limit)


@router.get("/api/accounting/summary")
def accounting_summary_api(entity_id: str | None = None, period: str | None = None):
    from raphiia_openai.operational import accounting_store

    return accounting_store.accounting_summary(entity_id=entity_id, period=period)


@router.get("/api/accounting/receivables/open")
def accounting_receivables_open(entity_id: str | None = None, limit: int = 50):
    from raphiia_openai.operational import accounting_store

    return accounting_store.list_receivables_open(entity_id=entity_id, limit=limit)


@router.post("/api/accounting/payables/draft")
def accounting_create_payable_draft(body: dict[str, Any]):
    from raphiia_openai.operational import accounting_store

    return accounting_store.create_payable_draft(body)


@router.post("/api/accounting/payables/upsert")
def accounting_upsert_payable(body: dict[str, Any]):
    from raphiia_openai.operational import accounting_store

    return accounting_store.upsert_payable(body)


@router.post("/api/accounting/payables/pay")
def accounting_pay(body: dict[str, Any]):
    from raphiia_openai.operational import accounting_store

    body.setdefault("receive_inventory", body.get("receive_inventory", False))
    return accounting_store.record_payment(body)


@router.post("/api/procurement/draft")
def procurement_create_draft(body: dict[str, Any]):
    from raphiia_openai.operational import procurement_store

    return procurement_store.create_purchase_draft(body)


@router.post("/api/procurement/upsert")
def procurement_upsert(body: dict[str, Any]):
    from raphiia_openai.operational import procurement_store

    return procurement_store.upsert_purchase(body)


@router.get("/api/procurement/open")
def procurement_open(entity_id: str | None = None, limit: int = 50):
    from raphiia_openai.operational import procurement_store

    return procurement_store.list_purchases_open(entity_id=entity_id, limit=limit)


@router.post("/api/inventory/receive")
def inventory_receive(body: dict[str, Any]):
    from raphiia_openai.operational import inventory_store

    return inventory_store.receive_goods(body)


@router.get("/api/inventory/items")
def inventory_items(entity_id: str | None = None, limit: int = 100):
    from raphiia_openai.operational import inventory_store

    return inventory_store.list_inventory(entity_id=entity_id, limit=limit)


@router.post("/api/accounting/receivables/draft")
def accounting_create_receivable(body: dict[str, Any]):
    from raphiia_openai.operational import accounting_store

    return accounting_store.create_receivable_draft(body)


@router.post("/api/accounting/receivables/collect")
def accounting_collect(body: dict[str, Any]):
    from raphiia_openai.operational import accounting_store

    return accounting_store.record_collection(body)


@router.post("/api/accounting/whatsapp-parse")
def accounting_whatsapp_parse(body: dict[str, Any]):
    from raphiia_openai.operational import accounting_store

    message = str(body.get("message") or "")
    entity_id = str(body.get("entity_id") or "ent_pcdoctor")
    return accounting_store.create_payable_from_whatsapp(message, entity_id=entity_id)


@router.get("/api/whatsapp/status")
def whatsapp_status():
    from raphiia_openai import whatsapp_mcp_bridge

    return whatsapp_mcp_bridge.get_whatsapp_status(dual=True)


@router.get("/api/contacts/search")
def contacts_search(q: str = "", limit: int = 20):
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.list_contacts(query=q or None, limit=limit)


@router.get("/api/contacts/marketing-pool")
def contacts_marketing_pool(
    q: str = "",
    limit: int = 50,
    skip: int = 0,
    include_groups: bool = False,
):
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.list_marketing_pool(
        query=q or None,
        limit=limit,
        skip=skip,
        include_groups=include_groups,
    )


@router.get("/api/contacts/marketing-pool/stats")
def contacts_marketing_pool_stats():
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.marketing_pool_stats()


@router.post("/api/contacts/marketing-pool/index-qdrant")
def contacts_marketing_pool_index_qdrant(limit: int | None = None, include_groups: bool = True):
    from raphiia_openai import contact_index

    return contact_index.index_chip_contacts_to_qdrant(limit=limit, include_groups=include_groups)


@router.get("/api/docvault/health")
def docvault_health_api():
    from raphiia_openai import docvault_store

    return docvault_store.docvault_health()


@router.get("/api/docvault/search")
def docvault_search_api(q: str = "", limit: int = 8, expediente: str = ""):
    from raphiia_openai import docvault_store

    return docvault_store.search_docvault(q, limit=limit, expediente=expediente or None)


@router.get("/api/docvault/document/{identifier}")
def docvault_document_api(identifier: str):
    from raphiia_openai import docvault_store

    return docvault_store.get_document(identifier)


@router.post("/api/notion/webhook")
async def notion_webhook_api(request: Request):
    from raphiia_openai import notion_webhook

    raw = await request.body()
    sig = request.headers.get("X-Notion-Signature")
    result = notion_webhook.handle_notion_webhook(raw, signature=sig)
    status = int(result.pop("http_status", 200))
    from fastapi import Response
    import json

    return Response(content=json.dumps(result), status_code=status, media_type="application/json")


@router.get("/api/notion/webhook/setup")
def notion_webhook_setup_api():
    from raphiia_openai import notion_webhook

    return notion_webhook.get_notion_webhook_setup()


@router.get("/api/notion/webhook/pending")
def notion_webhook_pending_api():
    from raphiia_openai import notion_webhook

    return notion_webhook.get_pending_verification_token()


@router.get("/api/notion/schema")
def notion_schema_api():
    from raphiia_openai import notion_bridge

    return notion_bridge.get_notion_schema_blueprint()


@router.get("/api/notion/preview")
def notion_preview_api(limit: int = 50):
    from raphiia_openai import notion_bridge

    return notion_bridge.preview_notion_sync(limit=limit)


@router.get("/api/notion/status")
def notion_status_api():
    from raphiia_openai import notion_bridge

    return notion_bridge.get_notion_status()


@router.get("/api/notion/sync-log")
def notion_sync_log_api(limit: int = 20):
    from raphiia_openai import notion_bridge

    return notion_bridge.get_notion_sync_log(limit=limit)


@router.get("/accounting/ui")
def accounting_ui():
    from pathlib import Path

    from fastapi.responses import HTMLResponse

    path = Path(__file__).resolve().parent / "static" / "accounting_ui.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/funding/ui")
def funding_ui():
    from pathlib import Path

    from fastapi.responses import HTMLResponse

    path = Path(__file__).resolve().parent / "static" / "funding_ui.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/api/ops/credits")
def api_list_credits():
    from raphiia_openai.operational import credits_store
    return {"ok": True, "applications": credits_store.list_applications()}


@router.post("/api/ops/credits")
def api_create_credit(body: dict[str, Any]):
    from raphiia_openai.operational import credits_store
    return credits_store.create_application(body)


@router.get("/api/ops/credits/{app_id}")
def api_get_credit(app_id: str):
    from raphiia_openai.operational import credits_store
    res = credits_store.get_application(app_id)
    if not res:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Application not found")
    return res


@router.post("/api/ops/credits/{app_id}/link-email")
def api_link_email(app_id: str, mail_id: str):
    from raphiia_openai.operational import credits_store
    return credits_store.link_email_to_application(app_id, mail_id)


@router.patch("/api/ops/credits/{app_id}")
def api_update_credit(app_id: str, body: dict[str, Any]):
    from raphiia_openai.operational import credits_store
    return credits_store.update_application(app_id, body)


class GenerateAIBody(BaseModel):
    prompt: str = ""


@router.post("/api/ops/credits/{app_id}/generate-ai")
def api_generate_ai(app_id: str, body: GenerateAIBody):
    from raphiia_openai.operational import credits_store
    app = credits_store.get_application(app_id)
    if not app:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Application not found")

    notes = app.get("notes", "")
    program_name = app.get("program_name", "")
    draft = credits_store.generate_ai_draft(program_name, notes, body.prompt)
    return {"ok": True, "draft": draft}




def create_ops_app():
    """Standalone API-only (legacy). Panel UI = portal :2002."""
    from fastapi import FastAPI

    app = FastAPI(title="Ralphi IA Ops API", version="1.0.0")
    app.include_router(router)

    @app.get("/")
    def _root():
        return RedirectResponse(OPS_PANEL_PUBLIC_URL)

    return app
