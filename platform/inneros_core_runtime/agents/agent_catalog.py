"""Catálogo canónico de agentes RalfIA — IDs, nombres amigables, aliases, tools."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# status: functional = invoke_agent() puede ejecutarlo en MCP runtime
# Los YAML CrewAI en agents_pool/ son persona/metadata — NO se usa CrewAI en producción MCP

def _entry(
    display_name: str,
    role: str,
    *,
    aliases: list[str] | None = None,
    status: str = "functional",
    entry_tool: str | None = None,
    task_kind: str | None = None,
    mcp_profile: str | None = None,
    intent_keywords: list[str] | None = None,
    domain: str = "platform",
) -> dict[str, Any]:
    return {
        "display_name": display_name,
        "role": role,
        "aliases": sorted(set(a.lower() for a in (aliases or []))),
        "status": status,
        "entry_tool": entry_tool,
        "task_kind": task_kind,
        "mcp_profile": mcp_profile,
        "intent_keywords": [k.lower() for k in (intent_keywords or [])],
        "domain": domain,
    }


AGENT_CATALOG: dict[str, dict[str, Any]] = {
    "AG-01": _entry("Net Router", "Red y conectividad", domain="infra", entry_tool="invoke_agent", intent_keywords=["red", "puertos", "network"]),
    "AG-02": _entry("Context Memory", "Memoria de contexto", domain="memory", entry_tool="invoke_agent", intent_keywords=["memoria", "recuerda", "contexto"]),
    "AG-03": _entry("Telemetry Analyst", "Análisis telemetría / uso IA", domain="ops", entry_tool="invoke_agent"),
    "AG-04": _entry("Doc Maker", "Documentos coordinación", domain="docs", entry_tool="invoke_agent", intent_keywords=["documento", "markdown", "hub"]),
    "AG-05": _entry("Email Gatekeeper", "Correo archivado", domain="email", entry_tool="invoke_agent", intent_keywords=["correo", "email", "buscar mail"]),
    "AG-06": _entry("Field Voice", "Voz en campo PC Doctor", domain="pcdoctor", entry_tool="invoke_agent"),
    "AG-07": _entry("Notion Cosmos", "Estado Notion", domain="notion", entry_tool="invoke_agent", intent_keywords=["notion"]),
    "AG-08": _entry("Financial Consolidator", "Finanzas consolidadas", domain="finance", entry_tool="invoke_agent", intent_keywords=["contabilidad", "finanzas", "accounting"]),
    "AG-09": _entry("Catalyst RAG", "Búsqueda híbrida RAG", domain="platform", entry_tool="invoke_agent", intent_keywords=["buscar", "rag", "search"]),
    "AG-10": _entry("Fiscal Signer", "Estado fiscal Contifico", domain="finance", entry_tool="invoke_agent", intent_keywords=["contifico", "fiscal"]),
    "AG-11": _entry("Media Marketing", "Pipeline editorial", domain="social", entry_tool="invoke_agent", intent_keywords=["marketing", "contenido", "linkedin"]),
    "AG-12": _entry("Project Provisioner", "Bindings proyectos", domain="platform", entry_tool="invoke_agent"),
    "AG-13": _entry("Voice Inspection", "Informe inspección voz", domain="pcdoctor", entry_tool="invoke_agent"),
    "AG-14": _entry("CRM Onboarder", "Alta clientes CRM", domain="pcdoctor", entry_tool="invoke_agent", intent_keywords=["nuevo cliente", "alta cliente"]),
    "AG-15": _entry("Inventory Cataloger", "Catálogo inventario", domain="pcdoctor", entry_tool="invoke_agent", intent_keywords=["inventario", "stock"]),
    "AG-16": _entry("Quote Calculator", "Cálculos cotización", domain="pcdoctor", entry_tool="invoke_agent", task_kind="quote"),
    "AG-17": _entry("Contifico Bridge", "Facturación SRI Ecuador", domain="finance", entry_tool="invoke_agent", intent_keywords=["factura fiscal", "sri", "contifico"]),
    "AG-18": _entry("Collections Tracker", "Cobranzas", domain="finance", entry_tool="invoke_agent", intent_keywords=["cobranza", "cobrar", "cxc"]),
    "AG-19": _entry("Sales Funnel Scout", "Embudo ventas / clientes", domain="pcdoctor", entry_tool="invoke_agent"),
    "AG-20": _entry("Hub Dashboard", "Dashboard HUB vivo", domain="coordination", entry_tool="invoke_agent", intent_keywords=["hub", "dashboard", "estado vivo"]),
    "AG-21": _entry("Hackathon Harvester", "Docs hackathons", domain="funding", entry_tool="invoke_agent", task_kind="hackathon"),
    "AG-22": _entry("Opportunity Collector", "Recolector oportunidades/grants", domain="funding", entry_tool="invoke_agent", task_kind="credits", intent_keywords=["oportunidad", "grant", "convocatoria", "funding"]),
    "AG-23": _entry("Opportunity Analyst", "Analista oportunidades", domain="funding", entry_tool="invoke_agent", task_kind="hackathon"),
    "AG-24": _entry("Application Drafter", "Borradores postulación grants", domain="funding", entry_tool="invoke_agent"),
    "AG-25": _entry("RalfIA", "Orquestador principal — ve todo y enruta", domain="platform", entry_tool="ralfia_dispatch", aliases=["ralfia", "ralphi ia", "orquestador"], intent_keywords=["ralfia", "orquestador", "qué agente", "ayuda general"], mcp_profile="ralfia_hub"),
    "AG-26": _entry("Discord Bridge", "Discord + SRE local", domain="platform", entry_tool="invoke_agent", intent_keywords=["discord"]),
    "AG-27": _entry("Security Health", "Salud sistema / seguridad", domain="ops", entry_tool="invoke_agent"),
    "AG-28": _entry("Backup Sync", "Sync plataforma / backup", domain="ops", entry_tool="invoke_agent"),
    "AG-29": _entry("Log Ops", "Logs servicios peer ops", domain="ops", entry_tool="invoke_agent", intent_keywords=["logs", "journal"]),
    "AG-30": _entry("WhatsApp Agent", "WhatsApp Evolution", domain="whatsapp", entry_tool="invoke_agent", intent_keywords=["whatsapp", "wsp", "enviar mensaje"]),
    "AG-31": _entry("Service Recovery", "Recuperación servicios", domain="ops", entry_tool="invoke_agent", intent_keywords=["health watch", "recuperar servicio", "caído"]),
    "AG-32": _entry("Home Assistant", "Casa inteligente", domain="home", entry_tool="invoke_agent", intent_keywords=["casa", "luz", "home assistant"]),
    "AG-33": _entry("Sync Sentinel", "Sincronización docs", domain="coordination", entry_tool="invoke_agent"),
    "AG-34": _entry("KB Ingest", "Ingesta conocimiento", domain="memory", entry_tool="invoke_agent"),
    "AG-35": _entry("Ecosystem Pulse", "Pulso ecosistema / flota MCP", domain="ops", entry_tool="invoke_agent"),
    "AG-36": _entry("Deferred Tasks", "Tareas diferidas / ops propuestas", domain="coordination", entry_tool="invoke_agent"),
    "AG-37": _entry("Disk Steward", "Espacio en disco", domain="ops", entry_tool="invoke_agent", intent_keywords=["disco", "espacio", "storage"]),
    "AG-38": _entry("Vero", "Comercial PC Doctor (NL)", domain="pcdoctor", entry_tool="invoke_agent", task_kind="vero", mcp_profile="quoter", aliases=["vero", "comercial"], intent_keywords=["cotizar", "cotización", "dile a vero", "presupuesto", "cliente"]),
    "AG-39": _entry("Raúl", "Catálogo local / Atlas", domain="pcdoctor", entry_tool="invoke_agent", aliases=["raul", "raúl", "atlas", "catálogo"], intent_keywords=["catálogo", "producto", "precio proveedor"]),
    "AG-40": _entry("Runtime Reconciler", "Inventario dual-nodo", domain="ops", entry_tool="invoke_agent", task_kind="reconcile", intent_keywords=["reconciliar", "runtime", "dual nodo", "matriz servicios"]),
    "AG-41": _entry("Peer Ops", "Operaciones servidores .4/.5", domain="ops", entry_tool="invoke_agent", task_kind="peer_ops", intent_keywords=["peer ops", "servidor", "reiniciar servicio", "amd", "intel"]),
    "AG-42": _entry("Service Guardian", "Vigilancia + auto-reparación local", domain="ops", entry_tool="invoke_agent", task_kind="guardian", aliases=["guardian", "guardián", "self-heal"], intent_keywords=["vigilar", "servicios caídos", "guardian", "watch", "reparar", "auto-reparar", "self heal", "arreglar servicios"]),
    "AG-43": _entry("Platform Sync", "Sync AMD→Intel", domain="ops", entry_tool="invoke_agent", intent_keywords=["sync platform", "failover"]),
    "AG-44": _entry("Cloud Deployer", "Deploy cloud GCP/CF", domain="ops", entry_tool="invoke_agent", intent_keywords=["deploy cloud", "gcp"]),
    "AG-45": _entry("Local Exec", "Ejecución local segura (Codex plane)", domain="platform", entry_tool="invoke_agent", intent_keywords=["local exec", "worktree", "patch"]),
    "AG-46": _entry("Quote Agent", "Cotizaciones PC Doctor", domain="pcdoctor", entry_tool="invoke_agent", task_kind="quote", intent_keywords=["cotizar", "cotización", "quote"]),
    "AG-47": _entry("Report Agent", "Informes técnicos", domain="pcdoctor", entry_tool="invoke_agent", task_kind="report", intent_keywords=["informe", "reporte técnico", "supervisor"]),
    "AG-48": _entry("Billing Agent", "Borradores factura", domain="pcdoctor", entry_tool="invoke_agent", task_kind="invoice", intent_keywords=["factura", "facturar", "invoice"]),
    "AG-49": _entry("Dispatcher", "Entrada única local-first", domain="platform", entry_tool="dispatch_local_agent", aliases=["dispatcher", "dispatch"], intent_keywords=["dispatch", "agente local"]),
    "AG-50": _entry("Daily Companion", "Compañero día a día", domain="life", entry_tool="invoke_agent", task_kind="daily", mcp_profile="daily_companion", aliases=["companion", "compañero", "día a día"], intent_keywords=["cómo va mi día", "buenos días", "pendientes hoy", "brief", "día a día", "compañero"]),
    "AG-51": _entry("Health Memory", "Historial de salud", domain="life", entry_tool="invoke_agent", task_kind="salud", mcp_profile="health_memory", aliases=["salud", "health", "médico"], intent_keywords=["salud", "me siento", "registrar salud", "historial médico", "presión", "glucosa", "dolor", "síntoma", "vitals", "cómo estoy de salud", "guardar salud"]),
    "AG-52": _entry("Iskcon Ops", "Operaciones ISKCON", domain="iskcon", entry_tool="invoke_agent", task_kind="iskcon", mcp_profile="iskcon_ops", aliases=["iskcon", "ffl", "panihati", "templo", "yoga vaishnava"], intent_keywords=["iskcon", "food for life", "ffl", "panihati", "templo", "festival devocional", "yoga", "vaishnava", "bhagavad gita", "kirtan", "prasadam", "clases", "whatsapp yoga"]),
    "AG-53": _entry("Hackathon Agent", "Hackathons y convocatorias", domain="funding", entry_tool="invoke_agent", task_kind="hackathon", intent_keywords=["hackathon", "devpost", "xprize"]),
    "AG-54": _entry("Funding Credits", "Créditos y grants", domain="funding", entry_tool="invoke_agent", task_kind="credits", mcp_profile="hackathon_funding", aliases=["créditos", "credits", "grants"], intent_keywords=["crédito", "credit", "grant", "funding", "aws activate", "google cloud credits", "no desperdiciar créditos", "bright data"]),
    "AG-55": _entry("Browser Ops", "Navegador local Playwright", domain="platform", entry_tool="invoke_agent", task_kind="browser", mcp_profile="ralfia_hub", aliases=["browser", "navegador", "playwright", "formulario"], intent_keywords=["navegador", "browser", "llenar formulario", "publicar web", "screenshot pagina", "playwright", "automatizar web"]),
    "AG-56": _entry("Sandbox Fleet", "Modelos uncensored + WebUI sandbox", domain="research", entry_tool="invoke_agent", task_kind="sandbox", mcp_profile="local_fleet", aliases=["sandbox", "uncensored", "research sandbox"], intent_keywords=["sandbox", "uncensored", "modelo local", "instalar modelo", "ollama sandbox", "3004", "research"]),
}


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def get_catalog_entry(agent_id: str) -> dict[str, Any] | None:
    meta = AGENT_CATALOG.get(agent_id.upper().replace("_", "-"))
    if not meta:
        return None
    return {"agent_id": agent_id.upper().replace("_", "-"), **meta}


def get_agent_catalog(
    *,
    domain: str | None = None,
    status: str | None = None,
    functional_only: bool = False,
) -> dict[str, Any]:
    from raphiia_openai.agents.pool_agent_runners import get_runner_registry

    runners = get_runner_registry()
    items: list[dict[str, Any]] = []
    for aid, meta in sorted(AGENT_CATALOG.items(), key=lambda x: int(re.search(r"\d+", x[0]).group())):
        if domain and meta.get("domain") != domain.strip().lower():
            continue
        if status and meta.get("status") != status.strip().lower():
            continue
        if functional_only and aid not in runners:
            continue
        call_hint = meta.get("task_kind") or meta.get("entry_tool") or "invoke_agent"
        how = (
            f'dispatch_local_agent("{meta["task_kind"]}")'
            if meta.get("task_kind")
            else (f'invoke_agent("{aid}")' if meta.get("entry_tool") == "invoke_agent" else meta.get("entry_tool"))
        )
        items.append({
            "agent_id": aid,
            "display_name": meta["display_name"],
            "role": meta["role"],
            "aliases": meta["aliases"],
            "status": "functional" if aid in runners else meta.get("status"),
            "how_to_call": how,
            "entry_tool": meta.get("entry_tool"),
            "task_kind": meta.get("task_kind"),
            "mcp_profile": meta.get("mcp_profile"),
            "domain": meta.get("domain"),
        })
    return {
        "ok": True,
        "count": len(items),
        "agents": items,
        "routing_hint": "Principal: ralfia_dispatch(mensaje). Por ID: invoke_agent('AG-51'). NL: route_agent_request(mensaje, auto_execute=true)",
        "doc": "get_agent_catalog() + resolve_agent()",
    }


def resolve_agent(message: str, limit: int = 3) -> dict[str, Any]:
    """Resuelve qué agente corresponde a un mensaje en lenguaje natural."""
    text = _normalize(message or "")
    if not text.strip():
        return {"ok": False, "error": "empty_message"}

    scored: list[tuple[float, str, dict[str, Any]]] = []
    tokens = set(re.findall(r"[a-z0-9áéíóúñ]+", text))

    for aid, meta in AGENT_CATALOG.items():
        from raphiia_openai.agents.pool_agent_runners import get_runner_registry
        if aid not in get_runner_registry():
            continue
        score = 0.0
        for alias in meta.get("aliases") or []:
            if alias in text:
                score += 3.0
        for kw in meta.get("intent_keywords") or []:
            kn = _normalize(kw)
            if kn in text:
                score += 2.5
            elif any(w in kn for w in tokens if len(w) > 3):
                score += 0.5
        if score > 0:
            scored.append((score, aid, meta))

    scored.sort(key=lambda x: (-x[0], x[1]))
    matches = []
    for score, aid, meta in scored[: max(1, min(limit, 5))]:
        matches.append({
            "agent_id": aid,
            "display_name": meta["display_name"],
            "role": meta["role"],
            "confidence": round(min(1.0, score / 5.0), 3),
            "entry_tool": meta.get("entry_tool"),
            "task_kind": meta.get("task_kind"),
            "status": meta.get("status"),
        })

    best = matches[0] if matches else None
    return {
        "ok": True,
        "message_preview": message[:200],
        "best_match": best,
        "alternatives": matches[1:],
        "execute_hint": (
            f'route_agent_request("{message[:80]}...", auto_execute=true)'
            if best else "get_agent_catalog(functional_only=true)"
        ),
    }
