"""Control de servicios systemd — reinicio automático tras cambios de config."""

from __future__ import annotations

import subprocess
from typing import Any

from raphiia_openai import portal_bridge
from raphiia_openai.settings import OPS_PANEL_PUBLIC_URL, RALFIA_LAN_IP

HOST = RALFIA_LAN_IP

# Claves de config → unidades que deben reiniciarse para aplicar cambios
CONFIG_RESTART_MAP: dict[str, list[dict[str, str]]] = {
    "MCP_API_KEY": [{"unit": "ralfia-mcp.service", "scope": "user"}],
    "GOOGLE_API_KEY": [
        {"unit": "ralfia-app.service", "scope": "user"},
        {"unit": "ralfia-editorial-worker.service", "scope": "user"},
    ],
    "GEMINI_API_KEY": [
        {"unit": "ralfia-app.service", "scope": "user"},
        {"unit": "ralfia-editorial-worker.service", "scope": "user"},
    ],
    "LINKEDIN_ACCESS_TOKEN": [{"unit": "ralfia-app.service", "scope": "user"}],
    "LINKEDIN_AUTHOR_URN": [{"unit": "ralfia-app.service", "scope": "user"}],
    "LINKEDIN_CLIENT_ID": [{"unit": "ralfia-app.service", "scope": "user"}],
    "LINKEDIN_CLIENT_SECRET": [{"unit": "ralfia-app.service", "scope": "user"}],
    "LINKEDIN_REDIRECT_URI": [{"unit": "ralfia-app.service", "scope": "user"}],
    "IMAGE_GEN_PROVIDER": [{"unit": "ralfia-app.service", "scope": "user"}],
    "LOCAL_IMAGE_PROVIDER": [{"unit": "ralfia-app.service", "scope": "user"}],
    "COMFYUI_URL": [{"unit": "comfyui.service", "scope": "user"}],
    "COMFYUI_CHECKPOINT": [{"unit": "comfyui.service", "scope": "user"}],
    "AUTOMATIC1111_URL": [{"unit": "automatic1111.service", "scope": "user"}],
}

# Cockpit Ralphi IA — servicios reales del sistema (no hackatones)
COCKPIT_SERVICES: list[dict[str, Any]] = [
    {
        "id": "portal",
        "tier": "core",
        "label": "Panel Control",
        "desc": "Este cockpit — proyectos, config, ops",
        "unit": "ralfia-portal.service",
        "scope": "user",
        "port": 2002,
        "path": "/",
        "icon": "🎛️",
        "action": "open",
    },
    {
        "id": "editorial",
        "tier": "core",
        "label": "Editorial Hub",
        "desc": "LinkedIn, borradores, imágenes",
        "unit": "ralfia-app.service",
        "scope": "user",
        "port": 8101,
        "path": "/editorial",
        "icon": "✍️",
        "action": "open",
    },
    {
        "id": "ralphia-app",
        "tier": "core",
        "label": "Ralphi App",
        "desc": "API + status del puente MCP",
        "unit": "ralfia-app.service",
        "scope": "user",
        "port": 8101,
        "path": "/status",
        "icon": "🧭",
        "action": "open",
    },
    {
        "id": "mcp",
        "tier": "core",
        "label": "Conector MCP",
        "desc": "ChatGPT Connectors — no es página web; usa el estado",
        "unit": "ralfia-mcp.service",
        "scope": "user",
        "port": 8102,
        "path": "",
        "icon": "🔐",
        "action": "mcp_info",
    },
    {
        "id": "admin",
        "tier": "daily",
        "label": "PC Doctor Admin",
        "desc": "Mini-ERP — clientes, inventario",
        "unit": "swarm-admin.service",
        "scope": "system",
        "ports": [5173, 5174],
        "path": "",
        "icon": "📋",
        "action": "open",
    },
    {
        "id": "swarm-api",
        "tier": "daily",
        "label": "Swarm-OS API",
        "desc": "Cerebro operativo PC Doctor",
        "unit": "swarm-api.service",
        "scope": "system",
        "port": 8100,
        "path": "/docs",
        "icon": "⚡",
        "action": "open",
    },
    {
        "id": "smart-quoter",
        "tier": "daily",
        "label": "Smart Quoter",
        "desc": "Cotizaciones InnerSpark — audio, IA local, PDF, clientes",
        "unit": "ralfia-smart-quoter.service",
        "scope": "user",
        "port": 2026,
        "path": "/",
        "icon": "💰",
        "action": "open",
    },
    {
        "id": "uipath-copilot",
        "tier": "daily",
        "label": "UiPath Copilot",
        "desc": "Dashboard RPA — local :8097, público vía ngrok /uipath",
        "unit": "swarm-uipath-copilot.service",
        "scope": "system",
        "port": 8097,
        "path": "/dashboard",
        "icon": "🤖",
        "action": "open",
    },
    {
        "id": "ngrok",
        "tier": "core",
        "label": "ngrok HTTPS",
        "desc": "Túnel público — ChatGPT MCP, UiPath, OAuth",
        "unit": "swarm-ngrok.service",
        "scope": "system",
        "port": 4040,
        "path": "",
        "icon": "🌐",
        "action": "none",
    },
    {
        "id": "coordination",
        "tier": "core",
        "label": "Coordinación AG-25",
        "desc": "Daemon memoria compartida ai_coordination",
        "unit": "ralfia-coordination-daemon.service",
        "scope": "user",
        "port": None,
        "path": "",
        "icon": "🔄",
        "action": "none",
    },
]

# Stack Docker / infra — visible en panel con reinicio por contenedor
DOCKER_COCKPIT_SERVICES: list[dict[str, Any]] = [
    {
        "id": "open-webui",
        "tier": "daily",
        "label": "Open WebUI",
        "desc": "Chat Ollama + MCP + presets RalfIA",
        "container": "open-webui",
        "port": 3000,
        "path": "/",
        "icon": "💬",
        "action": "open",
    },
    {
        "id": "evolution",
        "tier": "daily",
        "label": "Evolution WhatsApp",
        "desc": "API WhatsApp backup AMD",
        "container": "evolution_api",
        "port": 8082,
        "path": "/manager",
        "icon": "📱",
        "action": "open",
    },
    {
        "id": "n8n",
        "tier": "daily",
        "label": "n8n",
        "desc": "Automatizaciones visuales",
        "container": "n8n",
        "port": 5678,
        "path": "/",
        "icon": "🔗",
        "action": "open",
    },
    {
        "id": "filebrowser",
        "tier": "daily",
        "label": "Gestor archivos",
        "desc": "FileBrowser — /home/rlopez/data",
        "container": "filebrowser",
        "port": 8081,
        "path": "/",
        "icon": "📁",
        "action": "open",
    },
    {
        "id": "qdrant",
        "tier": "daily",
        "label": "Qdrant",
        "desc": "Vectores semánticos",
        "container": "qdrant",
        "port": 6333,
        "path": "/dashboard",
        "icon": "🔍",
        "action": "open",
    },
    {
        "id": "anythingllm",
        "tier": "daily",
        "label": "AnythingLLM",
        "desc": "RAG documentos",
        "container": "anythingllm",
        "port": 3001,
        "path": "/",
        "icon": "📚",
        "action": "open",
    },
    {
        "id": "whisper",
        "tier": "daily",
        "label": "Whisper ASR",
        "desc": "Voz a texto local",
        "container": "whisper-service",
        "port": 9000,
        "path": "/",
        "icon": "🎙️",
        "action": "open",
    },
    {
        "id": "ollama",
        "tier": "core",
        "label": "Ollama",
        "desc": "Modelos locales CPU/GPU",
        "unit": "ollama.service",
        "scope": "system",
        "port": 11434,
        "path": "",
        "icon": "🧠",
        "action": "none",
    },
]


def _unit_active(unit: str, scope: str) -> str:
    cmd = ["systemctl", "is-active", unit] if scope == "system" else ["systemctl", "--user", "is-active", unit]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (proc.stdout or proc.stderr or "").strip()


def restart_unit(unit: str, *, scope: str = "user", verify: bool = True) -> dict[str, Any]:
    prefix = [] if scope == "system" else ["--user"]
    proc = subprocess.run(
        ["systemctl", *prefix, "restart", unit],
        capture_output=True,
        text=True,
    )
    state = _unit_active(unit, scope)
    ok = state == "active" and proc.returncode == 0
    result = {
        "unit": unit,
        "scope": scope,
        "ok": ok,
        "state": state,
        "stderr": (proc.stderr or "").strip()[:200],
    }
    if verify:
        from raphiia_openai.recovery_agent import schedule_post_restart_verify

        schedule_post_restart_verify([result], trigger=f"restart:{unit}")
    return result


def restart_for_config_keys(keys: list[str]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    results: list[dict[str, Any]] = []
    for key in keys:
        for spec in CONFIG_RESTART_MAP.get(key, []):
            unit = spec["unit"]
            scope = spec.get("scope", "user")
            token = (unit, scope)
            if token in seen:
                continue
            seen.add(token)
            results.append(restart_unit(unit, scope=scope, verify=False))
    if results:
        from raphiia_openai.recovery_agent import schedule_post_restart_verify

        schedule_post_restart_verify(results, trigger="config_change")
    return results


def resolve_admin_port() -> int:
    for port in (5173, 5174):
        if portal_bridge._tcp_open(port):
            return port
    return 5173


def _service_url(svc: dict[str, Any]) -> str:
    if svc.get("id") == "admin":
        port = resolve_admin_port()
        return f"http://{HOST}:{port}/"
    if svc.get("id") == "ngrok":
        from raphiia_openai.ngrok_watch import NGROK_PUBLIC_HOST

        return f"https://{NGROK_PUBLIC_HOST}/"
    port = svc.get("port")
    path = svc.get("path") or ""
    if port:
        return f"http://{HOST}:{port}{path}"
    return OPS_PANEL_PUBLIC_URL


def _service_health(svc: dict[str, Any]) -> str:
    if svc.get("id") == "ngrok":
        from raphiia_openai import ngrok_watch

        return ngrok_watch.check_ngrok_tunnel().get("status", "unknown")
    if svc.get("container"):
        port = svc.get("port")
        if port and portal_bridge._tcp_open(int(port)):
            path = svc.get("path") or "/"
            if path and path != "/":
                return portal_bridge._http_probe(f"http://127.0.0.1:{port}{path}")
            return portal_bridge._http_probe(f"http://127.0.0.1:{port}/")
        return "up" if _docker_running(svc["container"]) else "down"
    if svc.get("id") == "admin":
        port = resolve_admin_port()
        return "up" if portal_bridge._tcp_open(port) else "down"
    if svc.get("id") == "mcp":
        port = int(svc["port"])
        unit = svc.get("unit")
        scope = svc.get("scope", "user")
        if portal_bridge._tcp_open(port) and unit and _unit_active(unit, scope) == "active":
            return "up"
        return "down"
    port = svc.get("port")
    if port and portal_bridge._tcp_open(int(port)):
        path = svc.get("path") or "/"
        if path.startswith("/") and path != "/":
            return portal_bridge._http_probe(f"http://127.0.0.1:{port}{path}")
        return portal_bridge._http_probe(f"http://127.0.0.1:{port}/") if path == "/" else "up"
    unit = svc.get("unit")
    scope = svc.get("scope", "user")
    if unit and _unit_active(unit, scope) == "active":
        if svc.get("id") in ("coordination", "ollama", "ngrok"):
            return "up"
        return "degraded"
    return "down"


def restart_docker(container: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["docker", "restart", container],
        capture_output=True,
        text=True,
    )
    ok = proc.returncode == 0
    return {
        "container": container,
        "ok": ok,
        "stderr": (proc.stderr or "").strip()[:200],
        "stdout": (proc.stdout or "").strip()[:200],
    }


def _docker_running(name: str) -> bool:
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def cockpit_status() -> dict[str, Any]:
    from raphiia_openai import config_store

    items = []
    all_services = COCKPIT_SERVICES + DOCKER_COCKPIT_SERVICES
    for svc in all_services:
        health = _service_health(svc)
        unit = svc.get("unit")
        scope = svc.get("scope", "user")
        container = svc.get("container")
        systemd = _unit_active(unit, scope) if unit else ("docker" if container and _docker_running(container) else "n/a")
        items.append(
            {
                **svc,
                "url": _service_url(svc) if svc.get("action") == "open" else "",
                "health": health,
                "systemd": systemd,
                "admin_port": resolve_admin_port() if svc.get("id") == "admin" else None,
            }
        )
    cfg = config_store.status_catalog()
    return {
        "ok": True,
        "host": HOST,
        "panel_url": OPS_PANEL_PUBLIC_URL,
        "admin_port": resolve_admin_port(),
        "config_ok": cfg.get("ok"),
        "config_summary": f"{cfg.get('configured_count', 0)}/{cfg.get('total_count', 0)}",
        "services": items,
    }
