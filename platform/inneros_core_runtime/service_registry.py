"""Service Registry Mongo — fuente canónica para panel :2002 y watchdog."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.settings import (
    COL_SERVICE_REGISTRY,
    PORTAL_SERVICES_JSON,
    RALFIA_AMD_HOST,
    RALFIA_INTEL_HOST,
    RALFIA_LAN_IP,
)

HOST = RALFIA_LAN_IP
STATUSES = frozenset({
    "up", "down", "unauthorized_alive", "degraded", "timeout", "unknown",
    "pending_review", "on_demand", "skipped_wrong_node", "archived",
})
STATE_MODES = frozenset({"always_on", "on_demand", "intel_only", "amd_only", "legacy"})

DEFAULT_SERVICES: list[dict[str, Any]] = [
    {
        "service_id": "portal-control-center",
        "name": "Ralphi IA Control Center",
        "project": "ralfia",
        "type": "control_panel",
        "owner": "CURSOR",
        "port": 2002,
        "local_url": f"http://{HOST}:2002/",
        "health_endpoint": "http://127.0.0.1:2002/login",
        "risk_level": "critical",
        "visible_in_panel": True,
        "notes": "Panel único — :8800 redirige aquí",
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "always_on",
    },
    {
        "service_id": "portal-8800-redirect",
        "name": "Legacy :8800 redirect",
        "project": "ralfia",
        "type": "redirect",
        "owner": "CURSOR",
        "port": 8800,
        "local_url": f"http://{HOST}:8800/",
        "health_endpoint": "http://127.0.0.1:8800/",
        "risk_level": "low",
        "visible_in_panel": False,
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "legacy",
    },
    {
        "service_id": "raphiia-health",
        "name": "Ralphi IA — Status + Editorial",
        "project": "raphiia-openai",
        "type": "api",
        "owner": "CURSOR",
        "port": 8101,
        "local_url": f"http://{HOST}:8101/status",
        "health_endpoint": "http://127.0.0.1:8101/status",
        "risk_level": "high",
        "visible_in_panel": True,
        "preferred_node": "intel",
        "eligible_nodes": ["intel", "amd"],
        "state_mode": "always_on",
    },
    {
        "service_id": "raphiia-mcp",
        "name": "Conector RalfIA MCP",
        "project": "raphiia-openai",
        "type": "mcp",
        "owner": "CODEX",
        "port": 8102,
        "local_url": f"http://{HOST}:8102/mcp",
        "health_endpoint": "http://127.0.0.1:8102/mcp",
        "risk_level": "critical",
        "visible_in_panel": True,
        "web": False,
        "preferred_node": "intel",
        "eligible_nodes": ["intel", "amd"],
        "state_mode": "always_on",
    },
    {
        "service_id": "raphiia-oauth",
        "name": "Ralphi IA OAuth",
        "project": "raphiia-openai",
        "type": "auth",
        "owner": "CODEX",
        "port": 8103,
        "local_url": f"http://{HOST}:8103/health",
        "health_endpoint": "http://127.0.0.1:8103/health",
        "risk_level": "critical",
        "visible_in_panel": True,
        "web": False,
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "intel_only",
    },
    {
        "service_id": "editorial-hub",
        "name": "Editorial LinkedIn Hub",
        "project": "raphiia-openai",
        "type": "editorial",
        "owner": "CURSOR",
        "port": 8101,
        "local_url": f"http://{HOST}:8101/editorial",
        "health_endpoint": "http://127.0.0.1:8101/status",
        "risk_level": "medium",
        "visible_in_panel": True,
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "funding-hub",
        "name": "Funding Hub",
        "project": "hackathon",
        "type": "api",
        "owner": "ANTIGRAVITY",
        "port": 8099,
        "local_url": f"http://{HOST}:8099/api/opportunities",
        "health_endpoint": "http://127.0.0.1:8099/api/opportunities",
        "risk_level": "medium",
        "visible_in_panel": True,
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "swarm-api",
        "name": "Swarm-OS API",
        "project": "innerspark-swarm",
        "type": "api",
        "owner": "CURSOR",
        "port": 8100,
        "local_url": f"http://{HOST}:8100/docs",
        "health_endpoint": "http://127.0.0.1:8100/docs",
        "risk_level": "high",
        "visible_in_panel": True,
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "ollama",
        "name": "Ollama Local",
        "project": "infra",
        "type": "llm",
        "owner": "SYSTEM",
        "port": 11434,
        "local_url": f"http://{HOST}:11434/",
        "health_endpoint": "http://127.0.0.1:11434/api/tags",
        "risk_level": "medium",
        "visible_in_panel": True,
        "preferred_node": "intel",
        "eligible_nodes": ["intel", "amd"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "ralfia-voice-gateway",
        "name": "RalfIA Voice Gateway",
        "project": "raphiia-openai",
        "type": "web",
        "owner": "CURSOR",
        "port": 8200,
        "local_url": f"http://{HOST}:8200/",
        "public_url": "https://voz.pcdoctor.ai",
        "health_endpoint": "http://127.0.0.1:8200/api/voice/health",
        "risk_level": "critical",
        "visible_in_panel": True,
        "systemd_unit": "ralfia-voice-gateway.service",
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "always_on",
    },
    {
        "service_id": "vllm-rocm",
        "name": "vLLM ROCm (AMD)",
        "project": "ralfia-amd",
        "type": "llm",
        "owner": "SYSTEM",
        "port": 8000,
        "local_url": f"http://{HOST}:8000/v1/models",
        "health_endpoint": "http://127.0.0.1:8000/v1/models",
        "risk_level": "high",
        "visible_in_panel": True,
        "web": False,
        "systemd_unit": "ralfia-vllm-docker.service",
        "preferred_node": "amd",
        "eligible_nodes": ["amd"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "ollama-router",
        "name": "Ollama Dual-Node Router",
        "project": "ralfia-amd",
        "type": "gateway",
        "owner": "SYSTEM",
        "port": 11435,
        "local_url": f"http://{HOST}:11435/health",
        "health_endpoint": "http://127.0.0.1:11435/health",
        "risk_level": "high",
        "visible_in_panel": True,
        "web": False,
        "systemd_unit": "ralfia-ollama-router.service",
        "preferred_node": "amd",
        "eligible_nodes": ["intel", "amd"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "comfyui-amd",
        "name": "ComfyUI (AMD ROCm)",
        "project": "ralfia-amd",
        "type": "web",
        "owner": "SYSTEM",
        "port": 8188,
        "local_url": f"http://{HOST}:8188/",
        "health_endpoint": "http://127.0.0.1:8188/",
        "risk_level": "medium",
        "visible_in_panel": True,
        "systemd_unit": "ralfia-comfyui.service",
        "preferred_node": "amd",
        "eligible_nodes": ["amd"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "whisper-amd",
        "name": "Whisper STT (AMD)",
        "project": "ralfia-amd",
        "type": "api",
        "owner": "SYSTEM",
        "port": 9000,
        "local_url": f"http://{HOST}:9000/",
        "health_endpoint": "http://127.0.0.1:9000/",
        "risk_level": "medium",
        "visible_in_panel": True,
        "preferred_node": "amd",
        "eligible_nodes": ["amd"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "smart-quoter",
        "name": "InnerSpark Smart Quoter",
        "project": "innerspark-smart-quoter",
        "type": "web",
        "owner": "ANTIGRAVITY",
        "port": 2026,
        "local_url": f"http://{HOST}:2026/",
        "health_endpoint": "http://127.0.0.1:2026/",
        "risk_level": "medium",
        "visible_in_panel": True,
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "on_demand",
    },
    {
        "service_id": "public-gateway",
        "name": "Public Gateway (ngrok → :5188)",
        "project": "innerspark-swarm",
        "type": "gateway",
        "owner": "SYSTEM",
        "port": 5188,
        "local_url": f"http://{HOST}:5188/",
        "health_endpoint": "http://127.0.0.1:5188/",
        "risk_level": "critical",
        "visible_in_panel": True,
        "systemd_unit": "swarm-public-gateway.service",
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "legacy",
    },
    {
        "service_id": "ngrok-public-tunnel",
        "name": "ngrok HTTPS público",
        "project": "infra",
        "type": "tunnel",
        "owner": "SYSTEM",
        "port": 4040,
        "local_url": f"https://sworn-profusely-alongside.ngrok-free.dev/",
        "health_endpoint": "ngrok://public",
        "risk_level": "critical",
        "visible_in_panel": True,
        "systemd_unit": "swarm-ngrok.service",
        "notes": "ChatGPT MCP, UiPath /uipath, OAuth — alerta WhatsApp si cae",
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "legacy",
    },
    {
        "service_id": "uipath-copilot",
        "name": "UiPath Copilot",
        "project": "uipath-copilot",
        "type": "web",
        "owner": "HACKATHON",
        "port": 8097,
        "local_url": f"http://{HOST}:8097/dashboard",
        "health_endpoint": "http://127.0.0.1:8097/dashboard",
        "risk_level": "high",
        "visible_in_panel": True,
        "systemd_unit": "swarm-uipath-copilot.service",
        "preferred_node": "intel",
        "eligible_nodes": ["intel"],
        "state_mode": "legacy",
    },
]


def _local_node() -> str:
    import os

    role = os.getenv("NODE_ROLE", "auto")
    if role in ("amd", "gpu"):
        return "amd"
    if role in ("primary", "intel"):
        return "intel"
    if RALFIA_LAN_IP == RALFIA_AMD_HOST:
        return "amd"
    return "intel"


def _node_host(node: str) -> str:
    return RALFIA_AMD_HOST if node == "amd" else RALFIA_INTEL_HOST


def _probe_host(svc: dict[str, Any]) -> str:
    """Host efectivo para health check — evita falsos DOWN cruzados entre nodos."""
    preferred = svc.get("preferred_node")
    eligible = svc.get("eligible_nodes") or []
    local = _local_node()
    if preferred:
        return _node_host(str(preferred))
    if eligible:
        if local in eligible:
            return "127.0.0.1"
        return _node_host(str(eligible[0]))
    return "127.0.0.1"


def _rewrite_endpoint(endpoint: str, probe_host: str) -> str:
    if not endpoint.startswith("http"):
        return endpoint
    return re.sub(r"https?://(?:127\.0\.0\.1|localhost)", f"http://{probe_host}", endpoint, count=1)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def upsert_service(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    sid = (payload.get("service_id") or payload.get("id") or "").strip()
    if not sid:
        return {"ok": False, "error": "service_id required"}
    now = _now_iso()
    doc = {k: v for k, v in payload.items() if k != "_id"}
    doc["service_id"] = sid
    doc.setdefault("status", "unknown")
    doc.setdefault("visible_in_panel", True)
    doc["updated_at"] = now
    db[COL_SERVICE_REGISTRY].update_one({"service_id": sid}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    saved = db[COL_SERVICE_REGISTRY].find_one({"service_id": sid})
    return {"ok": True, "service": _serialize(saved) if saved else doc}


def seed_defaults(force: bool = False) -> dict[str, Any]:
    db = mongo_store.get_db()
    n = 0
    for svc in DEFAULT_SERVICES:
        upsert_service(svc)
        n += 1
    before = db[COL_SERVICE_REGISTRY].count_documents({})
    portal_path = PORTAL_SERVICES_JSON
    try:
        raw = json.loads(open(portal_path, encoding="utf-8").read())
        for section, items in raw.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("port"):
                    continue
                sid = str(item.get("id", item.get("name", ""))).strip().replace(" ", "-").lower()
                if not sid:
                    continue
                port = int(item["port"])
                path = item.get("path") or ""
                upsert_service(
                    {
                        "service_id": f"portal-{sid}",
                        "name": item.get("name", sid),
                        "project": item.get("company", section),
                        "type": "web" if item.get("web", True) else "api",
                        "owner": "PORTAL",
                        "port": port,
                        "local_url": f"http://{HOST}:{port}{path}",
                        "health_endpoint": f"http://127.0.0.1:{port}{path or '/'}",
                        "risk_level": "low",
                        "visible_in_panel": item.get("web", True),
                        "notes": item.get("desc", ""),
                        "status": "unknown",
                        "preferred_node": "intel",
                        "eligible_nodes": ["intel"],
                        "state_mode": "on_demand",
                    }
                )
                n += 1
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    after = db[COL_SERVICE_REGISTRY].count_documents({})
    return {"ok": True, "seeded": n, "total": after, "added": max(0, after - before)}


def list_services(
    *,
    visible_only: bool = True,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if visible_only:
        filt["visible_in_panel"] = True
    if status:
        filt["status"] = status
    cursor = db[COL_SERVICE_REGISTRY].find(filt).sort("risk_level", 1).limit(max(1, min(limit, 200)))
    items = [_serialize(d) for d in cursor]
    return {"ok": True, "count": len(items), "services": items}


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_service(svc: dict[str, Any]) -> dict[str, Any]:
    endpoint = (svc.get("health_endpoint") or svc.get("local_url") or "").strip()
    state_mode = svc.get("state_mode") or "always_on"
    probe_host = _probe_host(svc)
    endpoint = _rewrite_endpoint(endpoint, probe_host)
    if endpoint == "ngrok://public":
        from raphiia_openai import ngrok_watch

        checked = ngrok_watch.check_ngrok_tunnel()
        now = _now_iso()
        patch = {
            "status": checked.get("status", "unknown"),
            "last_check": now,
            "last_error": checked.get("last_error", ""),
        }
        db = mongo_store.get_db()
        svc_id = svc.get("service_id") or svc.get("id")
        if svc_id:
            db[COL_SERVICE_REGISTRY].update_one({"service_id": svc_id}, {"$set": patch})
        return {**svc, **patch}

    now = _now_iso()
    port = int(svc.get("port") or 0)
    status = "unknown"
    last_error = ""

    if endpoint.startswith("http"):
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "RalfIA-Watchdog/1.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                code = resp.status
                if 200 <= code < 400:
                    status = "up"
                elif code in (401, 403, 406):
                    status = "unauthorized_alive"
                else:
                    status = "degraded"
                    last_error = f"HTTP {code}"
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 406):
                status = "unauthorized_alive"
            else:
                status = "down"
                last_error = f"HTTP {exc.code}"
        except TimeoutError:
            status = "timeout"
            last_error = "timeout"
        except (urllib.error.URLError, OSError) as exc:
            status = "down"
            last_error = str(exc)[:200]
            if state_mode == "on_demand":
                status = "on_demand"
                last_error = f"on_demand: {last_error}"
    elif port:
        host = probe_host if probe_host != "127.0.0.1" else "127.0.0.1"
        status = "up" if _tcp_open(host, port) else "down"
        if status == "down":
            last_error = f"port {port} closed on {host}"
            if state_mode == "on_demand":
                status = "on_demand"
                last_error = f"on_demand: port {port} closed on {host}"
    else:
        last_error = "no endpoint"

    patch = {
        "status": status,
        "last_check": now,
        "last_error": last_error,
        "probe_host": probe_host,
    }
    db = mongo_store.get_db()
    svc_id = svc.get("service_id") or svc.get("id")
    if not svc_id:
        return {**svc, **patch}
    db[COL_SERVICE_REGISTRY].update_one(
        {"$or": [{"service_id": svc_id}, {"id": svc_id}]},
        {"$set": patch}
    )
    return {**svc, **patch}


def maybe_run_stale_checks(*, max_age_sec: int = 240) -> bool:
    """Ejecuta run_all_checks si el registry critical está desactualizado (panel/MCP)."""
    from datetime import datetime, timezone

    seed_defaults(force=False)
    listed = list_services(visible_only=False, limit=200)
    now = datetime.now(timezone.utc)
    stale = False
    for svc in listed.get("services", []):
        if svc.get("risk_level") not in ("critical", "high") and not str(svc.get("service_id", "")).startswith(
            ("ngrok-", "public-", "uipath-", "raphiia-", "portal-")
        ):
            continue
        lc = svc.get("last_check")
        if not lc or svc.get("status") in ("unknown", "pending_review"):
            stale = True
            break
        try:
            ts = datetime.fromisoformat(str(lc).replace("Z", "+00:00"))
            if (now - ts).total_seconds() > max_age_sec:
                stale = True
                break
        except (TypeError, ValueError):
            stale = True
            break
    if stale:
        run_all_checks()
    return stale


def archive_stale_discovered(*, dry_run: bool = True) -> dict[str, Any]:
    """Archiva entradas discovered-* cuyo puerto ya no escucha en ningún nodo."""
    db = mongo_store.get_db()
    listening = {row["port"] for row in _scan_listening_ports()}
    cursor = db[COL_SERVICE_REGISTRY].find({"service_id": {"$regex": r"^discovered-"}})
    archived: list[str] = []
    kept: list[str] = []
    for doc in cursor:
        sid = str(doc.get("service_id") or "")
        port = int(doc.get("port") or 0)
        if port in listening:
            kept.append(sid)
            continue
        archived.append(sid)
        if not dry_run:
            db[COL_SERVICE_REGISTRY].update_one(
                {"service_id": sid},
                {
                    "$set": {
                        "status": "archived",
                        "visible_in_panel": False,
                        "updated_at": _now_iso(),
                        "notes": (doc.get("notes") or "")[:180] + " [archived stale]",
                    }
                },
            )
    return {"ok": True, "dry_run": dry_run, "archived_count": len(archived), "archived": archived[:50], "kept_count": len(kept)}


def run_all_checks() -> dict[str, Any]:
    seed_defaults(force=False)
    archive_stale_discovered(dry_run=False)
    listed = list_services(visible_only=False, limit=200)
    results = []
    summary: dict[str, int] = {}
    for svc in listed.get("services", []):
        checked = check_service(svc)
        results.append(
            {
                "service_id": checked.get("service_id"),
                "name": checked.get("name"),
                "status": checked.get("status"),
                "port": checked.get("port"),
                "last_error": checked.get("last_error", ""),
            }
        )
        st = checked.get("status", "unknown")
        summary[st] = summary.get(st, 0) + 1
    mongo_store.log_coordination(
        agent="WATCHDOG",
        summary=f"Service checks: {summary}",
        event="service_watchdog",
        project="ralfia-ops",
        metadata={"summary": summary, "count": len(results)},
    )
    discovery = discover_new_services()
    return {
        "ok": True,
        "summary": summary,
        "results": results,
        "checked_at": _now_iso(),
        "discovery": discovery,
    }


# Puertos internos / infra — no proponer como servicio web nuevo
_SKIP_PORTS = frozenset({22, 25, 53, 111, 631, 3306, 5432, 6379, 27017, 6333})


def _scan_listening_ports(min_port: int = 3000, max_port: int = 9999) -> list[dict[str, Any]]:
    try:
        ss = subprocess.check_output(["ss", "-tlnp"], text=True, errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    found: dict[int, str] = {}
    for line in ss.splitlines():
        if "LISTEN" not in line:
            continue
        m = re.search(r":(\d+)\s", line)
        if not m:
            continue
        port = int(m.group(1))
        if port < min_port or port > max_port or port in _SKIP_PORTS:
            continue
        pid_m = re.search(r'pid=(\d+)', line)
        cmd = ""
        if pid_m:
            try:
                cmd = subprocess.check_output(
                    ["ps", "-p", pid_m.group(1), "-o", "args="],
                    text=True,
                    errors="replace",
                ).strip()[:200]
            except (OSError, subprocess.CalledProcessError):
                pass
        found[port] = cmd
    return [{"port": p, "cmd": c} for p, c in sorted(found.items())]


def discover_new_services() -> dict[str, Any]:
    """Detecta puertos web nuevos → pending_review en registry."""
    db = mongo_store.get_db()
    known_ports = {
        int(d["port"])
        for d in db[COL_SERVICE_REGISTRY].find({"port": {"$exists": True, "$gt": 0}}, {"port": 1})
        if d.get("port")
    }
    listening = _scan_listening_ports()
    proposed: list[dict[str, Any]] = []
    for row in listening:
        port = row["port"]
        if port in known_ports:
            continue
        sid = f"discovered-{port}"
        svc = {
            "service_id": sid,
            "name": f"Discovered :{port}",
            "project": "unknown",
            "type": "web",
            "owner": "PENDING",
            "port": port,
            "local_url": f"http://{HOST}:{port}/",
            "health_endpoint": f"http://127.0.0.1:{port}/",
            "status": "pending_review",
            "risk_level": "low",
            "visible_in_panel": False,
            "notes": row.get("cmd", "")[:200],
            "discovery_source": "ss_tlnp",
        }
        upsert_service(svc)
        proposed.append({"service_id": sid, "port": port, "cmd": row.get("cmd", "")[:80]})
    if proposed:
        mongo_store.log_coordination(
            agent="WATCHDOG",
            summary=f"Discovery: {len(proposed)} puertos pending_review",
            event="service_discovery",
            project="ralfia-ops",
            metadata={"proposed": proposed[:20]},
        )
    return {"ok": True, "proposed_count": len(proposed), "proposed": proposed}


def approve_discovered_service(service_id: str, name: str = "", owner: str = "RAFAEL") -> dict[str, Any]:
    db = mongo_store.get_db()
    doc = db[COL_SERVICE_REGISTRY].find_one({"service_id": service_id})
    if not doc:
        return {"ok": False, "error": "not found"}
    patch = {
        "status": "unknown",
        "visible_in_panel": True,
        "owner": owner,
        "updated_at": _now_iso(),
    }
    if name.strip():
        patch["name"] = name.strip()
    db[COL_SERVICE_REGISTRY].update_one({"service_id": service_id}, {"$set": patch})
    checked = check_service({**doc, **patch})
    return {"ok": True, "service": checked}
