"""Servidor MCP RaphiIA para ChatGPT Connectors."""

from __future__ import annotations

import json
import hashlib
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, TypedDict
from datetime import datetime, timezone

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from raphiia_openai.auth_middleware import ApiKeyMiddleware
from raphiia_openai import quoteops_mcp_bridge
from raphiia_openai import coordination_docs, dev_swarm_scheduler, dev_swarm_watchdog, discord_interaction_gateway, document_vault, editorial_media_upload, editorial_publish, editorial_store, external_repair_agent, funding_registry as funding_registry_module, image_gen, linkedin_client, local_discord_plane, local_execution_plane, local_filesystem_plane, local_github_plane, local_gitlab_plane, local_model_manager, local_model_router, mcp_diagnostics, mongo_store, project_runtime_registry
from raphiia_openai.operational import accounting_store, inventory_store, pcdoctor_store, party_store, procurement_store
from raphiia_openai.settings import (
    GOOGLE_API_KEY,
    MCP_API_KEY,
    MCP_DISPLAY_NAME,
    MCP_HOST,
    MCP_PORT,
    MCP_PUBLIC_URL,
    MCP_SERVER_VERSION,
    OAUTH_ISSUER,
    RAPHI_IA_OPENAI_PORT,
    RAPHI_IA_PUBLIC_URL,
)

class InfrastructureStatusToolResult(TypedDict, total=False):
    ok: bool
    generated_at: str
    servers: list[dict[str, Any]]
    partial: bool
    secret_policy: str


class OpsTaskToolResult(TypedDict, total=False):
    ok: bool
    task: dict[str, Any]
    task_id: str
    correlation_id: str
    error: str


mcp = FastMCP(
    MCP_DISPLAY_NAME,
    version=MCP_SERVER_VERSION,
    instructions=(
        "Puente MCP entre ChatGPT y MongoDB pcdoctor_swarm + memoria ai_coordination. "
        "Al iniciar sesión SIEMPRE (sin que Rafael pegue nada): get_coordination_live() → read_coordination_file('HUB/ESTADO_VIVO.md') → read_coordination_file('HUB/RUNBOOK_COTIZACION_WHATSAPP.md') → bootstrap_context(). "
        "Cotizar: list_mcp_tool_profiles() perfil quoter; seguir RUNBOOK HUB. "
        "Si revision subió, releer mandatory_reads. Órdenes: fila en Notion DB RalfIA Coordination O create_ops_task. "
        "La ruta canónica de ChatGPT es chatgpt/INBOX.md con espejo ChatGPT/INBOX.md. "
        "Si file y Mongo divergen, la verdad de entrega vive en Mongo ralfia_agent_messages y luego se resynca Markdown. "
        "Usa search/fetch para Mongo, read_coordination_file/search_coordination_docs para docs del servidor. "
        "Agentes — lenguaje natural: resolve_agent(mensaje) → route_agent_request(mensaje, auto_execute=true). Catálogo: get_agent_catalog(). "
        "Orquestador principal AG-25: ralfia_dispatch(mensaje, auto_execute=true). "
        "dispatch_local_agent ejecuta por defecto (dry_run=true solo preview). "
        "Al cerrar: log_coordination_event(agent=CHATGPT) + save_chatgpt_note o chatgpt/OUTBOX vía nota. "
        "No hay OpenAI API en el servidor."
    ),
)

if MCP_API_KEY:
    mcp.add_middleware(ApiKeyMiddleware(MCP_API_KEY))



# --- MOD-A2A (Agent2Agent transport over durable InnerOS control plane) ---

@mcp.tool
def a2a_status() -> dict[str, Any]:
    """A2A: estado del bridge, protocolo, SDK y agentes publicados."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.status()


@mcp.tool
def a2a_agent_cards() -> dict[str, Any]:
    """A2A: Agent Cards de los roles disponibles en InnerOS."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.agent_cards()


@mcp.tool
def a2a_dispatch(
    agent_id: str,
    title: str,
    body: str,
    correlation_id: str = "",
    context_id: str = "",
    priority: str = "p0",
    related_project: str = "inneros",
    dry_run: bool = False,
    protocol_task_id: str = "",
) -> dict[str, Any]:
    """A2A: delega trabajo durable sin saltarse RACB ni ops_tasks."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.dispatch(
        agent_id=agent_id,
        title=title,
        body=body,
        correlation_id=correlation_id,
        context_id=context_id,
        priority=priority,
        related_project=related_project or None,
        dry_run=dry_run,
        protocol_task_id=protocol_task_id,
    )


@mcp.tool
def a2a_task_status(a2a_task_id: str) -> dict[str, Any]:
    """A2A: proyecta estado RACB/Mongo y artifacts de una tarea A2A."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.task_status(a2a_task_id)

@mcp.resource("resource://RalfIA_MCP", name=MCP_DISPLAY_NAME, mime_type="application/json")
async def ralfia_mcp_manifest() -> dict[str, Any]:
    """Manifiesto vivo de herramientas y recursos expuestos por este servidor MCP."""
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    version = mcp_diagnostics.mcp_version()
    resource_uris = []
    for resource in resources:
        uri = getattr(resource, "uri", None) or getattr(resource, "name", None) or str(resource)
        resource_uris.append(str(uri))
    return {
        "ok": True,
        "name": MCP_DISPLAY_NAME,
        "service": MCP_DISPLAY_NAME,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "public_mcp_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
        "oauth_issuer": OAUTH_ISSUER,
        "auth_required": bool(MCP_API_KEY),
        "catalog_version": version.get("catalog_version"),
        "manifest_hash": version.get("manifest_hash"),
        "tool_count": len(tools),
        "tools": [tool.name for tool in tools],
        "resource_count": len(resources),
        "resources": resource_uris,
        "notes": [
            "Si ChatGPT ve un conjunto antiguo, recrear el connector o refrescar la app.",
            "Las tools reales las publica FastMCP en /mcp; este recurso ayuda al descubrimiento.",
        ],
    }


@mcp.tool
def save_message(conversation_id: str, role: str, content: str) -> dict[str, Any]:
    """Guarda un turno de conversación en raphiia_openai_messages."""
    doc = mongo_store.append_message(conversation_id=conversation_id, role=role, content=content)
    return {"ok": True, "saved": doc}


@mcp.tool
def create_agent_message(
    from_agent: str,
    target_agent: str,
    title: str,
    body: str,
    priority: str = "normal",
    correlation_id: str | None = None,
    message_type: str = "message",
    payload: dict[str, Any] | None = None,
    reply_to: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Canal único; instrucciones P0/P1/OPS se normalizan automáticamente a ops_task."""
    from raphiia_openai import coordination_ingest

    return coordination_ingest.ingest_agent_message(
        from_agent=from_agent,
        target_agent=target_agent,
        title=title,
        body=body,
        priority=priority,
        correlation_id=correlation_id,
        message_type=message_type,
        payload=payload,
        reply_to=reply_to,
        idempotency_key=idempotency_key,
    )


@mcp.tool
def ack_agent_message(message_id: str, agent: str) -> dict[str, Any]:
    """RACB: confirma lectura de un mensaje sin marcar la tarea terminada."""
    from raphiia_openai.memory import agent_messages as _am

    return _am.ack_agent_message(message_id=message_id, agent=agent)


@mcp.tool
def poll_agent_inbox(agent: str, limit: int = 20, auto_ack: bool = True) -> dict[str, Any]:
    """RACB: consulta el INBOX y genera ACK de lectura automático para lo entregado."""
    from raphiia_openai.memory import agent_messages as _am

    return _am.poll_agent_inbox(agent=agent, limit=limit, auto_ack=auto_ack)


@mcp.tool
def save_idea(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Guarda una idea titulada y crea un borrador listo para revisión."""
    idea = mongo_store.save_idea(title=title, body=body, tags=tags)
    try:
        from raphiia_openai import dev_backlog

        dev_backlog.capture_backlog_item(
            title=title,
            body=body,
            status="discussed",
            kind="idea",
            source_agent="CHATGPT",
            tags=tags,
            metadata={"legacy_idea_id": idea.get("_id")},
        )
    except Exception:
        pass
    draft = mongo_store.save_pipeline_draft(
        channel="linkedin",
        markdown=body,
        title=title,
        status="ready_for_review",
        metadata={
            "source": "chatgpt_idea",
            "idea_id": idea.get("_id"),
            "tags": tags or [],
        },
    )
    return {"ok": True, "idea": idea, "draft": draft}


@mcp.tool
def search(query: str, limit: int = 10, collection: str | None = None) -> dict[str, Any]:
    """Busca ideas, mensajes bridge, pipeline editorial o clientes por texto."""
    results = mongo_store.search(query=query, limit=limit, collection=collection)
    return {"ok": True, "count": len(results), "results": results}


@mcp.tool
def hybrid_search(
    query: str,
    limit: int = 12,
    entity_id: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Búsqueda híbrida: memoria Rafael + Qdrant (Notion/Drive) + ops Mongo."""
    from raphiia_openai import hybrid_context

    return hybrid_context.hybrid_search(query, limit=limit, entity_id=entity_id, project=project)


@mcp.tool
def get_rafael_context(query: str | None = None, entity_id: str | None = None, max_chars: int = 12000) -> dict[str, Any]:
    """Contexto completo de Rafael listo para LLM (proyectos, memoria, RAG, pendientes)."""
    from raphiia_openai import hybrid_context

    return hybrid_context.get_rafael_context(query=query, entity_id=entity_id, max_chars=max_chars)


@mcp.tool
def get_unified_stack_status() -> dict[str, Any]:
    """Estado memoria unificada: Mongo, Qdrant, nodos, failover."""
    from raphiia_openai import hybrid_context, mcp_fleet
    from raphiia_openai.notifications.evolution_client import dual_whatsapp_status

    return {
        "ok": True,
        "mongo": mongo_store.mongo_connection_info(),
        "mongo_ping": mongo_store.ping_mongo(),
        "qdrant": hybrid_context.qdrant_health(),
        "whatsapp": dual_whatsapp_status(),
        "summary": mongo_store.get_context_summary(),
        "mcp_fleet": mcp_fleet.fleet_status(),
    }


@mcp.tool
def get_mcp_fleet_status() -> dict[str, Any]:
    """Estado dual-nodo MCP Intel+AMD: versiones, salud y routing por capability."""
    from raphiia_openai import mcp_fleet

    return mcp_fleet.fleet_status(force_probe=True)


@mcp.tool
def reconcile_runtime_state(dry_run: bool = True) -> dict[str, Any]:
    """AG-40: reconciliación read-only runtime .4/.5 — falsos DOWN vs degradación real."""
    from raphiia_openai.agents import ag40_runtime_reconciler

    return ag40_runtime_reconciler.reconcile_runtime_state(dry_run=dry_run)


@mcp.tool
def run_health_watch(notify: bool = False) -> dict[str, Any]:
    """AG-31: snapshot cockpit/registry y transiciones up/down (sin reiniciar servicios)."""
    from raphiia_openai.agents import ag31_service_recovery_agent as ag31

    return ag31.run_health_watch(notify=notify, trigger="mcp_cursor")


@mcp.tool
def list_ralphia_agents(limit: int = 50) -> dict[str, Any]:
    """Lista agentes AG-xx del pool con nombres amigables del catálogo."""
    from raphiia_openai.agents import agent_catalog, registry

    pool = registry.list_agents()[: max(1, min(limit, 200))]
    enriched = []
    for row in pool:
        aid = row.get("agent_id", "")
        cat = agent_catalog.AGENT_CATALOG.get(aid, {})
        enriched.append({
            **row,
            "display_name": cat.get("display_name") or row.get("name"),
            "role": cat.get("role", ""),
            "aliases": cat.get("aliases", []),
            "runtime_status": cat.get("status", "unknown"),
            "how_to_call": cat.get("task_kind") or cat.get("entry_tool"),
        })
    return {"ok": True, "count": len(enriched), "agents": enriched, "catalog": "get_agent_catalog()"}


@mcp.tool
def list_peer_ops_services() -> dict[str, Any]:
    """AG-41: servicios allowlisted para peer ops (.4/.5)."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.list_peer_ops_services()


@mcp.tool
def peer_ops_snapshot(node: str = "") -> dict[str, Any]:
    """AG-41: snapshot status de servicios allowlisted en Intel/AMD."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_ops_snapshot(node or None)


@mcp.tool
def peer_ops_status(service_id: str, node: str = "primary") -> dict[str, Any]:
    """AG-41: status de un servicio allowlisted (mcp, portal, evolution, …)."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_ops_status(service_id, node)


@mcp.tool
def peer_ops_action(
    service_id: str,
    node: str = "primary",
    action: str = "restart",
    dry_run: bool = False,
) -> dict[str, Any]:
    """AG-41: start/restart/recover servicio allowlisted en .4 o .5."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_ops_action(service_id, node, action, dry_run=dry_run)


@mcp.tool
def peer_ops_logs(service_id: str, node: str = "primary", lines: int = 30) -> dict[str, Any]:
    """AG-41: logs recientes (journalctl/docker, máx 50 líneas)."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_ops_logs(service_id, node, lines)


@mcp.tool
def peer_net_interfaces(node: str = "amd") -> dict[str, Any]:
    """AG-41: lista interfaces del peer sin secretos ni mutación."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_net_interfaces(node=node)


@mcp.tool
def peer_wifi_scan(node: str = "amd", interface: str = "") -> dict[str, Any]:
    """AG-41: escanea SSIDs desde una interfaz Wi-Fi allowlisted."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_wifi_scan(node=node, interface=interface)


@mcp.tool
def peer_wifi_status(node: str = "amd", interface: str = "") -> dict[str, Any]:
    """AG-41: estado Wi-Fi/IP/ruta sin exponer credenciales."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_wifi_status(node=node, interface=interface)


@mcp.tool
def peer_route_check(node: str = "amd") -> dict[str, Any]:
    """AG-41: confirma que la ruta LAN/default del peer sigue intacta."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_route_check(node=node)


@mcp.tool
def peer_secret_store_wifi(node: str, ssid: str, secret: str, approval_id: str) -> dict[str, Any]:
    """AG-41: guarda PSK Wi-Fi server-side y devuelve solo credential_ref."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_secret_store_wifi(node=node, ssid=ssid, secret=secret, approval_id=approval_id)


@mcp.tool
def peer_wifi_connect(
    node: str = "amd",
    interface: str = "",
    ssid: str = "",
    credential_ref: str = "",
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """AG-41: conecta Wi-Fi dedicado con approval_id; dry_run por defecto."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_wifi_connect(
        node=node,
        interface=interface,
        ssid=ssid,
        credential_ref=credential_ref,
        approval_id=approval_id,
        dry_run=dry_run,
    )


@mcp.tool
def peer_wifi_disconnect(node: str = "amd", interface: str = "", approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-41: desconecta solo una interfaz Wi-Fi dedicada; dry_run por defecto."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_wifi_disconnect(node=node, interface=interface, approval_id=approval_id, dry_run=dry_run)


@mcp.tool
def peer_wifi_forget(node: str = "amd", connection_id: str = "", approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-41: olvida una conexión Wi-Fi allowlisted; dry_run por defecto."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_wifi_forget(node=node, connection_id=connection_id, approval_id=approval_id, dry_run=dry_run)


@mcp.tool
def peer_package_status(node: str = "primary", packages: list[str] | str | None = None) -> dict[str, Any]:
    """AG-41: estado de paquetes allowlisted en node=primary|amd."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_package_status(node=node, packages=packages)


@mcp.tool
def peer_package_install(node: str = "primary", packages: list[str] | str | None = None, approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-41: instala solo paquetes allowlisted con approval_id; dry_run por defecto."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_package_install(node=node, packages=packages, approval_id=approval_id, dry_run=dry_run)


@mcp.tool
def peer_package_remove(node: str = "primary", packages: list[str] | str | None = None, approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-41: remueve solo paquetes allowlisted con approval_id; dry_run por defecto."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_package_remove(node=node, packages=packages, approval_id=approval_id, dry_run=dry_run)


@mcp.tool
def peer_hardware_discovery(node: str = "primary") -> dict[str, Any]:
    """AG-41: inventario read-only de hardware/dispositivos del nodo."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_hardware_discovery(node=node)


@mcp.tool
def peer_python_runtime(
    node: str = "primary",
    project_path: str = "",
    project_id: str = "",
    repo: str = "",
    action: str = "status",
    requirements: str = "requirements.txt",
    target: str = ".",
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """AG-41: venv/pip/test/compileall dentro de proyecto allowlisted."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_python_runtime(node=node, project_path=project_path, project_id=project_id, repo=repo, action=action, requirements=requirements, target=target, approval_id=approval_id, dry_run=dry_run)


@mcp.tool
def peer_user_service(
    node: str = "primary",
    action: str = "status",
    service_name: str = "",
    project_path: str = "",
    project_id: str = "",
    repo: str = "",
    unit_content: str = "",
    approval_id: str = "",
    dry_run: bool = True,
    lines: int = 50,
) -> dict[str, Any]:
    """AG-41: lifecycle de systemd --user para servicios de proyectos autorizados."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_user_service(node=node, action=action, service_name=service_name, project_path=project_path, project_id=project_id, repo=repo, unit_content=unit_content, approval_id=approval_id, dry_run=dry_run, lines=lines)


@mcp.tool
def peer_node_capability_matrix() -> dict[str, Any]:
    """AG-41: matriz simétrica de capacidades .4/.5 y excepciones físicas."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_node_capability_matrix()


@mcp.tool
def peer_host_ops_policy() -> dict[str, Any]:
    """AG-41: contrato owner_dev/host_ops normal/high-impact/destructive."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_host_ops_policy()


@mcp.tool
def peer_observability_snapshot(node: str = "primary") -> dict[str, Any]:
    """AG-41: snapshot read-only de puertos, procesos, disco, memoria y contenedores."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_observability_snapshot(node=node)


@mcp.tool
def peer_project_fs(
    node: str = "primary",
    project_path: str = "",
    project_id: str = "",
    repo: str = "",
    action: str = "stat",
    relative_path: str = ".",
    dest_relative_path: str = "",
    content: str = "",
    mode: str = "",
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """AG-41: filesystem seguro dentro de roots/proyectos confiables; sin delete destructivo."""
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    return ag41.peer_project_fs(
        node=node,
        project_path=project_path,
        project_id=project_id,
        repo=repo,
        action=action,
        relative_path=relative_path,
        dest_relative_path=dest_relative_path,
        content=content,
        mode=mode,
        approval_id=approval_id,
        dry_run=dry_run,
    )


@mcp.tool
def project_runtime_register(project_id: str, repo: str = "", project_path: str = "", actor: str = "chatgpt") -> dict[str, Any]:
    """Project Runtime Registry: registra project_id/repo y paths confiables por nodo."""
    return project_runtime_registry.register_project(project_id=project_id, repo=repo or None, project_path=project_path, actor=actor)


@mcp.tool
def project_runtime_resolve(project_id: str = "", repo: str = "", node: str = "primary") -> dict[str, Any]:
    """Project Runtime Registry: resuelve project_id/repo a path seguro del nodo."""
    return project_runtime_registry.resolve_project(project_id=project_id, repo=repo, node=node)


@mcp.tool
def project_runtime_status(project_id: str = "", repo: str = "", node: str = "primary") -> dict[str, Any]:
    """Project Runtime Registry: estado de runtime path en node=primary|amd."""
    return project_runtime_registry.status(project_id=project_id, repo=repo, node=node)


@mcp.tool
def project_runtime_bootstrap(node: str = "primary", project_id: str = "", repo: str = "", remote_url: str = "", actor: str = "chatgpt", task_id: str = "", correlation_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Project Runtime Registry: crea/hidrata path seguro para un proyecto en un nodo."""
    return project_runtime_registry.bootstrap_runtime(node=node, project_id=project_id, repo=repo, remote_url=remote_url, actor=actor, task_id=task_id, correlation_id=correlation_id, dry_run=dry_run)


@mcp.tool
def project_runtime_reconcile(project_id: str = "", repo: str = "", node: str = "primary", action: str = "plan", approval_id: str = "", dry_run: bool = True, actor: str = "chatgpt") -> dict[str, Any]:
    """Project Runtime Registry: inspect/plan/apply de repo heredado anidado con rollback por cuarentena."""
    return project_runtime_registry.reconcile(project_id=project_id, repo=repo, node=node, action=action, approval_id=approval_id, dry_run=dry_run, actor=actor)


@mcp.tool
def project_runtime_migrate_existing(actor: str = "codex") -> dict[str, Any]:
    """Project Runtime Registry: migra proyectos existentes conocidos sin duplicar."""
    return project_runtime_registry.migrate_existing(actor=actor)


@mcp.tool
def sync_platform_to_intel(dry_run: bool = False, restart_intel: bool = True) -> dict[str, Any]:
    """AG-43: rsync platform AMD→Intel y restart MCP (ejecutar desde AMD)."""
    from raphiia_openai.agents import ag43_platform_sync_agent as ag43

    return ag43.sync_platform_to_intel(dry_run=dry_run, restart_intel=restart_intel)


@mcp.tool
def run_failover_dry_run() -> dict[str, Any]:
    """AG-43: dry-run failover Intel→AMD (no muta producción)."""
    from raphiia_openai.agents import ag43_platform_sync_agent as ag43

    return ag43.run_failover_dry_run()


@mcp.tool
def clone_tenant_deployment(
    slug: str,
    entity_id: str,
    dest_dir: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """AG-43: clona InnerOS tenant (default dry_run=true)."""
    from raphiia_openai.agents import ag43_platform_sync_agent as ag43

    return ag43.clone_tenant_deployment(slug, entity_id, dest_dir, dry_run=dry_run)


@mcp.tool
def cloud_deploy_status() -> dict[str, Any]:
    """AG-44: estado providers cloud (GCP/Alibaba/Cloudflare)."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_deploy_status()


@mcp.tool
def cloud_deploy_plan(
    provider: str = "gcp",
    service: str = "",
    environment: str = "staging",
) -> dict[str, Any]:
    """AG-44: plan de deploy (sin ejecutar) para GCP/Alibaba/Cloudflare."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_deploy_plan(provider, service, environment)


@mcp.tool
def cloud_provider_status(provider: str = "gcp") -> dict[str, Any]:
    """AG-44: readiness por proveedor cloud (GCP/Azure/Alibaba/Cloudflare), solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_provider_status(provider)


@mcp.tool
def cloud_deploy_dry_run(
    provider: str,
    repo: str,
    service: str,
    environment: str = "staging",
    project_id: str = "",
    region: str = "",
    image: str = "",
    source_path: str = "",
) -> dict[str, Any]:
    """AG-44: plan ejecutable sin mutar recursos cloud; prepara el camino para deploy."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_deploy_dry_run(
        provider=provider,
        repo=repo,
        service=service,
        environment=environment,
        project_id=project_id,
        region=region,
        image=image,
        source_path=source_path,
    )


@mcp.tool
def cloud_deploy_apply(
    provider: str,
    repo: str,
    service: str,
    approval_id: str,
    environment: str = "staging",
    project_id: str = "",
    region: str = "",
    image: str = "",
    source_path: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """AG-44: apply cloud con doble compuerta; por defecto dry_run y sin mutar."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_deploy_apply(
        provider=provider,
        repo=repo,
        service=service,
        approval_id=approval_id,
        environment=environment,
        project_id=project_id,
        region=region,
        image=image,
        source_path=source_path,
        dry_run=dry_run,
    )


@mcp.tool
def gcp_auth_bootstrap() -> dict[str, Any]:
    """AG-44: preflight de autenticacion GCP server-side; no expone secretos."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_auth_bootstrap()


@mcp.tool
def gcp_auth_begin(
    request_id: str,
    account_hint: str = "",
    force: bool = False,
    update_adc: bool = True,
) -> dict[str, Any]:
    """AG-44: inicia OAuth GCP headless y devuelve URL de consentimiento, sin secretos."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_auth_begin(request_id, account_hint=account_hint, force=force, update_adc=update_adc)


@mcp.tool
def gcp_auth_submit_code(request_id: str, authorization_code: str) -> dict[str, Any]:
    """AG-44: completa OAuth GCP con codigo one-time; credenciales quedan server-side."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_auth_submit_code(request_id, authorization_code)


@mcp.tool
def gcp_auth_status(request_id: str) -> dict[str, Any]:
    """AG-44: consulta flujo OAuth GCP sin exponer credenciales."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_auth_status(request_id)


@mcp.tool
def cloud_authorization_request(
    provider: str,
    purpose: str,
    project_id: str = "",
    requested_scopes: list[str] | None = None,
    risk_level: str = "moderate_write",
    target_agent: str = "CHATGPT",
) -> dict[str, Any]:
    """AG-44: solicita autorizacion humana/cloud sin exponer secretos."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_authorization_request(provider, purpose, project_id=project_id, requested_scopes=requested_scopes, risk_level=risk_level, target_agent=target_agent)


@mcp.tool
def cloud_authorization_status(request_id: str) -> dict[str, Any]:
    """AG-44: consulta si una autorizacion cloud ya quedo lista."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_authorization_status(request_id)


@mcp.tool
def cloud_approval_issue(provider: str = "gcp", action: str = "gcp_apply", project_id: str = "", billing_account_id: str = "", ttl_minutes: int = 30, note: str = "") -> dict[str, Any]:
    """AG-44: emite approval_id temporal auditado para operaciones cloud."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_approval_issue(provider=provider, action=action, project_id=project_id, billing_account_id=billing_account_id, ttl_minutes=ttl_minutes, note=note)


@mcp.tool
def cloud_approval_status(approval_id: str) -> dict[str, Any]:
    """AG-44: consulta estado de un approval_id temporal."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_approval_status(approval_id)


@mcp.tool
def cloud_apply_window_set(provider: str = "gcp", project_id: str = "", enabled: bool = True, ttl_minutes: int = 15, approval_id: str = "", reason: str = "") -> dict[str, Any]:
    """AG-44: abre/cierra ventana temporal de apply cloud con TTL."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_apply_window_set(provider=provider, project_id=project_id, enabled=enabled, ttl_minutes=ttl_minutes, approval_id=approval_id, reason=reason)


@mcp.tool
def cloud_apply_window_status(provider: str = "gcp", project_id: str = "") -> dict[str, Any]:
    """AG-44: estado de ventana temporal de apply cloud."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloud_apply_window_status(provider=provider, project_id=project_id)


@mcp.tool
def gcp_list_projects() -> dict[str, Any]:
    """AG-44: lista proyectos GCP con gcloud server-side, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_list_projects()


@mcp.tool
def gcp_billing_accounts_list(open_only: bool = False) -> dict[str, Any]:
    """AG-44: lista billing accounts accesibles, redacted y read-only."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_billing_accounts_list(open_only=open_only)


@mcp.tool
def gcp_list_billing_accounts(open_only: bool = False) -> dict[str, Any]:
    """AG-44: alias canonico para listar billing accounts accesibles."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_list_billing_accounts(open_only=open_only)


@mcp.tool
def gcp_billing_projects_list(billing_account_id: str) -> dict[str, Any]:
    """AG-44: lista proyectos vinculados a un billing account."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_billing_projects_list(billing_account_id)


@mcp.tool
def gcp_project_billing_info(project_id: str) -> dict[str, Any]:
    """AG-44: consulta billing vinculado de un proyecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_project_billing_info(project_id)


@mcp.tool
def gcp_get_project_billing(project_id: str) -> dict[str, Any]:
    """AG-44: alias canonico para consultar billing vinculado de proyecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_get_project_billing(project_id)


@mcp.tool
def gcp_billing_credits_status(billing_account_id: str = "") -> dict[str, Any]:
    """AG-44: estado best-effort de creditos/promos y budgets disponibles."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_billing_credits_status(billing_account_id)


@mcp.tool
def gcp_allowlist_project(project_id: str, approval_id: str, note: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-44: agrega proyecto al allowlist Mongo con approval_id."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_allowlist_project(project_id, approval_id, note=note, dry_run=dry_run)


@mcp.tool
def gcp_allowlist_billing_account(billing_account_id: str, approval_id: str, note: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-44: agrega billing account al allowlist Mongo con approval_id."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_allowlist_billing_account(billing_account_id, approval_id, note=note, dry_run=dry_run)


@mcp.tool
def gcp_budgets_list(billing_account_id: str) -> dict[str, Any]:
    """AG-44: lista budgets de un billing account."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_budgets_list(billing_account_id)


@mcp.tool
def gcp_budget_list(billing_account_id: str) -> dict[str, Any]:
    """AG-44: alias canonico para listar budgets de billing."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_budget_list(billing_account_id)


@mcp.tool
def gcp_budget_status(billing_account_id: str, budget_name: str = "") -> dict[str, Any]:
    """AG-44: estado de budgets o de un budget especifico por nombre."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_budget_status(billing_account_id, budget_name=budget_name)


@mcp.tool
def gcp_budget_create(
    billing_account_id: str,
    display_name: str,
    amount: str,
    threshold_percents: list[float] | None = None,
    credit_types_treatment: str = "include-all-credits",
    project_id: str = "",
    dry_run: bool = True,
    approval_id: str = "",
) -> dict[str, Any]:
    """AG-44: crea budget con dry-run/apply gate."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_budget_create(billing_account_id, display_name, amount, threshold_percents=threshold_percents, credit_types_treatment=credit_types_treatment, project_id=project_id, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_costs_query(billing_account_id: str = "", project_id: str = "", days: int = 30) -> dict[str, Any]:
    """AG-44: consulta estado de costos o informa bloqueo de billing export."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_costs_query(billing_account_id=billing_account_id, project_id=project_id, days=days)


@mcp.tool
def gcp_billing_cost_summary(billing_account_id: str = "", project_id: str = "", days: int = 30) -> dict[str, Any]:
    """AG-44: alias canonico para resumen read-only de costos/bloqueos."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_billing_cost_summary(billing_account_id=billing_account_id, project_id=project_id, days=days)


@mcp.tool
def gcp_billing_export_status(billing_account_id: str, project_id: str = "innerops-agentic-platform", dataset_id: str = "billing_export_innerchispa") -> dict[str, Any]:
    """AG-44: estado/limitaciones de Billing Export a BigQuery."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_billing_export_status(billing_account_id, project_id=project_id, dataset_id=dataset_id)


@mcp.tool
def gcp_billing_export_prepare(project_id: str = "innerops-agentic-platform", dataset_id: str = "billing_export_innerchispa", location: str = "US", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: prepara BigQuery para Billing Export con apply gate."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_billing_export_prepare(project_id=project_id, dataset_id=dataset_id, location=location, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_quotas_list(project_id: str, service: str = "run.googleapis.com", limit: int = 100) -> dict[str, Any]:
    """AG-44: lista cuotas GCP por servicio/proyecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_quotas_list(project_id, service=service, limit=limit)


@mcp.tool
def gcp_project_iam_policy(project_id: str) -> dict[str, Any]:
    """AG-44: lee IAM policy de proyecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_project_iam_policy(project_id)


@mcp.tool
def gcp_project_iam_add_binding(project_id: str, member: str, role: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: agrega IAM binding mínimo con allowlist y approval gate."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_project_iam_add_binding(project_id, member, role, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_artifact_registry_list(project_id: str, region: str = "") -> dict[str, Any]:
    """AG-44: lista repositorios Artifact Registry."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_artifact_registry_list(project_id, region)


@mcp.tool
def gcp_artifact_registry_create(project_id: str, repository: str, region: str = "", format: str = "docker", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: crea repositorio Artifact Registry con dry-run/apply gate."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_artifact_registry_create(project_id, repository, region=region, format=format, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_project_setup_preflight(project_id: str, billing_account_id: str = "", apis: list[str] | None = None, region: str = "") -> dict[str, Any]:
    """AG-44: preflight integrado proyecto+billing+APIs+budget/deploy."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_project_setup_preflight(project_id, billing_account_id=billing_account_id, apis=apis, region=region)


@mcp.tool
def gcp_create_project(project_id: str, name: str = "", billing_account_id: str = "", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: prepara/ejecuta creacion GCP con allowlist y aprobacion."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_create_project(project_id, name=name, billing_account_id=billing_account_id, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_link_billing(project_id: str, billing_account_id: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: vincula billing GCP con allowlist y aprobacion."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_link_billing(project_id, billing_account_id, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_enable_apis(project_id: str, apis: list[str], dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: habilita APIs GCP allowlisted; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_enable_apis(project_id, apis, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_cloud_run_status(project_id: str, service: str, region: str = "") -> dict[str, Any]:
    """AG-44: estado Cloud Run, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_status(project_id, service, region)


@mcp.tool
def gcp_cloud_run_domain_mapping_status(project_id: str, domain: str, region: str = "") -> dict[str, Any]:
    """AG-44: describe custom-domain mapping Cloud Run y DNS requerido por Google."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_domain_mapping_status(project_id, domain, region=region)


@mcp.tool
def gcp_cloud_run_domain_mapping_create(
    project_id: str,
    service: str,
    domain: str,
    region: str = "",
    dry_run: bool = True,
    approval_id: str = "",
    force_override: bool = False,
) -> dict[str, Any]:
    """AG-44: crea custom-domain mapping Cloud Run con approval/apply gate."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_domain_mapping_create(
        project_id,
        service,
        domain,
        region=region,
        dry_run=dry_run,
        approval_id=approval_id,
        force_override=force_override,
    )


@mcp.tool
def gcp_build_image(
    project_id: str,
    region: str,
    repository: str,
    image_name: str,
    source_path: str = "",
    repo: str = "",
    ref: str = "",
    tag: str = "latest",
    dry_run: bool = True,
    approval_id: str = "",
) -> dict[str, Any]:
    """AG-44: build+push GCP Artifact Registry via Cloud Build; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_build_image(project_id, region, repository, image_name, source_path=source_path, repo=repo, ref=ref, tag=tag, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_cloud_run_deploy(project_id: str, service: str, image: str, region: str = "", dry_run: bool = True, approval_id: str = "", allow_unauthenticated: bool = False, env_vars: dict[str, str] | None = None) -> dict[str, Any]:
    """AG-44: deploy Cloud Run gated; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_deploy(project_id, service, image, region=region, dry_run=dry_run, approval_id=approval_id, allow_unauthenticated=allow_unauthenticated, env_vars=env_vars or {})


@mcp.tool
def gcp_cloud_run_revisions(project_id: str, service: str, region: str = "") -> dict[str, Any]:
    """AG-44: revisiones Cloud Run, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_revisions(project_id, service, region)


@mcp.tool
def gcp_cloud_run_traffic(project_id: str, service: str, region: str = "") -> dict[str, Any]:
    """AG-44: trafico Cloud Run, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_traffic(project_id, service, region)


@mcp.tool
def gcp_cloud_run_rollback(project_id: str, service: str, revision: str, region: str = "", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: rollback Cloud Run gated; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_cloud_run_rollback(project_id, service, revision, region=region, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_logs_query(project_id: str, query: str = "", limit: int = 50) -> dict[str, Any]:
    """AG-44: consulta logs GCP, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_logs_query(project_id, query=query, limit=limit)


@mcp.tool
def gcp_secret_manager_metadata(project_id: str, secret_id: str) -> dict[str, Any]:
    """AG-44: metadata Secret Manager; nunca retorna valores secretos."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_secret_manager_metadata(project_id, secret_id)


@mcp.tool
def gcp_secret_manager_create_version(project_id: str, secret_id: str, secret_ref: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: crea version usando owner_vault ref; no acepta secreto raw."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_secret_manager_create_version(project_id, secret_id, secret_ref, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_firestore_status(project_id: str) -> dict[str, Any]:
    """AG-44: estado Firestore, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_firestore_status(project_id)


@mcp.tool
def gcp_firestore_create_db(project_id: str, database: str = "(default)", location: str = "nam5", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: crea base Firestore gated; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_firestore_create_db(project_id, database=database, location=location, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_pubsub_list(project_id: str) -> dict[str, Any]:
    """AG-44: lista Pub/Sub topics/subscriptions, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_pubsub_list(project_id)


@mcp.tool
def gcp_pubsub_create_topic(project_id: str, topic: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: crea topic Pub/Sub gated; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_pubsub_create_topic(project_id, topic, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_pubsub_create_subscription(project_id: str, topic: str, subscription: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """AG-44: crea subscription Pub/Sub gated; dry_run por defecto."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_pubsub_create_subscription(project_id, topic, subscription, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def gcp_gemini_or_vertex_status(project_id: str = "", region: str = "") -> dict[str, Any]:
    """AG-44: estado Gemini/Vertex AI metadata, solo lectura."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_gemini_or_vertex_status(project_id, region)


@mcp.tool
def gcp_service_health_check(project_id: str, service: str, region: str = "", path: str = "/") -> dict[str, Any]:
    """AG-44: descubre URL Cloud Run y prueba health HTTP."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.gcp_service_health_check(project_id, service, region=region, path=path)


@mcp.tool
def provider_manifest_schema() -> dict[str, Any]:
    """Provider Onboarding: contrato declarativo para nuevas nubes/tools."""
    from raphiia_openai import provider_onboarding_plane as pop

    return pop.provider_manifest_schema()


@mcp.tool
def provider_register_manifest(manifest: dict[str, Any], dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    """Provider Onboarding: registra manifest validado; dry_run por defecto."""
    from raphiia_openai import provider_onboarding_plane as pop

    return pop.provider_register_manifest(manifest, dry_run=dry_run, approval_id=approval_id)


@mcp.tool
def provider_list_manifests() -> dict[str, Any]:
    """Provider Onboarding: lista manifests registrados sin secretos."""
    from raphiia_openai import provider_onboarding_plane as pop

    return pop.provider_list_manifests()


@mcp.tool
def provider_preflight(provider_id: str) -> dict[str, Any]:
    """Provider Onboarding: preflight de manifest/adaptador."""
    from raphiia_openai import provider_onboarding_plane as pop

    return pop.provider_preflight(provider_id)


@mcp.tool
def resource_fabric_bootstrap(dry_run: bool = False) -> dict[str, Any]:
    """Resource Fabric: registra providers/model providers globales sin ligarlos a proyectos."""
    from raphiia_openai import resource_fabric

    return resource_fabric.bootstrap_global_resource_fabric(dry_run=dry_run)


@mcp.tool
def resource_fabric_status(limit: int = 20) -> dict[str, Any]:
    """Resource Fabric: estado de providers/model registry/project links globales."""
    from raphiia_openai import resource_fabric

    return resource_fabric.resource_fabric_status(limit=limit)


@mcp.tool
def resource_fabric_route(project_id: str, task_class: str, prefer_cloud: bool = False) -> dict[str, Any]:
    """Resource Fabric: selecciona recurso por capability/costo/evidencia; local-first."""
    from raphiia_openai import resource_fabric

    return resource_fabric.route_resource_request(project_id=project_id, task_class=task_class, prefer_cloud=prefer_cloud)


@mcp.tool
def resource_fabric_link_project_capability(project_id: str, capability: str, provider_id: str = "", task_id: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Resource Fabric: vincula proyecto/tarea a una capability sin mover funding ni proveedor al proyecto."""
    from raphiia_openai import resource_fabric

    return resource_fabric.link_project_capability(project_id=project_id, capability=capability, provider_id=provider_id, task_id=task_id, dry_run=dry_run)


@mcp.tool
def tenant_reconciliation_report(save: bool = True) -> dict[str, Any]:
    """Workforce/VigilOS: reporte read-only de tenants/clientes antes de cualquier migracion."""
    from raphiia_openai import tenant_reconciliation

    return tenant_reconciliation.build_tenant_reconciliation_report(save=save)


@mcp.tool
def digitalocean_status() -> dict[str, Any]:
    """DigitalOcean AMD Cloud: estado seguro sin exponer PAT."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.status()


@mcp.tool
def digitalocean_preflight() -> dict[str, Any]:
    """DigitalOcean AMD Cloud: preflight provider/resource fabric sin crear recursos."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.preflight()


@mcp.tool
def digitalocean_balance() -> dict[str, Any]:
    """DigitalOcean AMD Cloud: balance/uso leido por API sin exponer PAT."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.balance()


@mcp.tool
def digitalocean_store_pat_server_side(secret: str, label: str = "DigitalOcean AMD Cloud PAT", actor: str = "RAFAEL") -> dict[str, Any]:
    """DigitalOcean AMD Cloud: guarda PAT en owner_vault; no retorna el secreto."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.store_pat_server_side(secret=secret, label=label, actor=actor)


@mcp.tool
def digitalocean_list_regions() -> dict[str, Any]:
    """DigitalOcean AMD Cloud: lista regiones usando PAT server-side si existe."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.list_regions()


@mcp.tool
def digitalocean_list_sizes(gpu_only: bool = True) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: lista sizes, por defecto filtrados a GPU/AMD."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.list_sizes(gpu_only=gpu_only)


@mcp.tool
def digitalocean_list_images() -> dict[str, Any]:
    """DigitalOcean AMD Cloud: lista imagenes base aprobables."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.list_images()


@mcp.tool
def digitalocean_list_ssh_keys() -> dict[str, Any]:
    """DigitalOcean AMD Cloud: lista SSH keys disponibles para bootstrap."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.list_ssh_keys()


@mcp.tool
def digitalocean_create_ssh_key(name: str, public_key: str, dry_run: bool = True) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: registra una SSH public key; dry_run por defecto."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.create_ssh_key(name=name, public_key=public_key, dry_run=dry_run)


@mcp.tool
def digitalocean_register_server_public_ssh_key(name: str = "inneros-amd-5-id-ed25519", public_key_path: str = "~/.ssh/id_ed25519.pub", dry_run: bool = True) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: registra la public key local allowlisted para bootstrap."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.register_server_public_ssh_key(name=name, public_key_path=public_key_path, dry_run=dry_run)


@mcp.tool
def digitalocean_list_droplets(tag_name: str = "inneros-cloud-burst") -> dict[str, Any]:
    """DigitalOcean AMD Cloud: lista droplets del burst tag."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.list_droplets(tag_name=tag_name)


@mcp.tool
def digitalocean_create_gpu_droplet(
    name: str,
    region: str,
    size: str,
    image: str,
    ssh_key_ids: list[str] | None = None,
    project_id: str = "",
    task_id: str = "",
    approval_id: str = "",
    dry_run: bool = True,
    spend_limit_usd: float = 20.0,
    idle_minutes: int = 30,
) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: crea GPU droplet gated; dry_run por defecto."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.create_gpu_droplet(
        name=name,
        region=region,
        size=size,
        image=image,
        ssh_key_ids=ssh_key_ids,
        project_id=project_id,
        task_id=task_id,
        approval_id=approval_id,
        dry_run=dry_run,
        spend_limit_usd=spend_limit_usd,
        idle_minutes=idle_minutes,
    )


@mcp.tool
def digitalocean_get_droplet(droplet_id: str) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: consulta droplet por id."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.get_droplet(droplet_id)


@mcp.tool
def digitalocean_destroy_droplet(droplet_id: str, approval_id: str = "", project_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: destruye droplet gated; dry_run por defecto."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.destroy_droplet(droplet_id=droplet_id, approval_id=approval_id, project_id=project_id, dry_run=dry_run)


@mcp.tool
def digitalocean_cost_session_status(session_id: str = "", project_id: str = "", task_id: str = "") -> dict[str, Any]:
    """DigitalOcean AMD Cloud: costo estimado por sesion y politica destroy."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.cost_session_status(session_id=session_id, project_id=project_id, task_id=task_id)


@mcp.tool
def digitalocean_cleanup_failed_sessions(max_age_seconds: int = 3600, dry_run: bool = True) -> dict[str, Any]:
    """DigitalOcean AMD Cloud: marca sesiones fantasma sin droplet_id como fallidas."""
    from raphiia_openai import digitalocean_amd_provider as do

    return do.cleanup_failed_sessions(max_age_seconds=max_age_seconds, dry_run=dry_run)


@mcp.tool
def brightdata_status() -> dict[str, Any]:
    """Bright Data: estado seguro, balance y MCP remoto sin exponer token."""
    from raphiia_openai import brightdata_provider as bd

    return bd.status()


@mcp.tool
def brightdata_balance() -> dict[str, Any]:
    """Bright Data: balance/costos pendientes usando API token server-side."""
    from raphiia_openai import brightdata_provider as bd

    return bd.balance()


@mcp.tool
def brightdata_store_api_token_server_side(secret: str, label: str = "Bright Data API token", actor: str = "RAFAEL") -> dict[str, Any]:
    """Bright Data: guarda API token en owner_vault; no retorna el secreto."""
    from raphiia_openai import brightdata_provider as bd

    return bd.store_api_token_server_side(secret=secret, label=label, actor=actor)


@mcp.tool
def brightdata_mcp_list_tools(limit: int = 80) -> dict[str, Any]:
    """Bright Data: lista tools disponibles del MCP remoto oficial."""
    from raphiia_openai import brightdata_provider as bd

    return bd.mcp_list_tools(limit=limit)


@mcp.tool
def brightdata_mcp_call_tool(tool_name: str, arguments: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Bright Data: llama una tool allowlisted del MCP remoto; dry_run por defecto."""
    from raphiia_openai import brightdata_provider as bd

    return bd.mcp_call_tool(tool_name=tool_name, arguments=arguments, dry_run=dry_run)


@mcp.tool
def brightdata_search_engine(query: str, engine: str = "google", geo_location: str = "us", dry_run: bool = True) -> dict[str, Any]:
    """Bright Data: SERP/web search para research y SEO; consume credito si dry_run=false."""
    from raphiia_openai import brightdata_provider as bd

    return bd.search_engine(query=query, engine=engine, geo_location=geo_location, dry_run=dry_run)


@mcp.tool
def brightdata_scrape_as_markdown(url: str, dry_run: bool = True) -> dict[str, Any]:
    """Bright Data: obtiene una pagina publica como Markdown; consume credito si dry_run=false."""
    from raphiia_openai import brightdata_provider as bd

    return bd.scrape_as_markdown(url=url, dry_run=dry_run)


@mcp.tool
def cloudflare_status(zone_name: str = "pcdoctor.ai") -> dict[str, Any]:
    """AG-44: estado Cloudflare usando owner_vault; no expone secretos."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_status(zone_name)


@mcp.tool
def cloudflare_dns_upsert(
    hostname: str,
    record_type: str,
    content: str,
    proxied: bool = True,
    ttl: int = 1,
    priority: int | None = None,
    zone_name: str = "pcdoctor.ai",
    dry_run: bool = False,
) -> dict[str, Any]:
    """AG-44: crea/actualiza DNS allowlisted por hostname en Cloudflare."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_dns_upsert(hostname, record_type, content, proxied=proxied, ttl=ttl, priority=priority, zone_name=zone_name, dry_run=dry_run)


@mcp.tool
def cloudflare_dns_delete(hostname: str, record_type: str = "", zone_name: str = "pcdoctor.ai", dry_run: bool = False) -> dict[str, Any]:
    """AG-44: elimina registros DNS allowlisted por hostname/tipo en Cloudflare."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_dns_delete(hostname, record_type=record_type, zone_name=zone_name, dry_run=dry_run)


@mcp.tool
def cloudflare_waf_skip_challenge(hostname: str, zone_name: str = "pcdoctor.ai", path_prefix: str = "", dry_run: bool = False, note: str = "") -> dict[str, Any]:
    """AG-44: aplica regla WAF minima para saltar challenges en un hostname o path."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_waf_skip_challenge(hostname, zone_name=zone_name, path_prefix=path_prefix, dry_run=dry_run, note=note)


@mcp.tool
def cloudflare_waf_delete_hostname_rules(hostname: str, zone_name: str = "pcdoctor.ai", dry_run: bool = True) -> dict[str, Any]:
    """AG-44: rollback; borra reglas WAF custom cuyo expression coincide con el hostname."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_waf_delete_hostname_rules(hostname, zone_name=zone_name, dry_run=dry_run)


@mcp.tool
def cloudflare_tunnel_ingress_status(hostname: str = "", config_path: str = "") -> dict[str, Any]:
    """AG-44: inspecciona ingress cloudflared local para hostname/túnel."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_tunnel_ingress_status(hostname, config_path)


@mcp.tool
def cloudflare_hostname_health_check(hostname: str, path: str = "/", timeout: float = 12.0) -> dict[str, Any]:
    """AG-44: verifica HTTPS público y header cf-mitigated para un hostname."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_hostname_health_check(hostname, path=path, timeout=timeout)


@mcp.tool
def cloudflare_prepare_hostname(
    hostname: str,
    dns_type: str = "",
    dns_content: str = "",
    proxied: bool = True,
    ensure_waf_skip: bool = True,
    health_path: str = "/",
    dry_run: bool = False,
) -> dict[str, Any]:
    """AG-44: prepara/repara un subdominio pcdoctor.ai con DNS opcional, WAF, túnel y health."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.cloudflare_prepare_hostname(
        hostname,
        dns_type=dns_type,
        dns_content=dns_content,
        proxied=proxied,
        ensure_waf_skip=ensure_waf_skip,
        health_path=health_path,
        dry_run=dry_run,
    )


@mcp.tool
def get_development_roadmap() -> dict[str, Any]:
    """Roadmap vivo agentes/flujos — qué falta y dónde está registrado."""
    from raphiia_openai.agents import ag44_cloud_deployer as ag44

    return ag44.get_development_roadmap()


@mcp.tool
def list_local_agents() -> dict[str, Any]:
    """AG-49: catálogo flota local-first (cotizar, informes, factura, guardian, vida)."""
    from raphiia_openai.agents import ag49_local_dispatcher as ag49

    return ag49.list_local_agents()


@mcp.tool
def get_agent_catalog(
    domain: str = "",
    status: str = "",
    functional_only: bool = False,
) -> dict[str, Any]:
    """Catálogo AG-xx con nombres amigables, aliases y cómo llamar cada agente."""
    from raphiia_openai.agents import agent_catalog

    return agent_catalog.get_agent_catalog(
        domain=domain or None,
        status=status or None,
        functional_only=functional_only,
    )


@mcp.tool
def resolve_agent(message: str, limit: int = 3) -> dict[str, Any]:
    """Elige agente por intención (lenguaje natural). Ej: salud → AG-51, cotizar → Vero."""
    from raphiia_openai.agents import agent_catalog

    return agent_catalog.resolve_agent(message, limit=limit)


@mcp.tool
def route_agent_request(
    message: str,
    auto_execute: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Resuelve agente y ejecuta por defecto. dry_run=true solo preview."""
    from raphiia_openai.agents import agent_intent_router

    return agent_intent_router.route_agent_request(
        message,
        auto_execute=auto_execute,
        dry_run=dry_run,
    )


@mcp.tool
def invoke_agent(agent_id: str, message: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Ejecuta cualquier agente AG-xx por ID. Ej: invoke_agent('AG-51', 'presión 120/80')."""
    from raphiia_openai.agents.pool_agent_runners import invoke_agent as _invoke

    return _invoke(agent_id, message, dry_run=dry_run)


@mcp.tool
def ralfia_dispatch(message: str = "", auto_execute: bool = True, dry_run: bool = False) -> dict[str, Any]:
    """AG-25 RalfIA — orquestador principal. Ve catálogo y enruta/ejecuta cualquier agente."""
    from raphiia_openai.agents import ag25_ralfia_orchestrator as ag25

    return ag25.ralfia_dispatch(message, auto_execute=auto_execute, dry_run=dry_run)


@mcp.tool
def ralfia_status() -> dict[str, Any]:
    """AG-25 RalfIA — estado orquestador + conteos agentes."""
    from raphiia_openai.agents import ag25_ralfia_orchestrator as ag25

    return ag25.ralfia_status()


@mcp.tool
def dispatch_local_agent(
    task_kind: str,
    client_ref: str = "",
    message: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """AG-49: entrada única — ejecuta por defecto (dry_run=true = solo preview)."""
    from raphiia_openai.agents import ag49_local_dispatcher as ag49

    return ag49.dispatch_local_agent(task_kind, client_ref, message, dry_run=dry_run)


@mcp.tool
def run_service_guardian() -> dict[str, Any]:
    """AG-42: ciclo vigilancia AG-40+AG-31+AG-41 (servicios no caigan)."""
    from raphiia_openai.agents import ag42_service_guardian as ag42

    return ag42.run_service_guardian(notify=False)


@mcp.tool
def run_self_heal_cycle(auto_repair: bool = False, max_repairs: int = 3) -> dict[str, Any]:
    """AG-42: auto-reparación local — detecta caídos y restart allowlisted (peer_ops). Sin cloud."""
    from raphiia_openai.agents import ag42_service_guardian as ag42

    return ag42.run_self_heal_cycle(auto_repair=auto_repair, max_repairs=max_repairs)


@mcp.tool
def agent_quote_prepare(client_ref: str, title: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-46: preparar cotización PC Doctor (delega Vero/AG-16)."""
    from raphiia_openai.agents import ag46_quote_agent as ag46

    return ag46.agent_quote_prepare(client_ref, title, dry_run=dry_run)


@mcp.tool
def agent_report_technical(client_ref: str, message: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-47: informe técnico / supervisor."""
    from raphiia_openai.agents import ag47_report_agent as ag47

    return ag47.agent_report_technical(client_ref, message, dry_run=dry_run)


@mcp.tool
def agent_invoice_prepare(client_ref: str, quote_ref: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-48: borrador factura/cobro (FAC SRI gated — AG-17 pendiente)."""
    from raphiia_openai.agents import ag48_billing_agent as ag48

    return ag48.agent_invoice_prepare(client_ref, quote_ref, dry_run=dry_run)


@mcp.tool
def run_daily_companion(message: str = "", include_brief: bool = True) -> dict[str, Any]:
    """AG-50: compañero día a día — brief + memoria + respuesta local Ollama."""
    from raphiia_openai.agents import ag50_daily_companion as ag50

    return ag50.run_daily_companion(message, include_brief=include_brief)


@mcp.tool
def agent_daily_save_note(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    """AG-50: guardar nota personal del día (PRIVATE_PERSONAL)."""
    from raphiia_openai.agents import ag50_daily_companion as ag50

    return ag50.agent_daily_save_note(title, body, tags)


@mcp.tool
def agent_health_save(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    """AG-51: guardar entrada historial de salud (PRIVATE_HEALTH)."""
    from raphiia_openai.agents import ag51_health_memory_agent as ag51

    return ag51.agent_health_save(title, body, tags=tags)


@mcp.tool
def agent_health_timeline(query: str = "", limit: int = 20) -> dict[str, Any]:
    """AG-51: línea de tiempo salud privada."""
    from raphiia_openai.agents import ag51_health_memory_agent as ag51

    return ag51.agent_health_timeline(query, limit)


@mcp.tool
def agent_health_summary() -> dict[str, Any]:
    """AG-51: resumen historial salud reciente."""
    from raphiia_openai.agents import ag51_health_memory_agent as ag51

    return ag51.agent_health_summary()


@mcp.tool
def agent_iskcon_status() -> dict[str, Any]:
    """AG-52: estado operaciones ISKCON (ent_iskcon)."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_status()


@mcp.tool
def agent_iskcon_dispatch(action: str = "status", message: str = "", dry_run: bool = True) -> dict[str, Any]:
    """AG-52: dispatch ISKCON — status|memory|ops."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_dispatch(action, message, dry_run=dry_run)


@mcp.tool
def agent_iskcon_capabilities() -> dict[str, Any]:
    """AG-52: mapa dominios ISKCON local + reutilización InnerOS."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_capabilities()


@mcp.tool
def agent_iskcon_domain(domain: str) -> dict[str, Any]:
    """AG-52: detalle dominio — food_for_life|festivals_events|temple_operations|..."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_domain(domain)


@mcp.tool
def agent_iskcon_ffl_log(
    title: str,
    body: str = "",
    plates: int | None = None,
    location: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """AG-52: registrar distribución Food for Life (ralfia_memory_items)."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_ffl_log(title, body, plates=plates, location=location, dry_run=dry_run)


@mcp.tool
def agent_iskcon_ffl_timeline(limit: int = 20) -> dict[str, Any]:
    """AG-52: historial raciones Food for Life."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_ffl_timeline(limit)


@mcp.tool
def agent_iskcon_contacts_summary(limit: int = 10) -> dict[str, Any]:
    """AG-52: contactos comunitarios ent_iskcon."""
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    return ag52.agent_iskcon_contacts_summary(limit)


@mcp.tool
def agent_hackathon_status() -> dict[str, Any]:
    """AG-53: estado hackathons + programas funding relacionados."""
    from raphiia_openai.agents import ag53_hackathon_agent as ag53

    return ag53.agent_hackathon_status()


@mcp.tool
def agent_hackathon_scan_emails(query: str = "hackathon credits grant devpost", limit: int = 15) -> dict[str, Any]:
    """AG-53: escanear correo por oportunidades hackathon."""
    from raphiia_openai.agents import ag53_hackathon_agent as ag53

    return ag53.agent_hackathon_scan_emails(query, limit)


@mcp.tool
def agent_funding_status() -> dict[str, Any]:
    """AG-54: créditos/grants registrados + resumen consumos."""
    from raphiia_openai.agents import ag54_funding_credits_agent as ag54

    return ag54.agent_funding_status()


@mcp.tool
def agent_funding_scan_emails(query: str = "credits grant funding cloud startup", limit: int = 25) -> dict[str, Any]:
    """AG-54: escanear correo por créditos/grants para no desperdiciar."""
    from raphiia_openai.agents import ag54_funding_credits_agent as ag54

    return ag54.agent_funding_scan_emails(query, limit)


@mcp.tool
def agent_funding_register_from_email(message_id: str, program_name: str, dry_run: bool = True) -> dict[str, Any]:
    """AG-54: registrar programa funding desde correo archivado."""
    from raphiia_openai.agents import ag54_funding_credits_agent as ag54

    return ag54.agent_funding_register_from_email(message_id, program_name, dry_run=dry_run)


@mcp.tool
def agent_funding_sync_and_scan(
    query: str = "bright data credits grant funding prize winner cloud startup",
    limit: int = 40,
    poll_email: bool = True,
) -> dict[str, Any]:
    """AG-54: poll correo → archive → scan créditos/grants (Bright Data, cloud, etc.)."""
    from raphiia_openai.agents import ag54_funding_credits_agent as ag54

    return ag54.agent_funding_sync_and_scan(query=query, limit=limit, poll_email=poll_email)


@mcp.tool
def agent_browser_status() -> dict[str, Any]:
    """AG-55: estado Playwright local + allowlist dominios."""
    from raphiia_openai.agents import ag55_browser_ops_agent as ag55

    return ag55.agent_browser_status()


@mcp.tool
def agent_browser_run_task(
    task: str,
    url: str = "",
    selectors: dict[str, str] | None = None,
    values: dict[str, str] | None = None,
    click_selector: str = "",
    extract_selector: str = "",
    dry_run: bool = True,
    timeout_ms: int = 30000,
    local_preview: bool = False,
    loopback_ports: list[int] | None = None,
) -> dict[str, Any]:
    """AG-55: tarea browser local (navigate|screenshot|fill_form|click|extract). dry_run=True por defecto."""
    from raphiia_openai.agents import ag55_browser_ops_agent as ag55

    return ag55.agent_browser_run_task(
        task,
        url,
        selectors=selectors,
        values=values,
        click_selector=click_selector,
        extract_selector=extract_selector,
        dry_run=dry_run,
        timeout_ms=timeout_ms,
        local_preview=local_preview,
        loopback_ports=loopback_ports,
    )


@mcp.tool
def browser_session_start(
    url: str,
    profile: str = "default",
    ttl_seconds: int = 7200,
    local_preview: bool = False,
    loopback_ports: list[int] | None = None,
) -> dict[str, Any]:
    """AG-55 human browser: inicia sesion visible/controlable desde Windows por LAN."""
    payload = {
        "url": url,
        "profile": profile,
        "ttl_seconds": ttl_seconds,
        "local_preview": local_preview,
        "loopback_ports": loopback_ports,
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/browser/api/session/start",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool
def browser_session_status(session_id: str = "", token: str = "") -> dict[str, Any]:
    """AG-55 human browser: estado de sesiones visuales y URLs para owner/agente."""
    if session_id:
        url = f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/browser/api/session/{session_id}/status?token={urllib.parse.quote(token)}"
    else:
        url = f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/browser/api/session/status"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool
def browser_session_action(session_id: str, token: str, kind: str, payload_json: str = "{}") -> dict[str, Any]:
    """AG-55 human browser: accion atomica navigate/click/type/press/wait/status en sesion autenticada."""
    payload = json.loads(payload_json or "{}")
    req = urllib.request.Request(
        f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/browser/api/session/{session_id}/action?token={urllib.parse.quote(token)}",
        data=json.dumps({"kind": kind, **payload}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool
def browser_session_stop(session_id: str, token: str = "") -> dict[str, Any]:
    """AG-55 human browser: cierra una sesion visual."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/browser/api/session/{session_id}/stop?token={urllib.parse.quote(token)}",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool
def fetch(document_id: str) -> dict[str, Any]:
    """Obtiene un documento por id (formato collection/ObjectId)."""
    return mongo_store.fetch(document_id)


@mcp.tool
def get_context_summary() -> dict[str, Any]:
    """Resume conteos de clientes, ideas, pipeline y últimos registros."""
    return mongo_store.get_context_summary()


@mcp.tool
def save_pipeline_draft(
    channel: str,
    title: str,
    markdown: str,
    metadata: dict[str, Any] | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Guarda borrador editorial (texto generado por ChatGPT) en editorial_pipeline."""
    doc = mongo_store.save_pipeline_draft(channel=channel, markdown=markdown, title=title, metadata=metadata, status=status)
    return {"ok": True, "saved": doc}


@mcp.tool
def upload_draft_media(
    draft_id: str,
    image_base64: str = "",
    image_url: str = "",
    mime_type: str = "image/png",
    prompt: str = "",
    source: str = "chatgpt",
) -> dict[str, Any]:
    """Sube una imagen generada por ChatGPT a un borrador editorial."""
    return editorial_media_upload.upload_to_draft(
        draft_id,
        image_base64=image_base64,
        image_url=image_url,
        mime_type=mime_type,
        prompt=prompt,
        source=source,
    )


@mcp.tool
def save_dalle_image(
    draft_id: str,
    image_url: str = "",
    prompt: str = "",
    image_base64: str = "",
    mime_type: str = "image/png",
) -> dict[str, Any]:
    """Alias compatible para guardar imagen ChatGPT/DALL·E en un borrador."""
    source = "dalle" if image_url else "chatgpt"
    return editorial_media_upload.upload_to_draft(
        draft_id,
        image_base64=image_base64,
        image_url=image_url,
        mime_type=mime_type,
        prompt=prompt,
        source=source,
    )


@mcp.tool
def queue_pipeline_item(id: str, status: str | None = None) -> dict[str, Any]:
    """Alias seguro para mover un item del pipeline a review/listo para publicación."""
    target_status = status or editorial_store.STATUS_REVIEW
    return editorial_store.update_pipeline_status(id, target_status)


@mcp.tool
def list_pipeline(limit: int = 20) -> dict[str, Any]:
    """Lista borradores editoriales recientes."""
    items = mongo_store.list_pipeline(limit=limit)
    return {"ok": True, "count": len(items), "items": items}


@mcp.tool
def approve_pipeline_draft(draft_id: str) -> dict[str, Any]:
    """Aprueba borrador -> editorial_posts + cola LinkedIn. NO publica."""
    from raphiia_openai import editorial_store

    return editorial_store.approve_draft(draft_id, approved_by="mcp_admin")


@mcp.tool
def generate_draft_image(draft_id: str) -> dict[str, Any]:
    """Genera imagen para borrador."""
    from raphiia_openai import editorial_store, image_gen

    dr = editorial_store.get_draft(draft_id)
    if not dr.get("ok"):
        return dr
    draft = dr["draft"]
    editorial_store.update_draft(draft_id, {"status": editorial_store.STATUS_GENERATING})
    gen = image_gen.generate_for_draft(draft_id, draft.get("title", ""), draft.get("markdown", draft.get("body", "")))
    if not gen.get("ok"):
        return gen
    return editorial_store.attach_media(
        draft_id,
        media_path=gen["media_path"],
        media_prompt=gen["media_prompt"],
        provider=gen["provider"],
    )


@mcp.tool
def get_coordination_summary(limit: int = 20) -> dict[str, Any]:
    """Últimos eventos de desarrollo/coordinación y rutas de documentación."""
    return mongo_store.get_coordination_summary(limit=limit)


@mcp.tool
def log_coordination_event(
    agent: str,
    summary: str,
    project: str | None = None,
    tool_used: str | None = None,
) -> dict[str, Any]:
    """Registra en MongoDB quién hizo qué."""
    doc = mongo_store.log_coordination(
        agent=agent,
        summary=summary,
        project=project,
        tool_used=tool_used,
    )
    return {"ok": True, "logged": doc}


@mcp.tool
def health_check() -> dict[str, Any]:
    """Comprueba MongoDB y estado del bridge MCP."""
    mongo = mongo_store.ping_mongo()
    mongo_store.log_sync("mcp_health_check", mongo_ok=mongo.get("ok"))
    return {
        "ok": bool(mongo.get("ok")),
        "service": "raphiia-openai-mcp",
        "mongodb": mongo,
        "auth_required": bool(MCP_API_KEY),
    }


@mcp.tool
def get_project_map() -> dict[str, Any]:
    """Mapa central RalfIA compacto."""
    return coordination_docs.get_project_map()


@mcp.tool
def create_client_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.create_client_draft(payload)


@mcp.tool
def upsert_client(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.upsert_client(payload)


@mcp.tool
def create_site_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.create_site_draft(payload)


@mcp.tool
def upsert_site(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.upsert_site(payload)


@mcp.tool
def create_asset_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.create_asset_draft(payload)


@mcp.tool
def upsert_asset(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.upsert_asset(payload)


@mcp.tool
def create_visit_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.create_visit_draft(payload)


@mcp.tool
def log_service_visit(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.log_service_visit(payload)


@mcp.tool
def add_observation(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.add_observation(payload)


@mcp.tool
def attach_media_to_visit(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.attach_media_to_visit(payload)


@mcp.tool
def attach_media_to_asset(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.attach_media_to_asset(payload)


@mcp.tool
def register_client_document(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.register_client_document(payload)


@mcp.tool
def list_client_documents(client_id: str, site_id: str = "", visit_id: str = "", asset_id: str = "", limit: int = 50) -> dict[str, Any]:
    return pcdoctor_store.list_client_documents(client_id, site_id=site_id, visit_id=visit_id, asset_id=asset_id, limit=limit)


@mcp.tool
def document_vault_ingest(
    file_ref: Any = None,
    local_path: str = "",
    entity_type: str = "client",
    entity_ref: str = "",
    category: str = "general",
    title: str = "",
    version_label: str = "",
    status: str = "",
    tags: Any = None,
    make_canonical: bool = False,
    drive_replica: dict[str, Any] | None = None,
    document_type: str = "",
    created_by: str = "agent",
) -> dict[str, Any]:
    return document_vault.document_vault_ingest(
        file_ref=file_ref,
        local_path=local_path or None,
        entity_type=entity_type,
        entity_ref=entity_ref,
        category=category,
        title=title,
        version_label=version_label or None,
        status=status or None,
        tags=tags,
        make_canonical=make_canonical,
        drive_replica=drive_replica,
        document_type=document_type or None,
        created_by=created_by,
    )


@mcp.tool
def document_vault_register_external(
    entity_ref: str,
    external_provider: str,
    file_id: str = "",
    url: str = "",
    metadata: dict[str, Any] | None = None,
    document_id: str = "",
    title: str = "",
    entity_type: str = "client",
    category: str = "external",
) -> dict[str, Any]:
    return document_vault.document_vault_register_external(
        entity_ref=entity_ref,
        external_provider=external_provider,
        file_id=file_id,
        url=url,
        metadata=metadata,
        document_id=document_id,
        title=title,
        entity_type=entity_type,
        category=category,
    )


@mcp.tool
def document_vault_list(entity_ref: str, filters: dict[str, Any] | None = None, limit: int = 50) -> dict[str, Any]:
    return document_vault.document_vault_list(entity_ref=entity_ref, filters=filters, limit=limit)


@mcp.tool
def document_vault_search(query: str, entity_ref: str = "", document_type: str = "", status: str = "", limit: int = 10) -> dict[str, Any]:
    return document_vault.document_vault_search(query=query, entity_ref=entity_ref, document_type=document_type, status=status, limit=limit)


@mcp.tool
def document_vault_get(document_id: str = "", natural_query: str = "", return_file_ref: bool = True) -> dict[str, Any]:
    return document_vault.document_vault_get(document_id=document_id, natural_query=natural_query, return_file_ref=return_file_ref)


@mcp.tool
def document_vault_set_canonical(document_id: str, actor: str, expected_revision: int | None = None) -> dict[str, Any]:
    return document_vault.document_vault_set_canonical(document_id=document_id, actor=actor, expected_revision=expected_revision)


@mcp.tool
def document_vault_versions(document_id: str = "", logical_key: str = "") -> dict[str, Any]:
    return document_vault.document_vault_versions(document_id=document_id, logical_key=logical_key)


@mcp.tool
def document_vault_health() -> dict[str, Any]:
    return document_vault.document_vault_health()


@mcp.tool
def document_vault_status() -> dict[str, Any]:
    return document_vault.document_vault_status()


@mcp.tool
def document_vault_replicate(document_id: str, target_node: str = "") -> dict[str, Any]:
    return document_vault.document_vault_replicate(document_id=document_id, target_node=target_node)


@mcp.tool
def document_vault_export_file(document_id: str) -> dict[str, Any]:
    return document_vault.document_vault_export_file(document_id=document_id)


@mcp.tool
def record_site_network_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.record_site_network_snapshot(payload)


@mcp.tool
def list_site_network_snapshots(site_id: str, client_id: str = "", limit: int = 20) -> dict[str, Any]:
    return pcdoctor_store.list_site_network_snapshots(site_id, client_id=client_id, limit=limit)


@mcp.tool
def build_client_360_snapshot(client_id: str, site_id: str = "") -> dict[str, Any]:
    return pcdoctor_store.build_client_360_snapshot(client_id, site_id=site_id)


@mcp.tool
def extract_fields_from_media(media_id: str) -> dict[str, Any]:
    return pcdoctor_store.extract_fields_from_media(media_id)


@mcp.tool
def link_asset_to_client(asset_id: str, client_id: str) -> dict[str, Any]:
    return pcdoctor_store.link_asset_to_client(asset_id, client_id)


@mcp.tool
def link_asset_to_site(asset_id: str, site_id: str) -> dict[str, Any]:
    return pcdoctor_store.link_asset_to_site(asset_id, site_id)


@mcp.tool
def resolve_client(identifier: str, limit: int = 10) -> dict[str, Any]:
    return pcdoctor_store.resolve_client(identifier, limit=limit)


@mcp.tool
def list_clients(limit: int = 25) -> dict[str, Any]:
    return pcdoctor_store.list_clients(limit=limit)


@mcp.tool
def resolve_site(identifier: str, limit: int = 10) -> dict[str, Any]:
    return pcdoctor_store.resolve_site(identifier, limit=limit)


@mcp.tool
def resolve_asset(identifier: str, limit: int = 10) -> dict[str, Any]:
    return pcdoctor_store.resolve_asset(identifier, limit=limit)


@mcp.tool
def list_client_sites(client_id: str) -> dict[str, Any]:
    return pcdoctor_store.list_client_sites(client_id)


@mcp.tool
def list_site_assets(site_id: str) -> dict[str, Any]:
    return pcdoctor_store.list_site_assets(site_id)


@mcp.tool
def create_quote_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.create_quote_draft(payload)


@mcp.tool
def update_quote_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return pcdoctor_store.update_quote_draft(payload)


@mcp.tool
def render_quote_document(quote_ref: str) -> dict[str, Any]:
    """HTML cotización — leer RUNBOOK HUB/RUNBOOK_COTIZACION_WHATSAPP.md §2."""
    from raphiia_openai.operational.quote_renderer import render_quote_html
    result = render_quote_html(quote_ref)
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "quote_ref": quote_ref,
        "display_number": result.get("display_number"),
        "preview_path": f"/api/v1/quotes/{quote_ref}/document",
        "html_length": len(result.get("html") or ""),
    }


@mcp.tool
def generate_quote_intro(quote_ref: str, visit_id: str | None = None) -> dict[str, Any]:
    """Introducción narrativa para cotización — contexto comercial, no informe técnico de campo."""
    from raphiia_openai.operational.quote_delivery import generate_quote_intro as _gen
    return _gen(quote_ref, visit_id=visit_id)


@mcp.tool
def send_quote_delivery(
    quote_ref: str,
    channels: list[str] | None = None,
    phone: str | None = None,
    email: str | None = None,
    intro_md: str | None = None,
) -> dict[str, Any]:
    """Envía cotización + ticket PCD-COT-* — RUNBOOK HUB §3. Cliente responde citando ticket."""
    from raphiia_openai.operational.quote_delivery import send_quote_delivery as _send
    return _send(quote_ref, channels=channels, phone=phone, email=email, intro_md=intro_md)


@mcp.tool
def get_quote_tracking(ticket_id: str) -> dict[str, Any]:
    """Estado de seguimiento de cotización por referencia WhatsApp."""
    from raphiia_openai.operational.quote_delivery import get_delivery_by_ticket
    return get_delivery_by_ticket(ticket_id)


@mcp.tool
def list_quote_deliveries(limit: int = 30, status: str | None = None) -> dict[str, Any]:
    """Lista envíos de cotización con ticket PCD-COT."""
    from raphiia_openai.operational.quote_delivery import list_quote_deliveries as _list
    return _list(limit=limit, status=status)


@mcp.tool
def generate_quote_pdf(quote_ref: str, ticket_id: str | None = None) -> dict[str, Any]:
    """Genera PDF de cotización. RUNBOOK HUB §3."""
    from raphiia_openai.operational.quote_pdf import generate_quote_pdf as _pdf
    return _pdf(quote_ref, ticket_id=ticket_id)


@mcp.tool
def sync_quote_sources(quote_ref: str) -> dict[str, Any]:
    """Unifica Smart Quoter / Contifico / ops → quote_id canónico."""
    from raphiia_openai.operational.quote_unify import sync_quote_sources as _sync
    return _sync(quote_ref)


@mcp.tool
def generate_supervisor_report(client_id: str, site_id: str | None = None, visit_id: str | None = None) -> dict[str, Any]:
    return pcdoctor_store.generate_supervisor_report(client_id, site_id=site_id, visit_id=visit_id)


@mcp.tool
def resolve_party(identifier: str, limit: int = 10, roles: list[str] | None = None) -> dict[str, Any]:
    """Busca identidad unificada (party_id) en kernel CRM y colecciones legacy."""
    return party_store.resolve_party(identifier, limit=limit, roles=roles)


@mcp.tool
def upsert_party(payload: dict[str, Any]) -> dict[str, Any]:
    """Crea o actualiza party canónico con roles y enlaces identity_map."""
    return party_store.upsert_party(payload)


@mcp.tool
def create_payable_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Crea borrador AP/cheque (idempotente). Requiere party supplier o nombre/RUC."""
    return accounting_store.create_payable_draft(payload)


@mcp.tool
def upsert_payable(payload: dict[str, Any]) -> dict[str, Any]:
    """Promueve o actualiza obligación AP canónica."""
    return accounting_store.upsert_payable(payload)


@mcp.tool
def resolve_payable(identifier: str, limit: int = 10) -> dict[str, Any]:
    """Busca payables por id, proveedor, cheque, factura o referencia."""
    return accounting_store.resolve_payable(identifier, limit=limit)


@mcp.tool
def list_payables_due(
    entity_id: str | None = None,
    days_ahead: int = 14,
    limit: int = 50,
    status: str | None = None,
) -> dict[str, Any]:
    """Lista AP por vencer o vencidas (alertas)."""
    return accounting_store.list_payables_due(entity_id=entity_id, days_ahead=days_ahead, limit=limit, status=status)


@mcp.tool
def record_payment(payload: dict[str, Any]) -> dict[str, Any]:
    """Registra pago de un payable y marca como paid."""
    return accounting_store.record_payment(payload)


@mcp.tool
def accounting_summary(entity_id: str | None = None, period: str | None = None) -> dict[str, Any]:
    """Resumen AP+AR consolidado por entidad."""
    return accounting_store.accounting_summary(entity_id=entity_id, period=period)


@mcp.tool
def create_receivable_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Crea borrador AR/cobro cliente (idempotente)."""
    return accounting_store.create_receivable_draft(payload)


@mcp.tool
def upsert_receivable(payload: dict[str, Any]) -> dict[str, Any]:
    """Promueve o actualiza cobro AR canónico."""
    return accounting_store.upsert_receivable(payload)


@mcp.tool
def list_receivables_open(entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Lista cobros pendientes (AR abierto)."""
    try:
        return accounting_store.list_receivables_open(entity_id=entity_id, limit=limit)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "entity_id": entity_id}


@mcp.tool
def create_receivable_from_quote(quote_id: str, entity_id: str | None = None) -> dict[str, Any]:
    """Crea borrador AR desde cotización ops_quote_drafts."""
    return accounting_store.create_receivable_from_quote(quote_id, entity_id=entity_id)


@mcp.tool
def approve_quote_for_billing(quote_id: str, approved_by: str = "RAFAEL") -> dict[str, Any]:
    """Aprueba cotización para facturación (sin emisión SRI)."""
    from raphiia_openai.agents import ag17_contifico_bridge_agent as ag17
    return ag17.approve_quote_for_billing(quote_id, approved_by=approved_by)


@mcp.tool
def prepare_invoice_from_quote(
    quote_id: str,
    approved_by: str = "RAFAEL",
    auto_approve: bool = False,
) -> dict[str, Any]:
    """Cotización aprobada → factura borrador HTML + AR contable (ready_for_sri, sin POST Contifico)."""
    from raphiia_openai.agents import ag17_contifico_bridge_agent as ag17
    return ag17.prepare_invoice_from_quote(quote_id, approved_by=approved_by, auto_approve=auto_approve)


@mcp.tool
def get_invoice_record(invoice_record_id: str) -> dict[str, Any]:
    """Metadatos factura borrador (sin HTML completo en respuesta)."""
    from raphiia_openai.operational import billing_pipeline
    return billing_pipeline.get_invoice_record(invoice_record_id)


@mcp.tool
def vero_dispatch(
    message: str,
    channel: str = "mcp",
    entity_id: str = "ent_pcdoctor",
    require_approval: bool = True,
    approved_by: str | None = None,
    client_ref: str | None = None,
    quote_ref: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    """Vero (AG-38): dispatcher comercial NL — cotizar, facturar, informe técnico, entregar."""
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.vero_dispatch(
        message,
        channel=channel,
        entity_id=entity_id,
        require_approval=require_approval,
        approved_by=approved_by,
        client_ref=client_ref,
        quote_ref=quote_ref,
        phone=phone,
    )


@mcp.tool
def quote_client(
    client_ref: str,
    message: str = "",
    entity_id: str = "ent_pcdoctor",
    channel: str = "mcp",
    quote_ref: str | None = None,
    send_whatsapp: bool = False,
    phone: str | None = None,
) -> dict[str, Any]:
    """Vero → AG-16: cotización comercial PCD-COT-*."""
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.quote_client(
        client_ref=client_ref,
        message=message,
        entity_id=entity_id,
        channel=channel,
        quote_ref=quote_ref,
        send_whatsapp=send_whatsapp,
        phone=phone,
    )


@mcp.tool
def invoice_client(
    client_ref: str,
    quote_ref: str | None = None,
    entity_id: str = "ent_pcdoctor",
    channel: str = "mcp",
    require_approval: bool = True,
    approved_by: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    """Vero → AG-17: facturación desde cotización (AR + gate Contifico)."""
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.invoice_client(
        client_ref=client_ref,
        quote_ref=quote_ref,
        entity_id=entity_id,
        channel=channel,
        require_approval=require_approval,
        approved_by=approved_by,
        message=message,
    )


@mcp.tool
def technical_report_client(
    client_ref: str,
    message: str = "",
    site_id: str | None = None,
    visit_id: str | None = None,
    channel: str = "mcp",
) -> dict[str, Any]:
    """Vero → AG-13: informe técnico supervisor PCD-INF-*."""
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.technical_report_client(
        client_ref=client_ref,
        message=message,
        site_id=site_id,
        visit_id=visit_id,
        channel=channel,
    )


@mcp.tool
def get_commercial_mission(mission_id: str) -> dict[str, Any]:
    """Estado de misión comercial Vero."""
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.get_commercial_mission(mission_id)


@mcp.tool
def vero_proactive_briefing(message: str, client_ref: str, entity_id: str = "ent_pcdoctor") -> dict[str, Any]:
    """Vero proactiva: stock, cotizaciones previas, upsell, preguntas antes de cotizar."""
    from raphiia_openai.commercial import vero_orchestrator

    return vero_orchestrator.vero_proactive_briefing(
        message=message,
        client_ref=client_ref,
        entity_id=entity_id,
    )


@mcp.tool
def raul_dispatch(message: str, max_fetch: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """RAUL (AG-39): catálogo local — estado, hidratación Contifico→Mongo, búsqueda."""
    from raphiia_openai.commercial import raul_orchestrator

    return raul_orchestrator.raul_dispatch(
        message,
        channel="mcp",
        max_fetch=max_fetch,
        dry_run=dry_run,
        background=max_fetch is None and not dry_run,
    )


@mcp.tool
def raul_catalog_status() -> dict[str, Any]:
    """RAUL: estado del catálogo local (sin API)."""
    from raphiia_openai.local_catalog_hydrator import get_hydration_state

    return get_hydration_state()


@mcp.tool
def raul_hydrate_catalog(max_fetch: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """RAUL: hidrata fichas Contifico en Mongo (AMD local, 0 créditos cloud)."""
    from raphiia_openai.commercial import raul_orchestrator

    return raul_orchestrator.raul_dispatch(
        "hidrata el catálogo completo",
        channel="mcp",
        max_fetch=max_fetch,
        dry_run=dry_run,
        background=max_fetch is None and not dry_run,
    )


@mcp.tool
def create_purchase_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """MOD-PROCUREMENT: borrador orden de compra (idempotente)."""
    return procurement_store.create_purchase_draft(payload)


@mcp.tool
def upsert_purchase(payload: dict[str, Any]) -> dict[str, Any]:
    """Promueve o actualiza orden de compra canónica."""
    return procurement_store.upsert_purchase(payload)


@mcp.tool
def list_purchases_open(entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Órdenes de compra pendientes de recepción."""
    return procurement_store.list_purchases_open(entity_id=entity_id, limit=limit)


@mcp.tool
def upsert_inventory_item(payload: dict[str, Any]) -> dict[str, Any]:
    """MOD-INVENTORY: crea o actualiza ítem de stock."""
    return inventory_store.upsert_inventory_item(payload)


@mcp.tool
def record_inventory_movement(payload: dict[str, Any]) -> dict[str, Any]:
    """Registra movimiento in/out/adjust de inventario."""
    return inventory_store.record_inventory_movement(payload)


@mcp.tool
def receive_goods(payload: dict[str, Any]) -> dict[str, Any]:
    """Recibe mercadería desde purchase_id o líneas manuales → inventario."""
    return inventory_store.receive_goods(payload)


@mcp.tool
def list_inventory(entity_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Lista inventario y alertas low_stock."""
    return inventory_store.list_inventory(entity_id=entity_id, limit=limit)


@mcp.tool
def list_mcp_tool_profiles(for_model: str | None = None) -> dict[str, Any]:
    """Perfiles versionados (Capability Router F0). Proyección recomendada; legacy tools/list intacto."""
    from raphiia_openai import mcp_profiles

    return mcp_profiles.list_profiles(for_model=for_model)


# --- QuoteOps Build Week bridge (isolated local service) ---

@mcp.tool
def quoteops_start_or_continue_mission(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or continue an idempotent QuoteOps mission."""
    return quoteops_mcp_bridge.call("quoteops_start_or_continue_mission", payload)


@mcp.tool
def quoteops_get_mission(payload: dict[str, Any]) -> dict[str, Any]:
    """Read a QuoteOps mission and its current dossier."""
    return quoteops_mcp_bridge.call("quoteops_get_mission", payload)


@mcp.tool
def quoteops_upsert_commercial_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Store customer or supplier commercial terms in QuoteOps."""
    return quoteops_mcp_bridge.call("quoteops_upsert_commercial_profile", payload)


@mcp.tool
def quoteops_get_sourcing_recommendations(payload: dict[str, Any]) -> dict[str, Any]:
    """Read evidence-backed sourcing recommendations."""
    return quoteops_mcp_bridge.call("quoteops_get_sourcing_recommendations", payload)


@mcp.tool
def quoteops_add_supplier_offer(payload: dict[str, Any]) -> dict[str, Any]:
    """Add an exact supplier offer to an existing QuoteOps mission."""
    return quoteops_mcp_bridge.call("quoteops_add_supplier_offer", payload)


@mcp.tool
def quoteops_record_extracted_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Record structured evidence extracted from a source document."""
    return quoteops_mcp_bridge.call("quoteops_record_extracted_evidence", payload)


@mcp.tool
def quoteops_review_extracted_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Approve or reject extracted QuoteOps evidence."""
    return quoteops_mcp_bridge.call("quoteops_review_extracted_evidence", payload)


@mcp.tool
def quoteops_review_catalog_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Approve or reject a staging catalog draft."""
    return quoteops_mcp_bridge.call("quoteops_review_catalog_draft", payload)


@mcp.tool
def quoteops_update_decision_brief(payload: dict[str, Any]) -> dict[str, Any]:
    """Update confirmed requirements, assumptions, risks, and questions."""
    return quoteops_mcp_bridge.call("quoteops_update_decision_brief", payload)


@mcp.tool
def quoteops_upsert_configuration_alternative(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a technical alternative in QuoteOps."""
    return quoteops_mcp_bridge.call("quoteops_upsert_configuration_alternative", payload)


@mcp.tool
def quoteops_review_configuration_alternative(payload: dict[str, Any]) -> dict[str, Any]:
    """Human-review a technical configuration alternative."""
    return quoteops_mcp_bridge.call("quoteops_review_configuration_alternative", payload)


@mcp.tool
def quoteops_select_package(payload: dict[str, Any]) -> dict[str, Any]:
    """Select an approved QuoteOps package and create editable quote lines."""
    return quoteops_mcp_bridge.call("quoteops_select_package", payload)


@mcp.tool
def quoteops_update_quote(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply human selling prices and tax to an editable quote."""
    return quoteops_mcp_bridge.call("quoteops_update_quote", payload)


@mcp.tool
def quoteops_approve_quote(payload: dict[str, Any]) -> dict[str, Any]:
    """Approve a priced quote and generate its PDF artifact."""
    return quoteops_mcp_bridge.call("quoteops_approve_quote", payload)


@mcp.tool
def quoteops_register_delivery(payload: dict[str, Any]) -> dict[str, Any]:
    """Register delivery of an approved QuoteOps artifact."""
    return quoteops_mcp_bridge.call("quoteops_register_delivery", payload)


@mcp.tool
def route_mcp_tools(
    title: str,
    body: str = "",
    requested_profile: str | None = None,
    granted_scopes: list[str] | None = None,
    max_risk: str = "medium",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Select a bounded MCP tool profile after scope and risk filtering."""
    from raphiia_openai import capability_router

    return capability_router.route_tools(
        title=title,
        body=body,
        requested_profile=requested_profile,
        granted_scopes=granted_scopes,
        max_risk=max_risk,
        tenant_id=tenant_id,
    )


@mcp.tool
def record_collection(payload: dict[str, Any]) -> dict[str, Any]:
    """Registra cobro parcial o total de un receivable."""
    return accounting_store.record_collection(payload)


@mcp.tool
def create_payable_from_whatsapp(message: str, entity_id: str = "ent_pcdoctor") -> dict[str, Any]:
    """Parsea mensaje tipo 'cheque: proveedor 1500 vence 2026-07-20' → payable draft."""
    return accounting_store.create_payable_from_whatsapp(message, entity_id=entity_id)


# --- MOD-COMMUNICATIONS (WhatsApp + contactos) ---

@mcp.tool
def get_whatsapp_status(dual: bool = True) -> dict[str, Any]:
    """Estado Evolution API primary/amd."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.get_whatsapp_status(dual=dual)


@mcp.tool
def send_whatsapp_message(message: str, number: str | None = None, contact_ref: str | None = None, node: str = "primary") -> dict[str, Any]:
    """Envía WhatsApp por número o contact_ref."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.send_whatsapp_message(message, number=number, contact_ref=contact_ref, node=node)


@mcp.tool
def send_whatsapp_draft(draft: str, number: str | None = None, contact_ref: str | None = None, node: str = "primary") -> dict[str, Any]:
    """Envía borrador WhatsApp."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.send_whatsapp_draft(draft, number=number, contact_ref=contact_ref, node=node)


@mcp.tool
def send_whatsapp_document(
    file_path: str,
    number: str | None = None,
    contact_ref: str | None = None,
    caption: str = "",
    node: str = "primary",
) -> dict[str, Any]:
    """Envía PDF/documento por WhatsApp. Flujo: RUNBOOK HUB/RUNBOOK_COTIZACION_WHATSAPP.md."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.send_whatsapp_document(
        file_path, number=number, contact_ref=contact_ref, caption=caption, node=node
    )


@mcp.tool
def send_whatsapp_status(
    content: str = "",
    status_type: str = "text",
    caption: str = "",
    file_path: str | None = None,
    all_contacts: bool = False,
    status_jid_list: list[str] | None = None,
    background_color: str = "#008000",
    font: int = 1,
    node: str = "primary",
) -> dict[str, Any]:
    """Publica un estado/story en WhatsApp vía Evolution."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.send_whatsapp_status(
        content,
        status_type=status_type,
        caption=caption,
        file_path=file_path,
        all_contacts=all_contacts,
        status_jid_list=status_jid_list,
        background_color=background_color,
        font=font,
        node=node,
    )


@mcp.tool
def list_contacts(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Lista contactos canónicos."""
    from raphiia_openai import whatsapp_contacts
    return whatsapp_contacts.list_contacts(query=query, entity_id=entity_id, limit=limit)


@mcp.tool
def list_ops_contacts(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Lista ops_contacts operativos."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.list_ops_contacts(query=query, entity_id=entity_id, limit=limit)


@mcp.tool
def resolve_contact(identifier: str, limit: int = 10) -> dict[str, Any]:
    """Busca contacto por nombre, teléfono o ID."""
    from raphiia_openai import whatsapp_contacts
    return whatsapp_contacts.resolve_contact(identifier, limit=limit)


@mcp.tool
def save_whatsapp_group(payload: dict[str, Any]) -> dict[str, Any]:
    """Guarda o actualiza un grupo WhatsApp canónico."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.save_whatsapp_group(payload)


@mcp.tool
def list_whatsapp_groups(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Lista grupos WhatsApp canónicos."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.list_whatsapp_groups(query=query, entity_id=entity_id, limit=limit)


@mcp.tool
def resolve_whatsapp_group(identifier: str, limit: int = 10) -> dict[str, Any]:
    """Resuelve grupo WhatsApp por nombre, alias o group_jid."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.resolve_whatsapp_group(identifier, limit=limit)


@mcp.tool
def save_ops_contact(payload: dict[str, Any]) -> dict[str, Any]:
    """Guarda contacto operativo."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.save_ops_contact(payload)


@mcp.tool
def link_contact_entities(contact_id: str, entity_ids: list[str]) -> dict[str, Any]:
    """Vincula contacto a entidades."""
    from raphiia_openai import whatsapp_contacts
    return whatsapp_contacts.link_contact_entities(contact_id, entity_ids)


@mcp.tool
def broadcast_whatsapp_groups(
    message: str,
    group_ids: list[str] | None = None,
    labels: list[str] | None = None,
    entity_ids: list[str] | None = None,
    limit: int = 200,
    dry_run: bool = True,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Broadcast segmentado a grupos WhatsApp canónicos."""
    from raphiia_openai import whatsapp_mcp_bridge

    return whatsapp_mcp_bridge.broadcast_whatsapp_groups(
        message,
        group_ids=group_ids,
        labels=labels,
        entity_ids=entity_ids,
        limit=limit,
        dry_run=dry_run,
        approved_by=approved_by,
    )


@mcp.tool
def broadcast_whatsapp_message(message: str, entity_ids: list[str] | None = None, labels: list[str] | None = None, dry_run: bool = True, approved_by: str | None = None) -> dict[str, Any]:
    """Broadcast masivo (dry_run por defecto)."""
    from raphiia_openai import whatsapp_contacts
    return whatsapp_contacts.broadcast_whatsapp(message, entity_ids=entity_ids, labels=labels, dry_run=dry_run, approved_by=approved_by)


@mcp.tool
def create_whatsapp_reminder(body: str, due_at: str | None = None, target_number: str | None = None, entity_id: str | None = None) -> dict[str, Any]:
    """Crea recordatorio WhatsApp."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.create_whatsapp_reminder(body, due_at=due_at, target_number=target_number, entity_id=entity_id)


@mcp.tool
def list_whatsapp_reminders(limit: int = 20) -> dict[str, Any]:
    """Lista recordatorios WhatsApp."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.list_whatsapp_reminders(limit=limit)


@mcp.tool
def process_whatsapp_inbound_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Procesa evento inbound Evolution (cheque:, recordatorio:, etc.)."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.process_whatsapp_inbound_event(payload)


@mcp.tool
def run_due_whatsapp_reminders() -> dict[str, Any]:
    """Ejecuta recordatorios vencidos."""
    from raphiia_openai import whatsapp_mcp_bridge
    return whatsapp_mcp_bridge.run_due_whatsapp_reminders()


@mcp.tool
def get_server_status() -> dict[str, Any]:
    """Fotografía canónica y sin efectos laterales del estado de ambos nodos."""
    from raphiia_openai import whatsapp_service_ops

    snapshot = whatsapp_service_ops.status_snapshot()
    text = whatsapp_service_ops.format_status_text(snapshot=snapshot)
    return {
        "ok": bool(snapshot.get("ok")),
        "text": text,
        # Alias conservado para clientes antiguos; deriva del mismo snapshot.
        "services_text": text,
        "snapshot": snapshot,
        "checked_at": snapshot.get("checked_at"),
        "source": snapshot.get("source"),
        "evidence_ref": snapshot.get("evidence_ref"),
        "tool_call_id": snapshot.get("tool_call_id"),
    }


@mcp.tool
def get_infrastructure_status() -> InfrastructureStatusToolResult:
    """Estado saneado y vivo de los servidores RalphiIA."""
    from raphiia_openai.infrastructure_runtime import get_infrastructure_status as collect
    return collect()


@mcp.tool
def list_monitored_emails(limit: int = 10, importance: str | None = "alta") -> dict[str, Any]:
    """Buzones IMAP activos (email_accounts) y últimos correos clasificados."""
    from raphiia_openai.notifications import email_monitor

    accounts = email_monitor.list_monitored_accounts()
    recent = email_monitor.list_recent_emails(importance=importance, limit=limit)
    return {"ok": True, **accounts, "recent_messages": recent.get("messages", [])}


@mcp.tool
def trigger_email_poll() -> dict[str, Any]:
    """Fuerza POST Swarm /api/v1/email/poll — revisa IMAP y alerta WhatsApp si alta."""
    from raphiia_openai.notifications import email_monitor

    return email_monitor.trigger_email_poll()


@mcp.tool
def sync_email_archive(limit: int = 500) -> dict[str, Any]:
    """Persiste email_messages → email_archive (no borra IMAP origen)."""
    from raphiia_openai.notifications import email_archive

    return email_archive.sync_email_archive_from_messages(limit=limit)


@mcp.tool
def save_productivity_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Guarda evento KPI/ROI de ahorro humano asistido en productivity_metrics."""
    from raphiia_openai import productivity_metrics

    return productivity_metrics.save_productivity_event(payload)


@mcp.tool
def list_productivity_events(limit: int = 50, task_key: str = "") -> dict[str, Any]:
    """Lista eventos KPI/ROI guardados."""
    from raphiia_openai import productivity_metrics

    return productivity_metrics.list_productivity_events(limit=limit, task_key=task_key)


@mcp.tool
def summarize_productivity_events(limit: int = 500) -> dict[str, Any]:
    """Resume ahorro humano asistido acumulado."""
    from raphiia_openai import productivity_metrics

    return productivity_metrics.summarize_productivity_events(limit=limit)


@mcp.tool
def analyze_email_intelligence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Email Intelligence sin efectos: clasifica documento, entidad, ruta y gate humano."""
    from raphiia_openai.notifications import email_router

    return email_router.analyze_email_payload(payload)


@mcp.tool
def process_email_intelligence_mail(mail_id: str, create_task: bool = False, hydrate: bool = True) -> dict[str, Any]:
    """Reprocesa un correo por mail_id. Por defecto NO crea ops_task."""
    from raphiia_openai.notifications import email_router

    return email_router.process_mail_id(mail_id, create_task=create_task, hydrate=hydrate)


@mcp.tool
def email_intelligence_summary(limit: int = 50) -> dict[str, Any]:
    """Resumen de clasificacion documental y ruido suprimido para correo."""
    from raphiia_openai.notifications import email_router

    return email_router.intelligence_summary(limit=limit)


@mcp.tool
def ha_ping() -> dict[str, Any]:
    """Comprueba conexión a Home Assistant local (:8123)."""
    from raphiia_openai import homeassistant_client as ha

    return ha.ping()


@mcp.tool
def ha_list_entities(domain: str | None = None, limit: int = 40) -> dict[str, Any]:
    """Lista entidades HA (light, switch, climate…)."""
    from raphiia_openai import homeassistant_client as ha

    return ha.list_states(domain=domain, limit=limit)


@mcp.tool
def ha_get_entity(entity_id: str) -> dict[str, Any]:
    """Estado de una entidad Home Assistant."""
    from raphiia_openai import homeassistant_client as ha

    return ha.get_state(entity_id)


@mcp.tool
def ha_list_devices(limit: int = 500, integration: str | None = None) -> dict[str, Any]:
    """Lista devices del registry de Home Assistant via WebSocket."""
    from raphiia_openai import homeassistant_client as ha

    return ha.list_devices(limit=limit, integration=integration)


@mcp.tool
def ha_list_entity_registry(limit: int = 500, integration: str | None = None) -> dict[str, Any]:
    """Lista entity registry de Home Assistant via WebSocket."""
    from raphiia_openai import homeassistant_client as ha

    return ha.list_entity_registry(limit=limit, integration=integration)


@mcp.tool
def ha_rename_device(device_id: str, name: str, dry_run: bool = True) -> dict[str, Any]:
    """Renombra device name_by_user en HA; dry_run por defecto."""
    from raphiia_openai import homeassistant_client as ha

    return ha.ha_rename_device(device_id, name, dry_run=dry_run)


@mcp.tool
def ha_rename_entity_name(entity_id: str, name: str, dry_run: bool = True) -> dict[str, Any]:
    """Renombra friendly/name de entidad HA sin cambiar entity_id."""
    from raphiia_openai import homeassistant_client as ha

    return ha.ha_rename_entity_name(entity_id, name, dry_run=dry_run)


@mcp.tool
def ha_search_entity_references(entity_id: str) -> dict[str, Any]:
    """Busca referencias relacionadas a una entidad HA antes de cambios riesgosos."""
    from raphiia_openai import homeassistant_client as ha

    return ha.ha_search_entity_references(entity_id)


@mcp.tool
def ha_batch_rename(items_json: str, dry_run: bool = True) -> dict[str, Any]:
    """Batch rename HA seguro: JSON list, dry_run por defecto, sin entity_id changes."""
    from raphiia_openai import homeassistant_client as ha

    return ha.ha_batch_rename(items_json, dry_run=dry_run)


@mcp.tool
def ha_call_service(domain: str, service: str, entity_id: str | None = None, data_json: str | None = None) -> dict[str, Any]:
    """Invoca servicio HA (light.turn_on, switch.toggle, scene.turn_on…)."""
    import json as _json

    from raphiia_openai import homeassistant_client as ha

    extra = _json.loads(data_json) if data_json else None
    return ha.call_service(domain, service, entity_id=entity_id, data=extra)


@mcp.tool
def ha_turn_on_light(name_or_entity: str) -> dict[str, Any]:
    """Enciende luz por entity_id (light.x) o nombre aproximado."""
    from raphiia_openai import homeassistant_client as ha

    return ha.turn_on_light(name_or_entity)


@mcp.tool
def ha_turn_off_light(name_or_entity: str) -> dict[str, Any]:
    """Apaga luz por entity_id o nombre aproximado."""
    from raphiia_openai import homeassistant_client as ha

    return ha.turn_off_light(name_or_entity)


@mcp.tool
def run_home_ops_cycle() -> dict[str, Any]:
    """Ciclo local: poll email + snapshot HA + digest Ollama (sin cloud)."""
    from raphiia_openai import home_ops_daemon

    return home_ops_daemon.run_cycle()


@mcp.tool
def dmx_status() -> dict[str, Any]:
    """AG-59: estado saneado del motor DMX local, sin IP, universo ni topología LAN."""
    from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59

    return ag59.dmx_status()


@mcp.tool
def dmx_set_scene(scene: str) -> dict[str, Any]:
    """AG-59: aplica solo una escena DMX allowlisted; no acepta canales/universos raw."""
    from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59

    return ag59.dmx_set_scene(scene)


@mcp.tool
def dmx_blackout() -> dict[str, Any]:
    """AG-59: blackout total acotado mediante el motor DMX local."""
    from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59

    return ag59.dmx_blackout()


# --- MOD-AUTODEV (SRE Autonomous Development and Project Approval) ---

@mcp.tool
def list_pending_projects() -> dict[str, Any]:
    """Lista todos los proyectos y hackatones pendientes de revisión y aprobación."""
    from pymongo import MongoClient
    import os
    
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = None
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        db = client["hackathon_autopilot"]
        pending = list(db.pending_approvals.find({"status": "pending"}))
        for p in pending:
            p["id"] = str(p["_id"])
            del p["_id"]
            if "created_at" in p and p["created_at"]:
                p["created_at"] = p["created_at"].isoformat()
        return {"ok": True, "count": len(pending), "projects": pending}
    except Exception as e:
        return {"ok": False, "error": f"Error conectando a MongoDB: {e}"}
    finally:
        if client is not None:
            client.close()


@mcp.tool
def get_project_reuse_analysis(project_id: str) -> dict[str, Any]:
    """Obtiene el análisis de reutilización de código (legos), arquitectura y requerimientos de un proyecto."""
    from pymongo import MongoClient
    from bson import ObjectId
    import os
    
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = None
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        db = client["hackathon_autopilot"]
        p = db.pending_approvals.find_one({"_id": ObjectId(project_id)})
        if not p:
            return {"ok": False, "error": "Proyecto no encontrado"}
            
        p["id"] = str(p["_id"])
        del p["_id"]
        if "created_at" in p and p["created_at"]:
            p["created_at"] = p["created_at"].isoformat()
            
        return {"ok": True, "analysis": p}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if client is not None:
            client.close()


@mcp.tool
def approve_and_develop_project(project_id: str, custom_requirements: str | None = None) -> dict[str, Any]:
    """Autoriza un proyecto owner-approved y lo enruta al dev swarm local sin ralfia:admin."""
    project_ref = (project_id or "").strip()
    if not project_ref:
        return {"ok": False, "error": "project_id_required"}

    analysis = get_project_reuse_analysis(project_ref)
    analysis_data = analysis.get("analysis") if analysis.get("ok") else {}
    if not isinstance(analysis_data, dict):
        analysis_data = {}

    candidate_repo = (
        analysis_data.get("repo")
        or analysis_data.get("github_repo")
        or analysis_data.get("repository")
        or analysis_data.get("related_repo")
        or (project_ref if "/" in project_ref else "")
    )
    resolved_project = project_runtime_registry.resolve_project(
        project_id=project_ref if "/" not in project_ref else "",
        repo=candidate_repo,
        node="primary",
    )
    if not resolved_project.get("ok"):
        return {
            "ok": False,
            "stage": "project_runtime_resolve",
            "error": "project_runtime_resolution_failed",
            "project_id": project_ref,
            "candidate_repo": candidate_repo,
            "resolution": resolved_project,
            "actionable": "Register the project with project_runtime_register/project_runtime_bootstrap; no silent fallback is allowed.",
        }
    repo = str((resolved_project.get("project") or {}).get("repo") or "").strip()
    if not repo:
        return {
            "ok": False,
            "stage": "project_runtime_resolve",
            "error": "repo_missing_after_resolution",
            "project_id": project_ref,
            "resolution": resolved_project,
        }
    reqs = (custom_requirements or analysis_data.get("requirements") or analysis_data.get("description") or "").strip()
    if not reqs:
        reqs = f"Owner-approved local development entrypoint for {project_ref}. Prepare an isolated worktree and produce a bounded local implementation plan."
    legos = analysis_data.get("suggested_legos") or []
    if legos:
        reqs = f"{reqs}\n\nSuggested reusable components: {legos}"

    policy = local_execution_plane.repo_policy_status(repo)
    if not policy.get("ok"):
        return {
            "ok": False,
            "stage": "repo_policy_status",
            "error": "repo_not_owner_approved_or_not_allowlisted",
            "repo": repo,
            "policy": policy,
            "admin_scope_required": False,
            "required_scope": "ralfia:agents",
        }

    fingerprint = hashlib.sha1(f"{project_ref}|{repo}|{reqs}".encode("utf-8")).hexdigest()[:12]
    task_id = f"approve_{fingerprint}"
    branch = f"local-agent/approve-{fingerprint}"
    correlation_id = f"approve-develop-{fingerprint}"
    idempotency_key = f"approve-and-develop-{fingerprint}"
    objective = (
        "ONE-TIME owner-approved local development entrypoint.\n"
        "Use only the local dev swarm, local models and allowlisted repo/worktree operations. "
        "Do not touch protected branches, secrets, cloud billing or production deploys.\n\n"
        f"Project: {project_ref}\nRepo: {repo}\nRequirements:\n{reqs}"
    )

    execution = dev_swarm_scheduler.execute_ad_hoc_objective(
        repo=repo,
        objective=objective[:4000],
        task_id=task_id,
        correlation_id=correlation_id,
        preferred_branch=branch,
        entrypoint="approve_and_develop_project",
        dry_run=False,
    )
    return {
        "ok": bool(execution.get("ok")),
        "message": "Proyecto aprobado y enrutado al dev swarm local con scope ralfia:agents.",
        "admin_scope_required": False,
        "required_scope": "ralfia:agents",
        "repo": repo,
        "project_runtime": {
            "project_id": (resolved_project.get("project") or {}).get("project_id"),
            "project_path": resolved_project.get("project_path"),
            "node": resolved_project.get("node"),
        },
        "task_id": task_id,
        "work_branch": execution.get("branch") or branch,
        "canonical_entrypoint": "dev_swarm_scheduler.execute_ad_hoc_objective",
        "execution": execution,
        "launch": execution.get("launch"),
        "executor": execution.get("executor"),
        "worker": execution.get("worker"),
    }



@mcp.tool
def search_email_archive(query: str | None = None, account_address: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Busca en archivo permanente de correo."""
    from raphiia_openai.notifications import email_archive

    return email_archive.search_email_archive(query=query, account_address=account_address, limit=limit)


@mcp.tool
def get_email_archive_status() -> dict[str, Any]:
    """Estado del archivo permanente de correo."""
    from raphiia_openai.notifications import email_archive

    return email_archive.get_email_archive_status()


@mcp.tool
def get_email_archive_message(mail_id: str, refresh_token: bool = True) -> dict[str, Any]:
    """Detalle + deep link autenticado (HMAC) de un correo en email_archive."""
    from raphiia_openai.notifications import email_archive

    return email_archive.get_email_archive_message(mail_id, refresh_token=refresh_token)


@mcp.tool
def send_general_email(
    to_addr: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
    attachment_name: str | None = None,
    from_account: str | None = None,
) -> dict[str, Any]:
    """Envía un correo electrónico usando SMTP configurado en email_accounts (ej. rlopez@innerchispa.us)."""
    from raphiia_openai.notifications.email_client import send_email
    return send_email(
        to_addr=to_addr,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
        attachment_name=attachment_name,
        from_account=from_account,
    )


@mcp.tool
def create_web_content(
    content_id: str,
    content_type: str,
    title: str,
    slug: str,
    description: str,
    technologies: list[str] | None = None,
    images: list[dict[str, Any]] | None = None,
    demo_url: str | None = None,
    github_url: str | None = None,
    visibility: str = "public",
    theme: str = "default",
) -> dict[str, Any]:
    """Crea un borrador de contenido para la web corporativa de InnerChispa (proyectos o hackatones)."""
    from raphiia_openai.operational import web_content_manager
    return web_content_manager.create_web_content(
        content_id=content_id,
        content_type=content_type,
        title=title,
        slug=slug,
        description=description,
        technologies=technologies,
        images=images,
        demo_url=demo_url,
        github_url=github_url,
        visibility=visibility,
        theme=theme,
    )


@mcp.tool
def update_web_content(content_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Actualiza campos específicos de un contenido web existente."""
    from raphiia_openai.operational import web_content_manager
    return web_content_manager.update_web_content(content_id, patch)


@mcp.tool
def change_web_content_status(
    content_id: str,
    new_status: str,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Controla el flujo de estados de publicación (draft -> review -> approved -> published)."""
    from raphiia_openai.operational import web_content_manager
    return web_content_manager.change_web_content_status(content_id, new_status, approved_by)


@mcp.tool
def list_web_content(
    content_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Lista las entradas de contenido web registradas (proyectos y hackatones)."""
    from raphiia_openai.operational import web_content_manager
    return web_content_manager.list_web_content(content_type, status, limit)


@mcp.tool
def export_web_content_for_astro(output_dir: str) -> dict[str, Any]:
    """Genera los archivos JSON/Markdown en el directorio de staging de la web Astro."""
    from raphiia_openai.operational import web_content_manager
    return web_content_manager.export_web_content_for_astro(output_dir)


@mcp.tool
def get_disk_steward_status(include_candidates: bool = True) -> dict[str, Any]:
    """AG-37: inventario multi-disco, backups, tareas AG-36 y candidatos a mover (requieren WhatsApp)."""
    from raphiia_openai import disk_steward

    return disk_steward.build_status(include_candidates=include_candidates)


@mcp.tool
def sync_hackathon_portfolio_to_web_content(
    source_path: str | None = None,
    default_status: str = "review",
    publish_safe_items: bool = True,
) -> dict[str, Any]:
    """Sincroniza el inventario canónico de hackathons/proyectos con la cola Web/Astro."""
    from raphiia_openai.operational import web_content_manager

    return web_content_manager.sync_hackathon_portfolio(
        source_path,
        default_status=default_status,
        publish_safe_items=publish_safe_items,
    )


@mcp.tool
def get_whatsapp_commands_help() -> dict[str, Any]:
    """Diccionario de comandos WhatsApp inbound (estado, correo, poll, etc.)."""
    from raphiia_openai import whatsapp_commands

    return whatsapp_commands.get_whatsapp_commands_help()


@mcp.tool
def preview_whatsapp_agent_reply(message: str, sender: str | None = None) -> dict[str, Any]:
    """Simula respuesta agente WhatsApp (Ollama local + contexto) sin enviar WA."""
    from raphiia_openai import whatsapp_conversational

    return whatsapp_conversational.conversational_reply(message, sender=sender or "593999059000")


@mcp.tool
def mcp_version(session_id: str | None = None) -> dict[str, Any]:
    """Versión viva del bridge, catálogo y manifest."""
    return mcp_diagnostics.mcp_version(session_id=session_id)


@mcp.tool
def list_mcp_capabilities() -> dict[str, Any]:
    """Catálogo vivo completo de tools, schemas, recursos y scopes."""
    return mcp_diagnostics.list_mcp_capabilities()


@mcp.tool
def describe_tool(tool_name: str) -> dict[str, Any]:
    """Describe una tool por nombre con schema y scopes."""
    return mcp_diagnostics.describe_tool(tool_name)


@mcp.tool
def system_debug() -> dict[str, Any]:
    """Diagnóstico técnico de MCP, OAuth, gateway y errores recientes."""
    return mcp_diagnostics.system_debug()


@mcp.tool
def diagnose_mcp_session(
    client_tool_count: int | None = None,
    client_catalog_version: str | None = None,
    client_seen_tools: list[str] | None = None,
    session_id: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Detecta catálogo viejo, refresco OAuth o problemas de stream."""
    return mcp_diagnostics.diagnose_mcp_session(
        client_tool_count=client_tool_count,
        client_catalog_version=client_catalog_version,
        client_seen_tools=client_seen_tools,
        session_id=session_id,
        user_agent=user_agent,
    )


@mcp.tool
def documentary_state() -> dict[str, Any]:
    """Estado vivo del Agente Documental y último snapshot sincronizado."""
    return mongo_store.get_coordination_state("documentary_sync")


@mcp.tool
def list_recent_changes(limit: int = 20, project: str | None = None) -> dict[str, Any]:
    """Cambios recientes de coordinación/documentación."""
    return mongo_store.list_recent_changes(limit=limit, project=project)


@mcp.tool
def register_change(
    agent: str,
    project: str,
    path: str,
    summary: str,
    before_hash: str | None = None,
    after_hash: str | None = None,
    service: str | None = None,
) -> dict[str, Any]:
    """Registra un cambio documental o de servicio."""
    change = mongo_store.register_change(
        agent=agent,
        project=project,
        path=path,
        summary=summary,
        before_hash=before_hash,
        after_hash=after_hash,
        service=service,
    )
    return {"ok": True, "change": change}


@mcp.tool
def sync_documentation_now(mode: str = "dry_run", limit: int = 50) -> dict[str, Any]:
    """Sincroniza documentación: documentary daemon + preview/push Notion (mode=dry_run|apply)."""
    from pathlib import Path
    from raphiia_openai import notion_bridge, ralfia_time
    from raphiia_openai.documentary_daemon import run_once

    changes = run_once()
    notion = notion_bridge.sync_documentation_to_notion(mode=mode, limit=limit)
    return {
        "ok": True,
        "documentary_changes": changes,
        "notion_sync": notion,
        "mode": mode,
        "ts_display": ralfia_time.format_log(),
        "coordination_root": str(Path("/home/rlopez/data/ai_coordination")),
    }


@mcp.tool
def sync_creator_os_projects(dry_run: bool = True, limit: int | None = None) -> dict[str, Any]:
    """Harmoniza DB08 Proyectos (Creator OS) con rutas servidor + Mongo — sin duplicar."""
    from raphiia_openai import notion_projects_sync

    return notion_projects_sync.sync_creator_os_projects(dry_run=dry_run, limit=limit)


@mcp.tool
def get_creator_os_project_map(limit: int = 50) -> dict[str, Any]:
    """Mapa proyectos Creator OS ↔ servidor (índice Mongo ralfia_notion_projects_index)."""
    from raphiia_openai import notion_projects_sync

    return notion_projects_sync.get_creator_os_project_map(limit=limit)


@mcp.tool
def get_contifico_status() -> dict[str, Any]:
    """Estado conexión API Contifico (read-only)."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.get_contifico_status()


@mcp.tool
def contifico_capabilities() -> dict[str, Any]:
    """Mapa de endpoints Contifico y plan de migración a MOD-ACCOUNTING."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.contifico_capabilities()


@mcp.tool
def list_contifico_personas(page: int = 1, size: int = 50, role: str | None = None) -> dict[str, Any]:
    """Clientes/proveedores desde Contifico."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.list_contifico_personas(page=page, size=size, role=role)


@mcp.tool
def list_contifico_documentos(page: int = 1, size: int = 20, tipo_documento: str | None = None) -> dict[str, Any]:
    """Facturas/compras/retenciones paginadas (FAC, etc.)."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.list_contifico_documentos(page=page, size=size, tipo_documento=tipo_documento)


@mcp.tool
def list_contifico_banco_movimientos(page: int = 1, size: int = 50) -> dict[str, Any]:
    """Movimientos bancarios Contifico."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.list_contifico_banco_movimientos(page=page, size=size)


@mcp.tool
def normalize_contifico_all(
    fetch_personas_api: bool = True,
    link_crm: bool = True,
    normalize_ledger: bool = True,
) -> dict[str, Any]:
    """Normaliza Contífico completo: personas (IDs sintéticos si API id=null), docs, ledger, CRM."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.normalize_contifico_all(
        fetch_personas_api=fetch_personas_api,
        link_crm=link_crm,
        normalize_ledger=normalize_ledger,
    )


@mcp.tool
def backfill_contifico_orphan_personas(limit: int | None = None, sleep_ms: int = 150) -> dict[str, Any]:
    """Recupera cliente en docs Contífico con persona_id vacío (lee detalle API persona.ruc/nombre)."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.backfill_orphan_document_personas(limit=limit, sleep_ms=sleep_ms)


@mcp.tool
def link_contifico_personas_to_crm(only_clients: bool = False, limit: int | None = None) -> dict[str, Any]:
    """Enlaza contifico_personas → crm_parties (+ ops_clients si es cliente)."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.link_contifico_personas_to_crm(only_clients=only_clients, limit=limit)


@mcp.tool
def normalize_contifico_ledger() -> dict[str, Any]:
    """Normaliza mirror Contífico: bancos, movimientos, transacciones, cuentas, centros, bodegas."""
    from raphiia_openai import contifico_ledger

    return contifico_ledger.normalize_all_ledger()


@mcp.tool
def list_contifico_bank_accounts() -> dict[str, Any]:
    """Cuentas bancarias Contífico normalizadas + saldo calculado."""
    from raphiia_openai import contifico_ledger

    return contifico_ledger.list_bank_accounts()


@mcp.tool
def get_contifico_bank_balance(account_query: str | None = None) -> dict[str, Any]:
    """Saldo / movimientos sumados de cuenta(s) bancaria Contífico."""
    from raphiia_openai import contifico_ledger

    return contifico_ledger.get_bank_account_balance(account_query)


@mcp.tool
def search_contifico_bank_movements(
    account_id: str | None = None,
    persona_query: str | None = None,
    year: int | None = None,
    tipo: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Busca movimientos bancarios Contífico normalizados."""
    from raphiia_openai import contifico_ledger

    return contifico_ledger.search_bank_movements(
        account_id=account_id,
        persona_query=persona_query,
        year=year,
        tipo=tipo,
        limit=limit,
    )


@mcp.tool
def search_contifico_transactions(
    persona_query: str | None = None,
    year: int | None = None,
    tipo: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Busca transacciones/caja Contífico normalizadas."""
    from raphiia_openai import contifico_ledger

    return contifico_ledger.search_transactions(
        persona_query=persona_query,
        year=year,
        tipo=tipo,
        limit=limit,
    )


@mcp.tool
def search_contifico_accounts(query: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Busca plan de cuentas Contífico normalizado."""
    from raphiia_openai import contifico_ledger

    return contifico_ledger.search_accounts(query=query, limit=limit)


@mcp.tool
def query_contifico_stats(
    tipo_documento: str | None = "COT",
    year: int | None = None,
    persona_query: str | None = None,
    top: int = 10,
) -> dict[str, Any]:
    """Estadísticas Contífico: conteos/montos por cliente (ej. COT 2026)."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.query_contifico_stats(
        tipo_documento=tipo_documento,
        year=year,
        persona_query=persona_query,
        top=top,
    )


@mcp.tool
def search_contifico_documents(
    query: str | None = None,
    tipo_documento: str | None = None,
    persona_id: str | None = None,
    year: int | None = None,
    documento: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Busca documentos Contífico normalizados (número, cliente, tipo, año)."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.search_contifico_documents(
        query=query,
        tipo_documento=tipo_documento,
        persona_id=persona_id,
        year=year,
        documento=documento,
        limit=limit,
    )


@mcp.tool
def get_contifico_client_summary(query: str, year: int | None = None) -> dict[str, Any]:
    """Resumen Contífico de un cliente por nombre/RUC: COT/FAC counts y recientes."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.get_contifico_client_summary(query=query, year=year)


@mcp.tool
def resolve_contifico_persona(query: str, limit: int = 10) -> dict[str, Any]:
    """Resuelve persona Contífico por nombre, RUC o persona_id."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.resolve_contifico_persona(query, limit=limit)


@mcp.tool
def contifico_inventory_summary() -> dict[str, Any]:
    """Inventario normalizado Contífico (docs, personas, tipos, huérfanos)."""
    from raphiia_openai import contifico_normalize

    return contifico_normalize.contifico_inventory_summary()


@mcp.tool
def contifico_analytics_capabilities() -> dict[str, Any]:
    """Catálogo DSL Contífico analytics (métricas/dimensiones allowlist) — piloto RO."""
    from raphiia_openai import contifico_analytics

    return contifico_analytics.analytics_capabilities()


@mcp.tool
def contifico_resolve_entity(query: str, entity_type: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Resuelve persona/documento/banco Contífico con ranking (piloto analytics)."""
    from raphiia_openai import contifico_analytics

    return contifico_analytics.resolve_entity(query, entity_type=entity_type, limit=limit)


@mcp.tool
def contifico_query(
    domain: str = "sales",
    measures: list[str] | None = None,
    dimensions: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    sort: str | None = None,
    limit: int = 20,
    include_details: bool = False,
    natural_language: str | None = None,
) -> dict[str, Any]:
    """Query analítica Contífico read-only (DSL allowlist). No crea tool por pregunta."""
    from raphiia_openai import contifico_analytics

    return contifico_analytics.contifico_query(
        domain=domain,
        measures=measures,
        dimensions=dimensions,
        filters=filters,
        sort=sort,
        limit=limit,
        include_details=include_details,
        natural_language=natural_language,
    )


@mcp.tool
def contifico_get_document(document_id: str | None = None, number: str | None = None) -> dict[str, Any]:
    """Detalle documento Contífico por id o número (COT-/FAC-…)."""
    from raphiia_openai import contifico_analytics

    return contifico_analytics.get_document(document_id=document_id, number=number)


@mcp.tool
def contifico_get_party_360(query: str, period_year: int | None = None) -> dict[str, Any]:
    """Vista 360 cliente Contífico: ventas, COT, cartera, bancos (read-only)."""
    from raphiia_openai import contifico_analytics

    return contifico_analytics.get_party_360(query, period_year=period_year)


@mcp.tool
def contifico_explain_metric(metric: str) -> dict[str, Any]:
    """Explica métrica canónica Contífico (fórmula + fuentes)."""
    from raphiia_openai import contifico_analytics

    return contifico_analytics.explain_metric(metric)


@mcp.tool
def refresh_capability_registry_shadow() -> dict[str, Any]:
    """Persiste inventario/registry en sombra (no altera tools/list legacy)."""
    from raphiia_openai import capability_registry

    return capability_registry.persist_shadow_registry()


@mcp.tool
def get_capability_registry_summary() -> dict[str, Any]:
    """Resumen registry sombra + fingerprint catálogo."""
    from raphiia_openai import capability_registry

    return capability_registry.get_registry_summary()


@mcp.tool
def get_mcp_profile(name: str) -> dict[str, Any]:
    """Devuelve un perfil versionado (toolset pinneable)."""
    from raphiia_openai import mcp_profiles

    return mcp_profiles.get_profile(name)


@mcp.tool
def sync_contifico_snapshot(resources: list[str] | None = None, page: int = 1, size: int = 50, dry_run: bool = True) -> dict[str, Any]:
    """Espejo read-only Contifico → Mongo (dry_run por defecto)."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.sync_contifico_snapshot(resources=resources, page=page, size=size, dry_run=dry_run)


@mcp.tool
def import_contifico_all(dry_run: bool = True) -> dict[str, Any]:
    """Importación completa Contifico → Mongo: personas, bancos, catálogo, documentos FAC/COT."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.import_contifico_all(dry_run=dry_run)


@mcp.tool
def import_contifico_full_sync(dry_run: bool = True, resume: bool = True, max_documents: int | None = None) -> dict[str, Any]:
    """Importación completa Contifico con throttling, checkpoint y numeración COT/FAC."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.import_contifico_full_sync(dry_run=dry_run, resume=resume, max_documents=max_documents)


@mcp.tool
def get_contifico_sync_status() -> dict[str, Any]:
    """Progreso del import Contifico (fase, conteos, rate limit)."""
    from raphiia_openai import contifico_bridge

    return contifico_bridge.get_contifico_sync_status()


@mcp.tool
def get_notion_status() -> dict[str, Any]:
    """Estado del puente Notion API (token, DB, contrato doc_id)."""
    from raphiia_openai import notion_bridge

    return notion_bridge.get_notion_status()


@mcp.tool
def get_notion_schema_blueprint() -> dict[str, Any]:
    """Blueprint de la DB Docs — RalfIA (Numerados) y frontmatter esperado."""
    from raphiia_openai import notion_bridge

    return notion_bridge.get_notion_schema_blueprint()


@mcp.tool
def bootstrap_notion_schema(dry_run: bool = True) -> dict[str, Any]:
    """Crea la DB Notion numerada bajo NOTION_DOCS_PARENT_PAGE_ID (dry_run por defecto)."""
    from raphiia_openai import notion_bridge

    return notion_bridge.bootstrap_notion_schema(dry_run=dry_run)


@mcp.tool
def bootstrap_notion_coordination_db(dry_run: bool = True) -> dict[str, Any]:
    """Crea DB Notion «RalfIA Coordination» (órdenes ↔ ops_tasks)."""
    from raphiia_openai import notion_coordination

    return notion_coordination.bootstrap_notion_coordination_db(dry_run=dry_run)


@mcp.tool
def get_notion_coordination_contract() -> dict[str, Any]:
    """Contrato cerrado: schema DB, webhook dedupe, respuesta Notion."""
    from raphiia_openai import notion_coordination

    return notion_coordination.get_notion_coordination_contract()


@mcp.tool
def preview_notion_sync(limit: int = 50) -> dict[str, Any]:
    """Preview de qué docs se crearían/actualizarían/saltarían en Notion (sin escribir)."""
    from raphiia_openai import notion_bridge

    return notion_bridge.preview_notion_sync(limit=limit)


@mcp.tool
def notion_upsert_doc_metadata(doc_id: str, fields: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Upsert metadata en DB Notion por doc_id (sin tocar cuerpo)."""
    from raphiia_openai import notion_bridge

    return notion_bridge.notion_upsert_doc_metadata(doc_id, fields, dry_run=dry_run)


@mcp.tool
def notion_push_doc(
    doc_id: str,
    title: str,
    content_md: str,
    source_path: str,
    status: str = "Active",
    domain: str = "Ops",
    source_last_modified: str | None = None,
    sync_hash: str | None = None,
    audience: str = "internal",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Push idempotente de un doc a Notion (Patrón 1: metadata DB + cuerpo en página)."""
    from raphiia_openai import notion_bridge

    return notion_bridge.notion_push_doc(
        doc_id,
        title,
        content_md,
        source_path,
        status=status,
        domain=domain,
        source_last_modified=source_last_modified,
        sync_hash=sync_hash,
        audience=audience,
        dry_run=dry_run,
    )


@mcp.tool
def notion_append_audit_event(doc_id: str, event_type: str, payload: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Registra evento de auditoría del bridge Notion."""
    from raphiia_openai import notion_bridge

    return notion_bridge.notion_append_audit_event(doc_id, event_type, payload, dry_run=dry_run)


@mcp.tool
def search_notion_pages(query: str, limit: int = 10) -> dict[str, Any]:
    """Busca páginas en Notion vía API del servidor."""
    from raphiia_openai import notion_bridge

    return notion_bridge.search_notion_pages(query, limit=limit)


@mcp.tool
def push_coordination_doc_to_notion(
    relative_path: str,
    parent_page_id: str | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Publica o actualiza un documento de ai_coordination en Notion."""
    from raphiia_openai import notion_bridge

    return notion_bridge.push_coordination_doc_to_notion(
        relative_path,
        parent_page_id=parent_page_id,
        max_chars=max_chars,
    )


@mcp.tool
def add_notion_page_comment(page_id: str, comment: str) -> dict[str, Any]:
    """Añade un comentario a una página Notion."""
    from raphiia_openai import notion_bridge

    return notion_bridge.add_notion_page_comment(page_id, comment)


@mcp.tool
def get_notion_sync_log(limit: int = 20) -> dict[str, Any]:
    """Lista el historial de documentos sincronizados a Notion."""
    from raphiia_openai import notion_bridge

    return notion_bridge.get_notion_sync_log(limit=limit)


@mcp.tool
def get_notion_webhook_setup() -> dict[str, Any]:
    """URL y pasos para configurar webhooks Notion en la integración."""
    from raphiia_openai import notion_webhook

    return notion_webhook.get_notion_webhook_setup()


@mcp.tool
def list_coordination_files(path: str | None = None) -> dict[str, Any]:
    """Lista archivos y carpetas permitidos dentro de ai_coordination."""
    return coordination_docs.list_coordination_files(path=path)


@mcp.tool
def list_coordination_docs(category: str | None = None) -> dict[str, Any]:
    """Alias de compatibilidad."""
    return coordination_docs.list_coordination_docs(category=category)


@mcp.tool
def read_coordination_file(relative_path: str, max_chars: int = 12000) -> dict[str, Any]:
    """Lee un archivo permitido de ai_coordination."""
    try:
        return coordination_docs.read_coordination_file(relative_path, max_chars=max_chars)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool
def read_coordination_doc(relative_path: str, max_chars: int = 24000) -> dict[str, Any]:
    """Alias de compatibilidad."""
    try:
        return coordination_docs.read_coordination_doc(relative_path, max_chars=max_chars)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool
def search_coordination_docs(query: str, limit: int = 10) -> dict[str, Any]:
    """Busca texto en documentación de coordinación del servidor."""
    return coordination_docs.search_coordination_docs(query, limit=limit)


@mcp.tool
def get_chatgpt_workspace() -> dict[str, Any]:
    """INBOX/OUTBOX/journal/notas de ChatGPT."""
    return coordination_docs.get_chatgpt_workspace()


@mcp.tool
def save_chatgpt_note(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Guarda nota en chatgpt/notes/ y registra evento en Mongo."""
    return coordination_docs.save_chatgpt_note(title, body, tags=tags)


@mcp.tool
def save_chatgpt_handoff(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Guarda handoff oficial de ChatGPT."""
    return coordination_docs.save_chatgpt_handoff(title, body, tags=tags)


@mcp.tool
def save_chatgpt_draft(title: str, body: str, channel: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    """Guarda borrador de ChatGPT sin publicar."""
    return coordination_docs.save_chatgpt_draft(title, body, channel=channel, tags=tags)


@mcp.tool
def get_agent_mailboxes(
    agent: str | None = None,
    limit: int = 20,
    include_files: bool = True,
) -> dict[str, Any]:
    """Mensajes recientes desde Mongo y cola legible de INBOX/OUTBOX Markdown."""
    return coordination_docs.get_agent_mailboxes(
        agent=agent,
        limit=limit,
        include_files=include_files,
    )


@mcp.tool
def write_agent_message(
    target_agent: str,
    title: str,
    body: str,
    priority: str | None = None,
    from_agent: str = "CHATGPT",
) -> dict[str, Any]:
    """Alias de create_agent_message (canal único). from_agent por defecto CHATGPT."""
    from raphiia_openai.memory import agent_messages as _am

    return _am.write_agent_message(
        target_agent=target_agent,
        title=title,
        body=body,
        priority=priority,
        from_agent=from_agent,
    )


@mcp.tool
def list_agent_messages(
    agent: str | None = None,
    status: str | None = None,
    limit: int = 20,
    role: str = "inbox",
) -> dict[str, Any]:
    """Lista mensajes del canal único. role=inbox (recibidos) | sent | all."""
    from raphiia_openai.memory import agent_messages as _am

    return _am.list_agent_messages(agent=agent, status=status, limit=limit, role=role)


@mcp.tool
def get_coordination_live() -> dict[str, Any]:
    """Estado vivo: revisión única, lecturas obligatorias, órdenes ops, mensajes abiertos."""
    from raphiia_openai import coordination_live

    return coordination_live.get_coordination_live()


@mcp.tool
def ack_coordination_revision(agent: str, revision: int) -> dict[str, Any]:
    """Marca que un agente leyó la revisión actual de coordinación."""
    from raphiia_openai import coordination_live

    return coordination_live.ack_coordination_revision(agent, revision)


@mcp.tool
def create_ops_task(
    assignee: str,
    title: str,
    checklist: list[str] | str | None = None,
    evidence_required: list[str] | str | None = None,
    priority: str = "normal",
    from_agent: str = "RAFAEL",
    correlation_id: str | None = None,
) -> OpsTaskToolResult:
    """Orden formal con checklist + evidencia → Mongo ops_tasks + INBOX assignee."""
    from raphiia_openai import coordination_live

    return coordination_live.create_ops_task(
        assignee=assignee,
        title=title,
        checklist=checklist,
        evidence_required=evidence_required,
        priority=priority,
        from_agent=from_agent,
        correlation_id=correlation_id,
    )


@mcp.tool
def complete_ops_task(task_id: str, status: str = "completed", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cierra orden ops con evidencia verificable."""
    from raphiia_openai import coordination_live

    return coordination_live.complete_ops_task(task_id, status=status, evidence=evidence)


@mcp.tool
def codex_continuity_checkpoint(
    task_id: str,
    status: str,
    next_action: str,
    correlation_id: str = "",
    repo: str = "",
    work_branch: str = "",
    files_touched: list[str] | None = None,
    tests: list[str] | None = None,
    blockers: list[str] | None = None,
    notes: str = "",
    actor: str = "codex",
) -> dict[str, Any]:
    """Codex continuity: guarda checkpoint durable en Mongo + codex/handoff."""
    from raphiia_openai import coordination_ingest, mongo_store

    if not task_id.strip() or not status.strip() or not next_action.strip():
        return {"ok": False, "error": "task_id_status_next_action_required"}
    payload = {
        "task_id": task_id,
        "status": status,
        "correlation_id": correlation_id,
        "repo": repo,
        "work_branch": work_branch,
        "files_touched": files_touched or [],
        "tests": tests or [],
        "blockers": blockers or [],
        "next_action": next_action,
        "notes": notes,
        "actor": actor,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["checkpoint_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    coord_root = Path(os.getenv("RALFIA_COORDINATION_ROOT", "/home/rlopez/data/ai_coordination"))
    handoff_dir = coord_root / "codex" / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_task = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in task_id)[:80]
    path = handoff_dir / f"{stamp}_{safe_task}_{payload['checkpoint_hash']}.md"
    body = "\n".join([
        f"# Codex Continuity Checkpoint - {task_id}",
        "",
        f"- status: `{status}`",
        f"- correlation_id: `{correlation_id}`",
        f"- repo: `{repo}`",
        f"- work_branch: `{work_branch}`",
        f"- checkpoint_hash: `{payload['checkpoint_hash']}`",
        "",
        "## Next Action",
        next_action,
        "",
        "## Files Touched",
        "\n".join(f"- `{item}`" for item in (files_touched or [])) or "- none",
        "",
        "## Tests",
        "\n".join(f"- {item}" for item in (tests or [])) or "- none",
        "",
        "## Blockers",
        "\n".join(f"- {item}" for item in (blockers or [])) or "- none",
        "",
        "## Notes",
        notes or "none",
        "",
    ])
    path.write_text(body, encoding="utf-8")
    log = mongo_store.log_coordination(
        agent=actor.upper(),
        summary=f"Codex continuity checkpoint {task_id}: {status}",
        event="codex_continuity_checkpoint",
        project="inneros",
        tool_used="codex_continuity_checkpoint",
        metadata={**payload, "handoff_path": str(path)},
    )
    message = coordination_ingest.ingest_agent_message(
        from_agent=actor.upper(),
        target_agent="CODEX",
        title=f"Continuity checkpoint {task_id}: {status}",
        body=body,
        priority="p0" if status.lower() in {"blocked", "in_progress"} else "normal",
        correlation_id=correlation_id or task_id,
        message_type="handoff",
        payload={**payload, "handoff_path": str(path)},
        idempotency_key=f"codex-continuity-{task_id}-{payload['checkpoint_hash']}",
    )
    return {"ok": True, "checkpoint": payload, "handoff_path": str(path), "log": log, "message": message}


@mcp.tool
def update_ops_task_state(
    task_id: str,
    status: str,
    actor: str,
    evidence: dict[str, Any] | None = None,
    expected_revision: int | None = None,
    force_handoff: bool = False,
) -> dict[str, Any]:
    """RACB: transition task state with ownership and revision checks."""
    from raphiia_openai import coordination_live

    return coordination_live.update_ops_task_state(
        task_id=task_id,
        status=status,
        actor=actor,
        evidence=evidence,
        expected_revision=expected_revision,
        force_handoff=force_handoff,
    )


@mcp.tool
def heartbeat_ops_task(
    task_id: str,
    actor: str,
    next_action: str | None = None,
    blocker: str | None = None,
    files_touched: list[str] | None = None,
) -> dict[str, Any]:
    """RACB: heartbeat auditable para una tarea aceptada o activa."""
    from raphiia_openai import coordination_live

    return coordination_live.heartbeat_ops_task(
        task_id=task_id,
        actor=actor,
        next_action=next_action,
        blocker=blocker,
        files_touched=files_touched,
    )


@mcp.tool
def manage_coordination_lock(
    action: str,
    resource_id: str = "",
    agent: str = "",
    task_id: str | None = None,
    ttl_seconds: int = 1800,
    force: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """RACB: acquire, renew, release, inspect or list resource locks."""
    from raphiia_openai import racb_locks

    return racb_locks.manage_coordination_lock(
        action=action,
        resource_id=resource_id,
        agent=agent,
        task_id=task_id,
        ttl_seconds=ttl_seconds,
        force=force,
        limit=limit,
    )


@mcp.tool
def migrate_racb_records(dry_run: bool = True, limit: int = 500) -> dict[str, Any]:
    """RACB admin migration. Defaults to a read-only dry run."""
    from raphiia_openai import racb_migration

    return racb_migration.migrate_racb_records(dry_run=dry_run, limit=limit)


@mcp.tool
def product_intelligence(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grouped source→draft→approval→catalog pipeline for products and offers."""
    from raphiia_openai import product_intelligence as _pi

    return _pi.product_intelligence(action=action, payload=payload)


@mcp.tool
def list_ops_tasks(assignee: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Lista órdenes ops (pending/completed)."""
    from raphiia_openai import coordination_live

    return coordination_live.list_ops_tasks(assignee=assignee, status=status, limit=limit)


@mcp.tool
def bootstrap_context() -> dict[str, Any]:
    """Resumen compacto para abrir sesión — incluye RUNBOOK COT+WhatsApp."""
    return coordination_docs.bootstrap_context()


@mcp.tool
def get_operational_runbooks() -> dict[str, Any]:
    """Runbooks canónicos (COT, WhatsApp). ChatGPT: leer HUB/RUNBOOK_COTIZACION_WHATSAPP.md."""
    return coordination_docs.get_operational_runbooks()


@mcp.tool
def save_memory(
    type: str,
    title: str,
    body: str,
    visibility: str,
    tags: list[str] | None = None,
    owner_id: str = "RAFAEL",
    kind: str | None = None,
    privacy_scope: str | None = None,
    source_message_ids: list[str] | None = None,
    entities: list[str] | None = None,
    project: str | None = None,
    conversation_id: str | None = None,
    actor: str = "CHATGPT",
) -> dict[str, Any]:
    """Guarda una memoria versionada, privada y respaldada por mensajes de origen."""
    from raphiia_openai import daily_memory

    return daily_memory.save_memory(
        {
            "type": type,
            "kind": kind or (type if type in daily_memory.MEMORY_KINDS else "fact"),
            "title": title,
            "body": body,
            "visibility": visibility,
            "privacy_scope": privacy_scope or visibility,
            "tags": tags or [],
            "owner_id": owner_id,
            "source_message_ids": source_message_ids or [],
            "entities": entities or [],
            "project": project,
            "conversation_id": conversation_id,
            "actor": actor,
            "metadata": {"legacy_type": type} if type not in daily_memory.MEMORY_KINDS else {},
        }
    )


_MEMORY_READ_ANNOTATIONS = {"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False}
_MEMORY_WRITE_ANNOTATIONS = {"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False}
_MEMORY_DESTRUCTIVE_ANNOTATIONS = {"readOnlyHint": False, "openWorldHint": False, "destructiveHint": True}


@mcp.tool(annotations=_MEMORY_READ_ANNOTATIONS)
def search_memory(
    query: str,
    type: str | None = None,
    visibility: str | None = None,
    limit: int = 10,
    min_score: float = 0.0,
    trace: bool = False,
    actor: str = "CHATGPT",
    owner_id: str | None = None,
    allowed_privacy: list[str] | None = None,
    project: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Busca memoria relevante respetando privacidad, proyecto y entidad."""
    from raphiia_openai import daily_memory

    privacy = allowed_privacy or ([visibility] if visibility else None)
    return daily_memory.search_memory(
        {"query": query, "kind": type, "limit": limit, "min_score": min_score, "actor": actor, "owner_id": owner_id, "allowed_privacy": privacy, "project": project, "entity_id": entity_id, "trace": trace}
    )


@mcp.tool(annotations=_MEMORY_WRITE_ANNOTATIONS)
def save_conversation_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """Daily Life Memory: guarda un lote idempotente de mensajes con privacidad explícita."""
    from raphiia_openai import daily_memory

    return daily_memory.save_conversation_batch(payload)


@mcp.tool(annotations=_MEMORY_WRITE_ANNOTATIONS)
def finalize_conversation(payload: dict[str, Any]) -> dict[str, Any]:
    """Daily Life Memory: ejecuta resumen→entidades→emociones→decisiones→pendientes→memorias→estado→timeline."""
    from raphiia_openai import daily_memory

    return daily_memory.finalize_conversation(payload)


@mcp.tool(annotations=_MEMORY_WRITE_ANNOTATIONS)
def update_memory(payload: dict[str, Any]) -> dict[str, Any]:
    """Actualiza una memoria y conserva la versión anterior."""
    from raphiia_openai import daily_memory

    return daily_memory.update_memory(payload)


@mcp.tool(annotations=_MEMORY_READ_ANNOTATIONS)
def get_current_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Obtiene el estado actual separado del historial."""
    from raphiia_openai import daily_memory

    return daily_memory.get_current_state(payload)


@mcp.tool(annotations=_MEMORY_WRITE_ANNOTATIONS)
def update_current_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Actualiza el estado actual sin reescribir la memoria histórica."""
    from raphiia_openai import daily_memory

    return daily_memory.update_current_state(payload)


@mcp.tool(annotations=_MEMORY_READ_ANNOTATIONS)
def get_person_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Recupera entidad PERSON, memorias autorizadas y pendientes abiertos."""
    from raphiia_openai import daily_memory

    return daily_memory.get_person_context(payload)


@mcp.tool(annotations=_MEMORY_DESTRUCTIVE_ANNOTATIONS)
def correct_memory(payload: dict[str, Any]) -> dict[str, Any]:
    """Corrige una memoria, versiona el valor anterior y registra auditoría."""
    from raphiia_openai import daily_memory

    return daily_memory.correct_memory(payload)


@mcp.tool(annotations=_MEMORY_DESTRUCTIVE_ANNOTATIONS)
def forget_memory(payload: dict[str, Any]) -> dict[str, Any]:
    """Olvida una memoria por soft-delete irreversible de contenido y purga sus versiones."""
    from raphiia_openai import daily_memory

    return daily_memory.forget_memory(payload)


@mcp.tool(annotations=_MEMORY_WRITE_ANNOTATIONS)
def resolve_pending_item(payload: dict[str, Any]) -> dict[str, Any]:
    """Resuelve o cancela un pendiente y agrega el evento al timeline."""
    from raphiia_openai import daily_memory

    return daily_memory.resolve_pending_item(payload)


@mcp.tool(annotations=_MEMORY_READ_ANNOTATIONS)
def timeline(payload: dict[str, Any]) -> dict[str, Any]:
    """Consulta el timeline filtrado por privacidad, proyecto o entidad."""
    from raphiia_openai import daily_memory

    return daily_memory.timeline(payload)


@mcp.tool(annotations=_MEMORY_READ_ANNOTATIONS)
def get_memory_review_queue(actor: str = "RAFAEL", status: str = "active", limit: int = 50) -> dict[str, Any]:
    """Cola privada para el panel de revisión; solo el owner puede ver contenido."""
    from raphiia_openai import daily_memory

    return daily_memory.review_queue(actor=actor, status=status, limit=limit)


@mcp.tool
def migrate_daily_memory(dry_run: bool = True, limit: int = 1000) -> dict[str, Any]:
    """Migra memorias legacy al esquema Daily Life Memory; dry-run por defecto."""
    from raphiia_openai import daily_memory

    return daily_memory.migrate_schema(dry_run=dry_run, limit=limit)


@mcp.tool
def classify_knowledge_seed(title: str, body: str) -> dict[str, Any]:
    """Sugiere categoría, intención, visibilidad y proyecto antes de guardar."""
    return coordination_docs.classify_knowledge_seed(title, body)


@mcp.tool
def save_knowledge_seed(
    title: str,
    body: str,
    category: str,
    intent: str,
    visibility: str,
    project: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Guarda conocimiento estructurado y crea borrador solo si aplica."""
    return coordination_docs.save_knowledge_seed(
        title=title,
        body=body,
        category=category,
        intent=intent,
        visibility=visibility,
        project=project,
        tags=tags,
    )


@mcp.tool
def capture_backlog_item(
    title: str,
    body: str = "",
    status: str = "discussed",
    kind: str = "idea",
    source_agent: str = "SYSTEM",
    project: str | None = None,
    tags: list[str] | None = None,
    conversation_ref: str | None = None,
    ops_task_id: str | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    """Captura idea/decisión/tarea en ralfia_dev_backlog (dedupe automático)."""
    from raphiia_openai import dev_backlog

    return dev_backlog.capture_backlog_item(
        title=title,
        body=body,
        status=status,
        kind=kind,
        source_agent=source_agent,
        project=project,
        tags=tags,
        conversation_ref=conversation_ref,
        ops_task_id=ops_task_id,
        evidence=evidence,
    )


@mcp.tool
def finalize_session_handoff(
    agent: str,
    session_summary: str,
    items: list[dict[str, Any]] | None = None,
    conversation_ref: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Cierre de sesión: resumen + items backlog + logs compartidos."""
    from raphiia_openai import dev_backlog

    return dev_backlog.finalize_session_handoff(
        agent=agent,
        session_summary=session_summary,
        items=items,
        conversation_ref=conversation_ref,
        project=project,
    )


@mcp.tool
def list_dev_backlog(
    status: str | None = None,
    source_agent: str | None = None,
    project: str | None = None,
    kind: str | None = None,
    stale_days: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Lista backlog de ideas/tareas con filtros."""
    from raphiia_openai import dev_backlog

    return dev_backlog.list_dev_backlog(
        status=status,
        source_agent=source_agent,
        project=project,
        kind=kind,
        stale_days=stale_days,
        limit=limit,
    )


@mcp.tool
def update_dev_backlog_item(
    item_id: str,
    status: str | None = None,
    note: str | None = None,
    evidence: str | None = None,
    ops_task_id: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Actualiza item del backlog por item_id."""
    from raphiia_openai import dev_backlog

    return dev_backlog.update_dev_backlog_item(
        item_id,
        status=status,
        note=note,
        evidence=evidence,
        ops_task_id=ops_task_id,
        tags=tags,
    )


@mcp.tool
def get_dev_backlog_summary(stale_days: int = 14) -> dict[str, Any]:
    """Resumen del backlog: hecho vs pendiente vs olvidado."""
    from raphiia_openai import dev_backlog

    return dev_backlog.get_dev_backlog_summary(stale_days=stale_days)


@mcp.tool
def list_recent_agent_activity(hours: int = 24, limit: int = 50) -> dict[str, Any]:
    """Lista ejecuciones reales de agentes (agent_activity_log)."""
    from raphiia_openai import agent_activity_report

    return agent_activity_report.list_recent_agent_activity(hours=hours, limit=limit)


@mcp.tool
def generate_agent_activity_report(hours: int = 24) -> dict[str, Any]:
    """AG-58: reporte automático — qué agentes ejecutaron, ingesta, ops abiertas."""
    from raphiia_openai import agent_activity_report

    return agent_activity_report.generate_agent_activity_report(hours=hours)


@mcp.tool
def send_daily_backlog_whatsapp(target_number: str | None = None) -> dict[str, Any]:
    """AG-57: envía recordatorio WhatsApp con proyectos/ideas pendientes."""
    from raphiia_openai.agents import ag57_backlog_steward as ag57

    return ag57.send_daily_backlog_whatsapp(target_number=target_number)


@mcp.tool
def run_backlog_steward(message: str = "", sender: str | None = None) -> dict[str, Any]:
    """AG-57: consulta backlog o asigna item (simula WhatsApp)."""
    from raphiia_openai.agents import ag57_backlog_steward as ag57

    return ag57.run_backlog_steward(message, sender=sender or "593988959606")


@mcp.tool
def list_local_models() -> dict[str, Any]:
    """Inventario de modelos locales instalados en Ollama."""
    return local_model_router.list_local_models()


@mcp.tool
def local_model_health() -> dict[str, Any]:
    """Salud de Ollama, Open WebUI, AnythingLLM, n8n, GPU y memoria."""
    return local_model_router.local_model_health()


@mcp.tool
def local_model_catalog_search(query: str, source: str = "huggingface", filters: dict[str, Any] | None = None, limit: int = 10) -> dict[str, Any]:
    """Busca modelos públicos en catálogo remoto sin descargar ni usar tokens."""
    return local_model_manager.local_model_catalog_search(query=query, source=source, filters=filters, limit=limit)


@mcp.tool
def local_model_preflight(model_ref: str, node: str = "amd", backend: str = "vllm", quantization: str = "", revision: str = "") -> dict[str, Any]:
    """Preflight seguro de modelo local: HF metadata, disco, ROCm/vLLM y riesgos antes de descargar."""
    return local_model_manager.local_model_preflight(model_ref=model_ref, node=node, backend=backend, quantization=quantization, revision=revision)


@mcp.tool
def local_model_download(model_ref: str, node: str = "amd", revision: str = "", quantization: str = "", target_store: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Crea job persistente de descarga de modelo; dry_run por defecto y preflight obligatorio."""
    return local_model_manager.local_model_download(model_ref=model_ref, node=node, revision=revision, quantization=quantization, target_store=target_store, dry_run=dry_run)


@mcp.tool
def local_model_download_status(job_id: str) -> dict[str, Any]:
    """Consulta estado de job persistente de descarga de modelo."""
    return local_model_manager.local_model_download_status(job_id=job_id)


@mcp.tool
def local_model_worker_start(job_id: str = "", node: str = "amd") -> dict[str, Any]:
    """Lanza worker persistente para un job queued de descarga de modelo local."""
    return local_model_manager.local_model_worker_start(job_id=job_id, node=node)


@mcp.tool
def local_model_list(node: str = "", backend: str = "") -> dict[str, Any]:
    """Lista modelos/artefactos registrados o presentes en el store local canónico."""
    return local_model_manager.local_model_list(node=node, backend=backend)


@mcp.tool
def local_model_serve(model_ref: str, node: str = "amd", backend: str = "vllm", alias: str = "", context_length: int = 8192, gpu_memory_utilization: float = 0.85, dry_run: bool = True) -> dict[str, Any]:
    """Planifica/encola serving local privado vLLM OpenAI-compatible; dry_run por defecto."""
    return local_model_manager.local_model_serve(model_ref=model_ref, node=node, backend=backend, alias=alias, context_length=context_length, gpu_memory_utilization=gpu_memory_utilization, dry_run=dry_run)


@mcp.tool
def local_model_runtime_status(node: str = "amd", backend: str = "vllm") -> dict[str, Any]:
    """Estado del runtime local de modelos: vLLM/Ollama, puertos privados, GPU y versiones."""
    return local_model_manager.local_model_runtime_status(node=node, backend=backend)


@mcp.tool
def local_model_stop(alias: str = "", model_ref: str = "", node: str = "amd") -> dict[str, Any]:
    """Detiene únicamente servicios allowlisted inneros-vllm-* por alias/model_ref."""
    return local_model_manager.local_model_stop(alias=alias, model_ref=model_ref, node=node)


@mcp.tool
def local_model_delete(model_ref: str, node: str = "amd", dry_run: bool = True) -> dict[str, Any]:
    """Elimina modelo del store local con dry_run por defecto y guards de serving/default."""
    return local_model_manager.local_model_delete(model_ref=model_ref, node=node, dry_run=dry_run)


@mcp.tool
def local_model_benchmark(model_ref: str = "", alias: str = "", prompt_suite: str = "format_contract", task_class: str = "coding", repo_context_ref: str = "") -> dict[str, Any]:
    """Benchmark fixture de modelo local; no modifica productos y reporta runtime/métricas disponibles."""
    return local_model_manager.local_model_benchmark(model_ref=model_ref, alias=alias, prompt_suite=prompt_suite, task_class=task_class, repo_context_ref=repo_context_ref)


@mcp.tool
def local_model_set_default(task_class: str, model_ref: str, provider_id: str = "local-amd-5") -> dict[str, Any]:
    """Fija default de router por task_class para Resource Fabric/Dev Swarm."""
    return local_model_manager.local_model_set_default(task_class=task_class, model_ref=model_ref, provider_id=provider_id)


@mcp.tool
def local_model_router_status(project_id: str = "", task_class: str = "") -> dict[str, Any]:
    """Consulta defaults de router local por proyecto/task_class."""
    return local_model_manager.local_model_router_status(project_id=project_id, task_class=task_class)


@mcp.tool
def classify_task_runtime(text: str, task_type: str | None = None) -> dict[str, Any]:
    """Clasifica una tarea y sugiere runtime local/external."""
    return local_model_router.classify_task_runtime(text, task_type=task_type)


@mcp.tool
def route_ai_task(title: str, body: str, task_type: str | None = None) -> dict[str, Any]:
    """Decide el runtime recomendado para una tarea de IA."""
    return local_model_router.route_ai_task(title, body, task_type=task_type)


@mcp.tool
def run_local_model(task_type: str, prompt: str, model: str | None = None, max_tokens: int | None = None) -> dict[str, Any]:
    """Ejecuta una tarea con un modelo local de Ollama."""
    return local_model_router.run_local_model(task_type=task_type, prompt=prompt, model=model, max_tokens=max_tokens)


@mcp.tool
def get_ai_usage_report(limit: int = 200) -> dict[str, Any]:
    """Resumen de uso local vs externo y ahorro estimado."""
    return local_model_router.get_ai_usage_report(limit=limit)


@mcp.tool
def generate_daily_brief(limit: int = 20, model: str | None = None) -> dict[str, Any]:
    """Brief diario local-first con fallback seguro."""
    return local_model_router.generate_daily_brief(limit=limit, model=model)


@mcp.tool
def cognitive_kernel_check(objective: str, context: str | None = None) -> dict[str, Any]:
    """Evalua objetivo, riesgo y ruta recomendada para el kernel cognitivo."""
    return local_model_router.cognitive_kernel_check(objective, context=context)


@mcp.tool
def local_exec_inspect_repo(repo: str) -> dict[str, Any]:
    """Local Execution Plane: inspecciona repo allowlisted sin mutar runtime."""
    return local_execution_plane.inspect_repo(repo=repo)


@mcp.tool
def local_exec_repo_policy_status(repo: str | None = None) -> dict[str, Any]:
    """Local Execution Plane: muestra policy/registry de repos autorizados."""
    return local_execution_plane.repo_policy_status(repo=repo)


@mcp.tool
def local_exec_repo_authorize(
    repo: str,
    repo_class: str = "product-app",
    write_scope: str = "worktree",
    allowed_paths: list[str] | None = None,
    allowed_commands_profile: str = "",
    package_roots: list[str] | None = None,
    approval_id: str = "",
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Local Execution Plane: registra policy auditable para repo del owner aprobado."""
    return local_execution_plane.repo_authorize(
        repo=repo,
        repo_class=repo_class,
        write_scope=write_scope,
        allowed_paths=allowed_paths,
        allowed_commands_profile=allowed_commands_profile,
        package_roots=package_roots,
        approval_id=approval_id,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        dry_run=dry_run,
    )


@mcp.tool
def local_exec_repo_revoke(
    repo: str,
    approval_id: str,
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Local Execution Plane: revoca policy de escritura; el owner aprobado queda read-only."""
    return local_execution_plane.repo_revoke(
        repo=repo,
        approval_id=approval_id,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        dry_run=dry_run,
    )


@mcp.tool
def dev_swarm_scope_status(repo: str | None = None) -> dict[str, Any]:
    """Dev Swarm: muestra launcher seguro para desarrollo local sin ralfia:admin."""
    return local_execution_plane.dev_swarm_scope_status(repo=repo)


@mcp.tool
def dev_swarm_launch_task(
    repo: str,
    objective: str,
    base_branch: str = "main",
    work_branch: str = "",
    actor: str = "chatgpt",
    task_id: str = "",
    correlation_id: str = "",
    idempotency_key: str = "",
    remote_url: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Dev Swarm: prepara repo, lock y worktree aislado para una tarea owner-approved."""
    return local_execution_plane.dev_swarm_launch_task(
        repo=repo,
        objective=objective,
        base_branch=base_branch,
        work_branch=work_branch,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        remote_url=remote_url,
        dry_run=dry_run,
    )


@mcp.tool
def dev_swarm_scheduler_status() -> dict[str, Any]:
    """Estado del scheduler 1→N que toma ops_tasks y lanza workers locales seguros."""
    return dev_swarm_scheduler.scheduler_status()


@mcp.tool
def dev_swarm_scheduler_start(max_concurrent: int = 4, dry_run: bool = False) -> dict[str, Any]:
    """Activa el scheduler 1→N sin requerir ralfia:admin global."""
    return dev_swarm_scheduler.scheduler_start(max_concurrent=max_concurrent, dry_run=dry_run)


@mcp.tool
def dev_swarm_scheduler_stop(reason: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Pausa el scheduler 1→N de forma reversible."""
    return dev_swarm_scheduler.scheduler_stop(reason=reason, dry_run=dry_run)


@mcp.tool
def dev_swarm_scheduler_tick(limit: int = 6, dry_run: bool = False, include_fixtures: bool = False) -> dict[str, Any]:
    """Ejecuta un ciclo manual del scheduler para proposed ops_tasks elegibles."""
    return dev_swarm_scheduler.scheduler_tick(limit=limit, dry_run=dry_run, include_fixtures=include_fixtures)


@mcp.tool
def dev_swarm_watchdog_record_anomaly(anomaly: dict[str, Any], repair_task_id: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Registra una anomalía Dev Swarm y crea/actualiza una ops_task deduplicada."""
    return dev_swarm_watchdog.record_anomaly(anomaly, repair_task_id=repair_task_id, actor="mcp", dry_run=dry_run)


@mcp.tool
def dev_swarm_watchdog_close_anomaly(fingerprint: str, repair_task_id: str = "", evidence: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Cierra una anomalía watchdog con evidencia de reparación/verificación."""
    return dev_swarm_watchdog.close_anomaly(fingerprint, repair_task_id=repair_task_id, evidence=evidence, actor="mcp", dry_run=dry_run)


@mcp.tool
def dev_swarm_watchdog_summary(limit: int = 20) -> dict[str, Any]:
    """Resumen consultable para agentes: anomalías, regresiones y P0 activos."""
    return dev_swarm_watchdog.summary(limit=limit)


@mcp.tool
def dev_swarm_watchdog_demo_closed_loop(dry_run: bool = True) -> dict[str, Any]:
    """Prueba detectar→task→cerrar→reinyectar→regression sin duplicar."""
    return dev_swarm_watchdog.demo_closed_loop(dry_run=dry_run)


@mcp.tool
def dev_swarm_watchdog_dedupe_ops(correlation_id: str, canonical_task_id: str = "", duplicate_task_ids: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Reconcilia ops_tasks duplicadas por correlation_id sin borrar evidencia."""
    return dev_swarm_watchdog.canonicalize_duplicate_ops(correlation_id=correlation_id, canonical_task_id=canonical_task_id, duplicate_task_ids=duplicate_task_ids, actor="mcp", dry_run=dry_run)


@mcp.tool
def dev_swarm_create_fixture_tasks(count: int = 2) -> dict[str, Any]:
    """Crea fixtures P0 seguras para probar ejecución concurrente del scheduler."""
    return dev_swarm_scheduler.create_fixture_tasks(count=count)


@mcp.tool
def dev_swarm_executor_status() -> dict[str, Any]:
    """Estado del executor que trabaja dentro de worktrees aislados."""
    return dev_swarm_scheduler.executor_status()


@mcp.tool
def dev_swarm_executor_tick(limit: int = 2, dry_run: bool = False, run_tests: bool = True) -> dict[str, Any]:
    """Ejecuta un ciclo del worker executor: checks, plan local, evidencia y commit de reporte."""
    return dev_swarm_scheduler.executor_tick(limit=limit, dry_run=dry_run, run_tests=run_tests)


@mcp.tool
def dev_swarm_fanout_execute(repo: str, task_ids: list[str], concurrency: int = 6, dry_run: bool = False) -> dict[str, Any]:
    """Ejecuta N lanes de desarrollo local en worktrees aislados con executor autónomo."""
    return dev_swarm_scheduler.fanout_execute(repo=repo, task_ids=task_ids, concurrency=concurrency, dry_run=dry_run)


@mcp.tool
def dev_swarm_capacity_status() -> dict[str, Any]:
    """Snapshot del capacity governor sin consumo LLM: CPU/RAM/GPU/disk/workers y concurrencia recomendada."""
    return dev_swarm_scheduler.capacity_status()


@mcp.tool
def dev_swarm_capacity_tick(simulated_load: dict[str, Any] | None = None) -> dict[str, Any]:
    """Toma y publica un snapshot de capacidad; simulated_load es solo para pruebas de throttling."""
    return dev_swarm_scheduler.capacity_status(simulated_load=simulated_load)


@mcp.tool
def external_repair_agent_status(provider: str = "") -> dict[str, Any]:
    """External Repair Agent: matriz Codex/Cursor/Antigravity + credit governor."""
    return external_repair_agent.external_repair_agent_status(provider=provider)


@mcp.tool
def external_repair_agent_claim_next(provider: str = "codex", dry_run: bool = True, limit: int = 10, task_id: str = "") -> dict[str, Any]:
    """External Repair Agent: claim atomico proposed→accepted si provider/cupo estan listos."""
    return external_repair_agent.external_repair_agent_claim_next(provider=provider, dry_run=dry_run, limit=limit, task_id=task_id)


@mcp.tool
def external_repair_agent_reconcile(provider: str = "codex", auto_claim: bool = True, limit: int = 10, dry_run: bool = False) -> dict[str, Any]:
    """External Repair Agent: reconcilia handoffs terminales y reclama la siguiente tarea elegible si esta autorizado."""
    return external_repair_agent.external_repair_agent_reconcile(provider=provider, auto_claim=auto_claim, limit=limit, dry_run=dry_run)


@mcp.tool
def external_repair_agent_run_task(
    provider: str,
    task_id: str,
    dry_run: bool = True,
    allow_external_spend: bool = False,
    approval_id: str = "",
) -> dict[str, Any]:
    """External Repair Agent: admision de ejecucion externa con gate de creditos/aprobacion."""
    return external_repair_agent.external_repair_agent_run_task(
        provider=provider,
        task_id=task_id,
        dry_run=dry_run,
        allow_external_spend=allow_external_spend,
        approval_id=approval_id,
    )


@mcp.tool
def external_repair_run_start(
    provider: str,
    task_id: str,
    correlation_id: str = "",
    repo: str = "",
    branch: str = "",
    worktree: str = "",
    dry_run: bool = True,
    chargeable: bool = False,
    context_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """External Repair Agent: inicia registro durable de run sin gastar creditos por defecto."""
    return external_repair_agent.start_external_repair_run(
        provider=provider,
        task_id=task_id,
        correlation_id=correlation_id,
        repo=repo,
        branch=branch,
        worktree=worktree,
        dry_run=dry_run,
        chargeable=chargeable,
        context_bundle=context_bundle,
    )


@mcp.tool
def external_repair_run_checkpoint(
    run_id: str,
    phase: str,
    evidence: dict[str, Any] | None = None,
    files_touched: list[str] | None = None,
) -> dict[str, Any]:
    """External Repair Agent: guarda checkpoint/heartbeat recuperable en Mongo."""
    return external_repair_agent.checkpoint_external_repair_run(
        run_id,
        phase=phase,
        evidence=evidence,
        files_touched=files_touched,
    )


@mcp.tool
def external_repair_run_complete(
    run_id: str,
    outcome: str = "completed",
    result: str = "PASS",
    evidence: dict[str, Any] | None = None,
    report_to: str = "chatgpt",
    update_task: bool = True,
) -> dict[str, Any]:
    """External Repair Agent: cierra run, actualiza ops_task y reporta handoff automaticamente."""
    return external_repair_agent.complete_external_repair_run(
        run_id,
        outcome=outcome,
        result=result,
        evidence=evidence,
        report_to=report_to,
        update_task=update_task,
    )


@mcp.tool
def external_repair_run_recover(provider: str = "", mark_stale_after_seconds: int = 3600) -> dict[str, Any]:
    """External Repair Agent: recupera runs activos tras restart y marca stale si aplica."""
    return external_repair_agent.recover_external_repair_runs(provider=provider, mark_stale_after_seconds=mark_stale_after_seconds)


@mcp.tool
def local_fs_policy() -> dict[str, Any]:
    """Local Filesystem Plane: muestra raíces confiables, límites y bloqueos."""
    return local_filesystem_plane.policy()


@mcp.tool
def local_fs_list(path: str, limit: int = 100) -> dict[str, Any]:
    """Local Filesystem Plane: lista archivo/directorio bajo raíces confiables."""
    return local_filesystem_plane.list_path(path=path, limit=limit)


@mcp.tool
def local_fs_read_file(path: str, max_bytes: int = 200000) -> dict[str, Any]:
    """Local Filesystem Plane: lee archivo acotado bajo raíces confiables."""
    return local_filesystem_plane.read_file(path=path, max_bytes=max_bytes)


@mcp.tool
def local_fs_mkdir(path: str, actor: str, task_id: str, correlation_id: str) -> dict[str, Any]:
    """Local Filesystem Plane: crea carpetas bajo raíces confiables."""
    return local_filesystem_plane.mkdir(path=path, actor=actor, task_id=task_id, correlation_id=correlation_id)


@mcp.tool
def local_fs_write_file(
    path: str,
    content: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    mode: str = "replace",
) -> dict[str, Any]:
    """Local Filesystem Plane: crea, reemplaza o agrega contenido a archivos permitidos."""
    return local_filesystem_plane.write_file(
        path=path,
        content=content,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        mode=mode,
    )


@mcp.tool
def local_fs_move_to_quarantine(path: str, actor: str, task_id: str, correlation_id: str, reason: str = "") -> dict[str, Any]:
    """Local Filesystem Plane: mueve a cuarentena reversible; no borra permanente."""
    return local_filesystem_plane.move_to_quarantine(
        path=path,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        reason=reason,
    )


@mcp.tool
def local_git_init_repo(path: str, actor: str, task_id: str, correlation_id: str, default_branch: str = "main") -> dict[str, Any]:
    """Local Filesystem Plane: inicializa un repositorio Git en una ruta confiable."""
    return local_filesystem_plane.git_init_repo(
        path=path,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        default_branch=default_branch,
    )


@mcp.tool
def local_github_status() -> dict[str, Any]:
    """Local GitHub Plane: valida gh/GitHub token y owners autorizados sin mutar."""
    return local_github_plane.github_status()


@mcp.tool
def local_github_create_repo(
    owner: str,
    name: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    description: str = "",
    private: bool = True,
    homepage: str | None = None,
) -> dict[str, Any]:
    """Local GitHub Plane: crea un repo GitHub allowlisted, privado por defecto e idempotente."""
    return local_github_plane.create_github_repo(
        owner=owner,
        name=name,
        description=description,
        private=private,
        homepage=homepage,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
    )


@mcp.tool
def local_project_bootstrap(
    path: str,
    project_name: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    description: str = "",
    github_owner: str = "Rafa-Innerchispa",
    create_remote: bool = False,
    private: bool = True,
) -> dict[str, Any]:
    """Local GitHub Plane: crea carpeta/proyecto, inicializa Git y opcionalmente crea remoto GitHub."""
    return local_github_plane.bootstrap_project(
        path=path,
        project_name=project_name,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        description=description,
        github_owner=github_owner,
        create_remote=create_remote,
        private=private,
    )


@mcp.tool
def local_gitlab_status() -> dict[str, Any]:
    """Local GitLab Plane: valida API/glab/usuario real sin exponer token."""
    return local_gitlab_plane.gitlab_status()


@mcp.tool
def local_gitlab_store_pat_server_side(secret: str, label: str = "GitLab Personal Access Token", actor: str = "RAFAEL") -> dict[str, Any]:
    """Local GitLab Plane: guarda PAT en owner_vault; no retorna el secreto."""
    return local_gitlab_plane.store_pat_server_side(secret=secret, label=label, actor=actor)


@mcp.tool
def local_gitlab_glab_preflight() -> dict[str, Any]:
    """Local GitLab Plane: revisa disponibilidad de glab CLI sin mutar."""
    return local_gitlab_plane.glab_preflight()


@mcp.tool
def local_gitlab_list_projects(search: str = "", owned: bool = False, membership: bool = True, limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: lista proyectos accesibles via API GitLab."""
    return local_gitlab_plane.list_projects(search=search, owned=owned, membership=membership, limit=limit)


@mcp.tool
def local_gitlab_list_groups(search: str = "", limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: lista grupos accesibles via API GitLab."""
    return local_gitlab_plane.list_groups(search=search, limit=limit)


@mcp.tool
def local_gitlab_user_profile(username: str = "") -> dict[str, Any]:
    """Local GitLab Plane: perfil de usuario GitLab para ContributorOps."""
    return local_gitlab_plane.user_profile(username=username)


@mcp.tool
def local_gitlab_user_events(username: str = "rafagye", action: str = "", limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: eventos recientes de usuario para metricas de contribucion."""
    return local_gitlab_plane.user_events(username=username, action=action, limit=limit)


@mcp.tool
def local_gitlab_discover_contribution_issues(search: str = "good first issue", labels: str = "", limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: descubre issues candidateables para contribucion."""
    return local_gitlab_plane.discover_contribution_issues(search=search, labels=labels, limit=limit)


@mcp.tool
def local_gitlab_project_summary(project_id_or_path: str) -> dict[str, Any]:
    """Local GitLab Plane: resumen seguro de repo/proyecto GitLab."""
    return local_gitlab_plane.project_summary(project_id_or_path=project_id_or_path)


@mcp.tool
def local_gitlab_list_merge_requests(project_id_or_path: str, state: str = "opened", limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: lista merge requests para trazabilidad y code review."""
    return local_gitlab_plane.list_merge_requests(project_id_or_path=project_id_or_path, state=state, limit=limit)


@mcp.tool
def local_gitlab_create_draft_merge_request(source_project: str, source_branch: str, target_project: str, target_branch: str = "main", title: str = "", description: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local GitLab Plane: crea un Draft MR allowlisted; por defecto solo simula."""
    return local_gitlab_plane.create_draft_merge_request(
        source_project=source_project,
        source_branch=source_branch,
        target_project=target_project,
        target_branch=target_branch,
        title=title,
        description=description,
        dry_run=dry_run,
    )


@mcp.tool
def local_gitlab_list_issues(project_id_or_path: str, state: str = "opened", limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: lista issues para trazabilidad de proyecto."""
    return local_gitlab_plane.list_issues(project_id_or_path=project_id_or_path, state=state, limit=limit)


@mcp.tool
def local_gitlab_list_pipelines(project_id_or_path: str, ref: str = "", limit: int = 20) -> dict[str, Any]:
    """Local GitLab Plane: lista pipelines CI/CD sin disparar ejecuciones."""
    return local_gitlab_plane.list_pipelines(project_id_or_path=project_id_or_path, ref=ref, limit=limit)


@mcp.tool
def local_gitlab_resource_sync(dry_run: bool = False) -> dict[str, Any]:
    """Local GitLab Plane: registra GitLab en Resource Fabric sin volverlo motor default."""
    return local_gitlab_plane.register_resource_provider(dry_run=dry_run)


@mcp.tool
def local_gitlab_prepare_github_mirrors(namespace: str = "rafagye", create_missing: bool = False, configure_remotes: bool = False, push: bool = False, dry_run: bool = True) -> dict[str, Any]:
    """Local GitLab Plane: inventaria/prepara mirrors GitHub->GitLab manteniendo GitHub como origin."""
    return local_gitlab_plane.prepare_github_mirrors(namespace=namespace, create_missing=create_missing, configure_remotes=configure_remotes, push=push, dry_run=dry_run)


@mcp.tool
def local_gitlab_credit_status(register_if_missing: bool = True, dry_run: bool = False) -> dict[str, Any]:
    """Local GitLab Plane: reconcilia creditos Contributor Rewards como no gastables hasta verificar."""
    return local_gitlab_plane.gitlab_credit_status(register_if_missing=register_if_missing, dry_run=dry_run)


@mcp.tool
def local_discord_configure_public_app(application_id: str, public_key: str, default_channel_id: str = "", default_guild_id: str = "", actor: str = "RAFAEL") -> dict[str, Any]:
    """Local Discord Plane: registra Application ID/Public Key y IDs por defecto sin secretos."""
    return local_discord_plane.configure_public_app(application_id=application_id, public_key=public_key, default_channel_id=default_channel_id, default_guild_id=default_guild_id, actor=actor)


@mcp.tool
def local_discord_status() -> dict[str, Any]:
    """Local Discord Plane: valida configuracion, bot token/webhook y usuario bot sin exponer secretos."""
    return local_discord_plane.discord_status()


@mcp.tool
def local_discord_interaction_gateway_status() -> dict[str, Any]:
    """Local Discord Plane: muestra estado del endpoint seguro para slash commands."""
    return discord_interaction_gateway.endpoint_status()


@mcp.tool
def local_discord_set_interactions_endpoint_url(endpoint_url: str, dry_run: bool = True, actor: str = "RAFAEL") -> dict[str, Any]:
    """Local Discord Plane: fija o simula la URL publica de Discord Interactions."""
    return local_discord_plane.set_interactions_endpoint_url(endpoint_url=endpoint_url, dry_run=dry_run, actor=actor)


@mcp.tool
def local_discord_store_bot_token_server_side(secret: str, label: str = "Discord Bot Token", actor: str = "RAFAEL") -> dict[str, Any]:
    """Local Discord Plane: guarda bot token en owner_vault; no retorna el secreto."""
    return local_discord_plane.store_bot_token_server_side(secret=secret, label=label, actor=actor)


@mcp.tool
def local_discord_store_webhook_url_server_side(secret: str, label: str = "Discord Ops Webhook URL", actor: str = "RAFAEL") -> dict[str, Any]:
    """Local Discord Plane: guarda webhook URL en owner_vault; no retorna el secreto."""
    return local_discord_plane.store_webhook_url_server_side(secret=secret, label=label, actor=actor)


@mcp.tool
def local_discord_list_guilds(limit: int = 20) -> dict[str, Any]:
    """Local Discord Plane: lista servidores donde el bot esta instalado."""
    return local_discord_plane.list_guilds(limit=limit)


@mcp.tool
def local_discord_oauth_install_url(permissions: int = 84992) -> dict[str, Any]:
    """Local Discord Plane: genera URL OAuth para instalar el bot con permisos minimos."""
    return local_discord_plane.oauth_install_url(permissions=permissions)


@mcp.tool
def local_discord_list_channels(guild_id: str = "", limit: int = 100) -> dict[str, Any]:
    """Local Discord Plane: lista canales de un servidor para elegir destino por nombre/ID."""
    return local_discord_plane.list_channels(guild_id=guild_id, limit=limit)


@mcp.tool
def local_discord_create_text_channel(name: str, topic: str = "", guild_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: crea canal de texto; dry_run por defecto."""
    return local_discord_plane.create_text_channel(name=name, topic=topic, guild_id=guild_id, dry_run=dry_run)


@mcp.tool
def local_discord_list_channel_webhooks(channel_id: str = "") -> dict[str, Any]:
    """Local Discord Plane: lista webhooks de canal sin retornar secretos."""
    return local_discord_plane.list_channel_webhooks(channel_id=channel_id)


@mcp.tool
def local_discord_create_channel_webhook(channel: str, name: str = "RalphiIA", dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: crea webhook de canal y guarda URL server-side."""
    return local_discord_plane.create_channel_webhook(channel=channel, name=name, dry_run=dry_run)


@mcp.tool
def local_discord_create_thread(channel: str, name: str, message: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: crea thread de publicacion/campana en un canal."""
    return local_discord_plane.create_thread(channel=channel, name=name, message=message, dry_run=dry_run)


@mcp.tool
def local_discord_list_channel_messages(channel_id: str = "", limit: int = 20) -> dict[str, Any]:
    """Local Discord Plane: lee mensajes recientes de un canal accesible."""
    return local_discord_plane.list_channel_messages(channel_id=channel_id, limit=limit)


@mcp.tool
def local_discord_resolve_channel(name_or_id: str = "") -> dict[str, Any]:
    """Local Discord Plane: resuelve nombre/alias de canal a channel_id."""
    return local_discord_plane.resolve_channel(name_or_id=name_or_id)


@mcp.tool
def local_discord_search_channel_messages(channel_id: str = "", query: str = "", limit: int = 50) -> dict[str, Any]:
    """Local Discord Plane: busca texto en mensajes recientes de un canal."""
    return local_discord_plane.search_channel_messages(channel_id=channel_id, query=query, limit=limit)


@mcp.tool
def local_discord_read_configured_channels(limit_per_channel: int = 10) -> dict[str, Any]:
    """Local Discord Plane: lee mensajes recientes de canales configurados."""
    return local_discord_plane.read_configured_channels(limit_per_channel=limit_per_channel)


@mcp.tool
def local_discord_search_configured_channels(query: str, limit_per_channel: int = 50) -> dict[str, Any]:
    """Local Discord Plane: busca texto en canales configurados."""
    return local_discord_plane.search_configured_channels(query=query, limit_per_channel=limit_per_channel)


@mcp.tool
def local_discord_send_channel_message(channel_id: str = "", content: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: envia mensaje a canal; dry_run por defecto para evitar ruido accidental."""
    return local_discord_plane.send_channel_message(channel_id=channel_id, content=content, dry_run=dry_run)


@mcp.tool
def local_discord_send_named_channel_message(channel: str, content: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: envia mensaje a canal por nombre/alias; dry_run por defecto."""
    return local_discord_plane.send_named_channel_message(channel=channel, content=content, dry_run=dry_run)


@mcp.tool
def local_discord_send_webhook_message(content: str, dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: envia alerta por webhook; dry_run por defecto para evitar ruido accidental."""
    return local_discord_plane.send_webhook_message(content=content, dry_run=dry_run)


@mcp.tool
def local_discord_list_guild_commands(guild_id: str = "") -> dict[str, Any]:
    """Local Discord Plane: lista slash commands registrados en un servidor."""
    return local_discord_plane.list_guild_commands(guild_id=guild_id)


@mcp.tool
def local_discord_register_guild_commands(guild_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: registra slash commands basicos de InnerOS."""
    return local_discord_plane.register_guild_commands(guild_id=guild_id, dry_run=dry_run)


@mcp.tool
def local_discord_add_reaction(channel_id: str, message_id: str, emoji: str, dry_run: bool = True) -> dict[str, Any]:
    """Local Discord Plane: agrega reaccion auditada a un mensaje."""
    return local_discord_plane.add_reaction(channel_id=channel_id, message_id=message_id, emoji=emoji, dry_run=dry_run)


@mcp.tool
def local_discord_resource_sync(dry_run: bool = False) -> dict[str, Any]:
    """Local Discord Plane: registra Discord en Resource Fabric como canal ops/aprobaciones."""
    return local_discord_plane.register_resource_provider(dry_run=dry_run)


@mcp.tool
def local_exec_prepare_repo(
    repo: str,
    base_ref: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
    remote_url: str | None = None,
) -> dict[str, Any]:
    """Local Execution Plane: clona/fetchea repo allowlisted como fuente Git local."""
    return local_execution_plane.prepare_repo(
        repo=repo,
        base_ref=base_ref,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        remote_url=remote_url,
    )


@mcp.tool
def local_exec_hydrate_repo(
    repo: str,
    base_ref: str,
    actor: str,
    task_id: str,
    correlation_id: str,
    idempotency_key: str,
    remote_url: str | None = None,
) -> dict[str, Any]:
    """Alias compatible de local_exec_prepare_repo."""
    return local_execution_plane.prepare_repo(
        repo=repo,
        base_ref=base_ref,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        remote_url=remote_url,
    )


@mcp.tool
def local_exec_acquire_lock(repo: str, actor: str, task_id: str, correlation_id: str, ttl_seconds: int = 1800) -> dict[str, Any]:
    """Local Execution Plane: adquiere lock RACB para un repo antes de mutar."""
    return local_execution_plane.acquire_lock(repo=repo, actor=actor, task_id=task_id, correlation_id=correlation_id, ttl_seconds=ttl_seconds)


@mcp.tool
def local_exec_release_lock(repo: str, actor: str, task_id: str, correlation_id: str) -> dict[str, Any]:
    """Local Execution Plane: libera lock RACB de un repo."""
    return local_execution_plane.release_lock(repo=repo, actor=actor, task_id=task_id, correlation_id=correlation_id)


@mcp.tool
def local_exec_create_worktree(repo: str, base_branch: str, work_branch: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str) -> dict[str, Any]:
    """Local Execution Plane: crea worktree/rama aislada desde una base aprobada."""
    return local_execution_plane.create_worktree(repo=repo, base_branch=base_branch, work_branch=work_branch, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key)


@mcp.tool
def local_exec_apply_patch(repo: str, work_branch: str, patch: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str) -> dict[str, Any]:
    """Local Execution Plane: aplica diff unificado validado dentro del worktree."""
    return local_execution_plane.apply_patch(repo=repo, work_branch=work_branch, patch=patch, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key)


@mcp.tool
def local_exec_write_file(repo: str, work_branch: str, path: str, content: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str) -> dict[str, Any]:
    """Local Execution Plane: escribe un archivo acotado bajo rutas permitidas."""
    return local_execution_plane.write_file(repo=repo, work_branch=work_branch, path=path, content=content, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key)


@mcp.tool
def local_exec_run_command_allowlisted(repo: str, work_branch: str, command: list[str], actor: str, task_id: str, correlation_id: str, timeout_seconds: int = 120, max_output_bytes: int = 60000) -> dict[str, Any]:
    """Local Execution Plane: ejecuta solo comandos argv allowlisted en worktree."""
    return local_execution_plane.run_command_allowlisted(repo=repo, work_branch=work_branch, command=command, actor=actor, task_id=task_id, correlation_id=correlation_id, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)


@mcp.tool
def local_exec_commit_branch(repo: str, work_branch: str, message: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str) -> dict[str, Any]:
    """Local Execution Plane: commitea cambios del worktree en la rama de trabajo."""
    return local_execution_plane.commit_branch(repo=repo, work_branch=work_branch, message=message, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key)


@mcp.tool
def local_exec_inspect_remotes(repo: str, work_branch: str, actor: str, task_id: str, correlation_id: str) -> dict[str, Any]:
    """Local Execution Plane: inspecciona remotos git configurados sin mutar el worktree."""
    return local_execution_plane.inspect_remotes(repo=repo, work_branch=work_branch, actor=actor, task_id=task_id, correlation_id=correlation_id)


@mcp.tool
def local_exec_configure_remote(repo: str, work_branch: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str, remote: str, dry_run: bool = True) -> dict[str, Any]:
    """Local Execution Plane: agrega/corrige solo remotos definidos por política exacta."""
    return local_execution_plane.configure_remote(repo=repo, work_branch=work_branch, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key, remote=remote, dry_run=dry_run)


@mcp.tool
def local_exec_verified_git_author_status(username: str = "rafagye") -> dict[str, Any]:
    """Local Execution Plane: verifica identidad de autor git sin adivinar email."""
    return local_execution_plane.verified_git_author_status(username=username)


@mcp.tool
def local_exec_amend_commit_author(repo: str, work_branch: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str, username: str = "rafagye", email: str = "", dry_run: bool = True) -> dict[str, Any]:
    """Local Execution Plane: amend seguro del autor de HEAD solo con email verificado."""
    return local_execution_plane.amend_commit_author(repo=repo, work_branch=work_branch, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key, username=username, email=email, dry_run=dry_run)


@mcp.tool
def local_exec_push_branch(repo: str, work_branch: str, actor: str, task_id: str, correlation_id: str, idempotency_key: str, remote: str = "origin", dry_run: bool = True) -> dict[str, Any]:
    """Local Execution Plane: push seguro de rama de trabajo; sin force ni ramas protegidas."""
    return local_execution_plane.push_branch(repo=repo, work_branch=work_branch, actor=actor, task_id=task_id, correlation_id=correlation_id, idempotency_key=idempotency_key, remote=remote, dry_run=dry_run)


@mcp.tool
def local_exec_report_evidence(repo: str, work_branch: str, actor: str, task_id: str, correlation_id: str, status: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Local Execution Plane: registra evidencia saneada PASS/PARTIAL/FAIL."""
    return local_execution_plane.report_evidence(repo=repo, work_branch=work_branch, actor=actor, task_id=task_id, correlation_id=correlation_id, status=status, evidence=evidence)


@mcp.tool
def update_pipeline_status(id: str, status: str) -> dict[str, Any]:
    """Actualiza el estado de un borrador editorial."""
    return editorial_store.update_pipeline_status(id, status)


@mcp.tool
def publish_pipeline_item(id: str) -> dict[str, Any]:
    """Publica un item aprobado."""
    draft = editorial_store.get_draft(id)
    if not draft.get("ok"):
        return draft
    d = draft["draft"]
    if d.get("status") != editorial_store.STATUS_APPROVED:
        return {"ok": False, "error": "item not approved"}
    post_id = d.get("post_id")
    if not post_id:
        return {"ok": False, "error": "missing post_id"}
    db = mongo_store.get_db()
    dest = db["social_destinations"].find_one({"post_id": post_id})
    if not dest:
        return {"ok": False, "error": "destination not found"}
    return editorial_publish.publish_destination(str(dest["_id"]))


@mcp.tool
def video_pipeline_health() -> dict[str, Any]:
    """Estado del pipeline de vídeo (TTS, voces, ComfyUI, ffmpeg, límites)."""
    from raphiia_openai.video_pipeline.pipeline import pipeline_health

    return pipeline_health()


@mcp.tool
def list_video_voices() -> dict[str, Any]:
    """Voces disponibles para Video Studio (XTTS clonadas, Piper, límites de duración)."""
    from raphiia_openai.video_pipeline.voices import voice_catalog

    return voice_catalog()


@mcp.tool
def generate_video_content(
    title: str,
    brief: str = "",
    script: str = "",
    entity_id: str = "ent_innerchispa",
    aspect: str = "9:16",
    max_scenes: int = 6,
    voice: str = "auto",
    language: str = "",
    transition: str = "fade",
    qr_url: str = "",
    draft_id: str | None = None,
    auto_publish: bool = False,
    destinations: list[str] | None = None,
) -> dict[str, Any]:
    """Genera vídeo narrado local (XTTS/Piper + escenas + ffmpeg).

    aspect: 9:16 (Instagram/Reels) | 16:9 (YouTube) | 1:1
    voice: auto | xtts:rafael | xtts:hector | piper path | espeak (robótico)
    max_scenes: 1-24 (más escenas = vídeo más largo, ~max 180s)
    qr_url: URL opcional para insertar código QR en el vídeo
    transition: fade | none
    """
    from raphiia_openai.video_pipeline.pipeline import generate_video

    return generate_video(
        title=title,
        brief=brief,
        script=script,
        entity_id=entity_id,
        aspect=aspect,
        max_scenes=max_scenes,
        voice=voice or "auto",
        language=language or None,
        transition=transition,
        qr_url=qr_url,
        draft_id=draft_id,
        auto_publish=auto_publish,
        destinations=destinations,
    )


@mcp.tool
def publish_video_content(
    video_path: str,
    title: str = "",
    caption: str = "",
    destinations: list[str] | None = None,
    whatsapp_status_jids: list[str] | None = None,
    node: str = "amd",
) -> dict[str, Any]:
    """Publica un MP4 en WhatsApp Status, web InnerChispa, etc."""
    from raphiia_openai.video_pipeline.publish import publish_video

    return publish_video(
        video_path,
        title=title,
        caption=caption,
        destinations=destinations,
        whatsapp_status_jids=whatsapp_status_jids,
        node=node,
    )


@mcp.tool
def get_publish_logs(limit: int = 20) -> dict[str, Any]:
    """Logs recientes de publicación, imágenes y errores."""
    return mongo_store.get_publish_logs(limit=limit)



@mcp.tool
def save_funding_program(
    name: str,
    description: str | None = None,
    status: str | None = "active",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra un programa de funding / créditos reutilizables."""
    return funding_registry_module.save_funding_program(
        name=name,
        description=description,
        status=status,
        tags=tags,
        metadata=metadata,
    )


@mcp.tool
def list_funding_programs(query: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Lista programas funding."""
    return funding_registry_module.list_funding_programs(query=query, status=status, limit=limit)


@mcp.tool
def save_funding_application(
    title: str,
    program_id: str | None = None,
    body: str | None = None,
    status: str | None = "draft",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra una aplicación / postulación de funding."""
    return funding_registry_module.save_funding_application(
        title=title,
        program_id=program_id,
        body=body,
        status=status,
        metadata=metadata,
    )


@mcp.tool
def list_funding_applications(
    limit: int = 20,
    program_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Lista aplicaciones funding."""
    return funding_registry_module.list_funding_applications(limit=limit, program_id=program_id, status=status)


@mcp.tool
def application_get(application_id: str = "", program: str = "", title: str = "") -> dict[str, Any]:
    """Submission Workspace: obtiene postulación con preguntas versionadas."""
    from raphiia_openai import application_workspace as aw

    return aw.application_get(application_id=application_id, program=program, title=title)


@mcp.tool
def application_upsert(title: str, program: str = "", company: str = "", project: str = "", status: str = "active", application_id: str = "", metadata: dict[str, Any] | None = None, body: str = "", idempotency_key: str = "") -> dict[str, Any]:
    """Submission Workspace: crea/actualiza una postulación sin duplicarla."""
    from raphiia_openai import application_workspace as aw

    return aw.application_upsert(title, program=program, company=company, project=project, status=status, application_id=application_id, metadata=metadata, body=body, idempotency_key=idempotency_key)


@mcp.tool
def application_add_or_update_module(application_id: str, module: str, order: int = 0, status: str = "draft", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Submission Workspace: agrega/actualiza módulo o sección."""
    from raphiia_openai import application_workspace as aw

    return aw.application_add_or_update_module(application_id, module, order=order, status=status, metadata=metadata)


@mcp.tool
def application_upsert_question_answer(application_id: str, question_key: str, question_text: str, answer: str, module: str = "", max_chars: int = 0, version_status: str = "draft", source_refs: list[str] | None = None, rationale: str = "", idempotency_key: str = "", author_agent: str = "CHATGPT") -> dict[str, Any]:
    """Submission Workspace: versiona una respuesta por pregunta."""
    from raphiia_openai import application_workspace as aw

    return aw.application_upsert_question_answer(application_id, question_key, question_text, answer, module=module, max_chars=max_chars, version_status=version_status, source_refs=source_refs, rationale=rationale, idempotency_key=idempotency_key, author_agent=author_agent)


@mcp.tool
def application_list_questions(application_id: str, module: str = "", status: str = "") -> dict[str, Any]:
    """Submission Workspace: lista preguntas/respuestas por módulo/estado."""
    from raphiia_openai import application_workspace as aw

    return aw.application_list_questions(application_id, module=module, status=status)


@mcp.tool
def application_search(query: str, program: str = "", company: str = "", project: str = "", limit: int = 10) -> dict[str, Any]:
    """Submission Workspace: busca respuestas por texto y metadatos."""
    from raphiia_openai import application_workspace as aw

    return aw.application_search(query, program=program, company=company, project=project, limit=limit)


@mcp.tool
def application_attach_source(application_id: str, source: dict[str, Any], idempotency_key: str = "") -> dict[str, Any]:
    """Submission Workspace: asocia guía/fuente sin duplicar archivos grandes."""
    from raphiia_openai import application_workspace as aw

    return aw.application_attach_source(application_id, source, idempotency_key=idempotency_key)


@mcp.tool
def application_attach_evidence(application_id: str, evidence: dict[str, Any], idempotency_key: str = "") -> dict[str, Any]:
    """Submission Workspace: asocia evidencia/artefacto seguro."""
    from raphiia_openai import application_workspace as aw

    return aw.application_attach_evidence(application_id, evidence, idempotency_key=idempotency_key)


@mcp.tool
def application_history(application_id: str = "", question_key: str = "") -> dict[str, Any]:
    """Submission Workspace: historial de versiones por aplicación/pregunta."""
    from raphiia_openai import application_workspace as aw

    return aw.application_history(application_id=application_id, question_key=question_key)


@mcp.tool
def application_mark_submitted(application_id: str, submitted_at: str = "", evidence_refs: list[str] | None = None, idempotency_key: str = "") -> dict[str, Any]:
    """Submission Workspace: marca postulación como enviada."""
    from raphiia_openai import application_workspace as aw

    return aw.application_mark_submitted(application_id, submitted_at=submitted_at, evidence_refs=evidence_refs, idempotency_key=idempotency_key)


@mcp.tool
def application_export_snapshot(application_id: str, format: str = "markdown") -> dict[str, Any]:
    """Submission Workspace: exporta dossier JSON/Markdown."""
    from raphiia_openai import application_workspace as aw

    return aw.application_export_snapshot(application_id, format=format)


@mcp.tool
def application_migrate_legacy_funding_application(application_id: str, idempotency_key: str = "legacy_funding_migration") -> dict[str, Any]:
    """Submission Workspace: migra funding_applications existente sin duplicar."""
    from raphiia_openai import application_workspace as aw

    return aw.application_migrate_legacy_funding_application(application_id, idempotency_key=idempotency_key)


@mcp.tool
def save_funding_credit_account(
    name: str,
    provider: str | None = None,
    currency: str = "USD",
    balance: float | int = 0,
    status: str | None = "active",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crea cuenta de créditos o saldo funding."""
    return funding_registry_module.save_funding_credit_account(
        name=name,
        provider=provider,
        currency=currency,
        balance=balance,
        status=status,
        metadata=metadata,
    )


@mcp.tool
def record_funding_consumption(
    account_id: str,
    amount: float | int,
    reason: str,
    currency: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra consumo de créditos / gasto funding."""
    return funding_registry_module.record_funding_consumption(
        account_id=account_id,
        amount=amount,
        reason=reason,
        currency=currency,
        metadata=metadata,
    )


@mcp.tool
def link_funding_project(
    project_name: str | None = None,
    project_id: str | None = None,
    program_id: str | None = None,
    application_id: str | None = None,
    external_ref: str | None = None,
    status: str | None = "active",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Vincula un proyecto a funding."""
    return funding_registry_module.link_funding_project(
        project_name=project_name,
        project_id=project_id,
        program_id=program_id,
        application_id=application_id,
        external_ref=external_ref,
        status=status,
        metadata=metadata,
    )


@mcp.tool
def get_funding_registry_summary(limit: int = 5) -> dict[str, Any]:
    """Resumen compacto del registry de funding y créditos."""
    return funding_registry_module.get_funding_registry_summary(limit=limit)


def _url_ok(url: str, timeout: float = 2.5) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": getattr(resp, "status", 200), "preview": body[:400]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _systemctl_status(unit: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        state = (proc.stdout or proc.stderr or "").strip() or "unknown"
        return {"ok": state == "active", "state": state}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool
def system_health() -> dict[str, Any]:
    """Estado de Mongo, MCP, portal, funding-hub, LinkedIn, Gemini y daemon."""
    mongo = mongo_store.ping_mongo()
    mcp_ok = mongo_store.ping_mongo().get("ok", False)
    portal = _url_ok("http://127.0.0.1:8800/api/portal/overview")
    ralphia_health = _url_ok(f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/status")
    funding_hub = {"ok": _port_open("127.0.0.1", 8099), "port": 8099}
    linkedin = linkedin_client.config_status()
    gemini = {
        "ok": bool(GOOGLE_API_KEY),
        "provider": getattr(image_gen, "IMAGE_GEN_PROVIDER", "google"),
        "configured": bool(GOOGLE_API_KEY),
    }
    local_models = local_model_router.local_model_health()
    funding_registry = funding_registry_module.get_funding_registry_summary(limit=3)
    watcher = _systemctl_status("ralfia-coordination-daemon")
    daemon = _systemctl_status("ralfia-coordination-daemon")
    oauth = _url_ok(f"{OAUTH_ISSUER}/health")
    file_access = coordination_docs.list_coordination_files(path="chatgpt")
    return {
        "ok": bool(mongo.get("ok")),
        "mongodb": mongo,
        "mcp": {"ok": mcp_ok, "public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp"},
        "portal": portal,
        "ralphia_health": ralphia_health,
        "funding_hub": funding_hub,
        "linkedin_connector": linkedin,
        "gemini_image_api": gemini,
        "local_model_runtime": local_models,
        "funding_registry": funding_registry,
        "watcher": watcher,
        "daemon": daemon,
        "oauth": oauth,
        "file_access_tools": {"ok": bool(file_access.get("ok")), "count": file_access.get("count", 0)},
    }


@mcp.custom_route("/health", methods=["GET"])
async def mcp_health_http(_request: Request) -> JSONResponse:
    from raphiia_openai import mcp_fleet

    fleet = mcp_fleet.fleet_status()
    return JSONResponse(
        {
            "ok": fleet.get("ok"),
            "service": "ralphi-ia-mcp",
            "version": MCP_SERVER_VERSION,
            "catalog_version": fleet.get("catalog_version"),
            "local_node": fleet.get("local_node"),
            "nodes": fleet.get("nodes"),
        }
    )


@mcp.custom_route("/ready", methods=["GET"])
async def mcp_ready_http(_request: Request) -> JSONResponse:
    mongo = mongo_store.ping_mongo()
    ready = bool(mongo.get("ok"))
    return JSONResponse({"ok": ready, "mongodb": mongo}, status_code=200 if ready else 503)


@mcp.custom_route("/version", methods=["GET"])
async def mcp_version_http(_request: Request) -> JSONResponse:
    ver = mcp_diagnostics.mcp_version()
    return JSONResponse(
        {
            "ok": True,
            "server_version": MCP_SERVER_VERSION,
            "catalog_version": ver.get("catalog_version"),
            "tool_count": ver.get("runtime_tool_count"),
            "manifest_hash": ver.get("manifest_hash"),
        }
    )


@mcp.custom_route("/capabilities", methods=["GET"])
async def mcp_capabilities_http(_request: Request) -> JSONResponse:
    from raphiia_openai import mcp_fleet, mcp_profiles

    caps = mcp_diagnostics.list_mcp_capabilities()
    return JSONResponse(
        {
            "ok": True,
            "logical_version": MCP_SERVER_VERSION,
            "profiles_version": mcp_profiles.PROFILES_VERSION,
            "profiles": sorted(mcp_profiles.PROFILES.keys()),
            "fleet": mcp_fleet.fleet_status(),
            "tools": caps.get("tools") or [],
            "tool_count": caps.get("tool_count"),
        }
    )


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def mcp_oauth_protected_resource(request: Request) -> JSONResponse:
    from raphiia_openai.oauth_metadata import protected_resource_metadata

    return JSONResponse(protected_resource_metadata(request.headers.get("host")))


@mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
async def mcp_oauth_protected_resource_path(request: Request) -> JSONResponse:
    from raphiia_openai.oauth_metadata import protected_resource_metadata

    return JSONResponse(protected_resource_metadata(request.headers.get("host")))


@mcp.custom_route("/notion/webhook", methods=["POST"])
async def notion_webhook_http(request: Request) -> JSONResponse:
    """Endpoint público HTTPS para webhooks Notion (vía ngrok)."""
    from raphiia_openai import notion_webhook

    raw = await request.body()
    sig = request.headers.get("X-Notion-Signature")
    result = notion_webhook.handle_notion_webhook(raw, signature=sig)
    status = int(result.pop("http_status", 200))
    return JSONResponse(result, status_code=status)


@mcp.custom_route("/notion/webhook/pending", methods=["GET"])
async def notion_webhook_pending_http(_request: Request) -> JSONResponse:
    """Token de verificación pendiente (tras crear suscripción en Notion)."""
    from raphiia_openai import notion_webhook

    return JSONResponse(notion_webhook.get_pending_verification_token())


@mcp.custom_route("/notion/webhook/setup", methods=["GET"])
async def notion_webhook_setup_http(_request: Request) -> JSONResponse:
    from raphiia_openai import notion_webhook

    return JSONResponse(notion_webhook.get_notion_webhook_setup())


def _apply_runtime_tool_profile(profile_name: str) -> dict[str, Any]:
    """Restrict tools advertised and callable by this MCP process to one profile."""
    from fastmcp.server.transforms import Visibility
    from raphiia_openai import mcp_profiles

    profile = mcp_profiles.get_profile(profile_name)
    if not profile.get("ok"):
        raise RuntimeError(f"unknown MCP tool profile: {profile_name}")
    names = set(profile["tools"])
    mcp.add_transform(Visibility(False, components={"tool"}, match_all=True))
    mcp.add_transform(Visibility(True, components={"tool"}, names=names))
    return {
        "profile": profile_name,
        "tool_count": len(names),
        "catalog_pin": profile["catalog_pin"],
        "profiles_version": profile["profiles_version"],
    }


if __name__ == "__main__":
    runtime_profile = os.getenv("MCP_TOOL_PROFILE", "").strip().lower()
    if runtime_profile:
        profile_info = _apply_runtime_tool_profile(runtime_profile)
        mongo_store.log_sync("mcp_profile_startup", host=MCP_HOST, port=MCP_PORT, **profile_info)
    mongo_store.log_sync("mcp_startup", host=MCP_HOST, port=MCP_PORT)
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT, path="/mcp")


# --- InnerOS A2A transport bridge ---

@mcp.tool
def a2a_status() -> dict[str, Any]:
    """A2A bridge health, SDK visibility and registered InnerOS agent roles."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.status()


@mcp.tool
def a2a_agent_cards() -> dict[str, Any]:
    """Return the five canonical Agent Cards exposed by the InnerOS A2A bridge."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.agent_cards()


@mcp.tool
def a2a_dispatch(
    agent_id: str,
    title: str,
    body: str,
    correlation_id: str = "",
    priority: str = "p0",
    related_project: str = "inneros",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit durable agent work over A2A while RACB/ops_tasks remain source of truth."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.dispatch(
        agent_id=agent_id,
        title=title,
        body=body,
        correlation_id=correlation_id,
        priority=priority,
        related_project=related_project or None,
        dry_run=dry_run,
    )


@mcp.tool
def a2a_task_status(a2a_task_id: str) -> dict[str, Any]:
    """Project an InnerOS RACB task into its A2A state and evidence artifacts."""
    from raphiia_openai import a2a_bridge

    return a2a_bridge.task_status(a2a_task_id)


# --- MOD-OWNER-VAULT generic safe bridge ---
@mcp.tool
def owner_vault_store_secret(category: str, key: str, secret: str, label: str = "", project_id: str = "", actor: str = "RAFAEL") -> dict[str, Any]:
    """Owner Vault: guarda un secreto server-side y nunca devuelve plaintext."""
    from raphiia_openai import owner_vault_bridge
    return owner_vault_bridge.store_secret(category=category, key=key, secret=secret, label=label, project_id=project_id, actor=actor)


@mcp.tool
def owner_vault_secret_status(category: str, key: str, actor: str = "RAFAEL") -> dict[str, Any]:
    """Owner Vault: devuelve solo presencia y metadata, nunca plaintext."""
    from raphiia_openai import owner_vault_bridge
    return owner_vault_bridge.secret_status(category=category, key=key, actor=actor)


@mcp.tool
def owner_vault_materialize_project_env(namespace: str, bindings: dict[str, str], static_values: dict[str, str] | None = None, actor: str = "RAFAEL") -> dict[str, Any]:
    """Owner Vault: materializa refs en runtime.env chmod 0600 sin devolver secretos."""
    from raphiia_openai import owner_vault_bridge
    return owner_vault_bridge.materialize_project_env(namespace=namespace, bindings=bindings, static_values=static_values, actor=actor)
