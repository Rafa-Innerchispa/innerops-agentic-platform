"""Backend compartido: portal Control Center + ops RalfIA (Mongo registry, recursos, OAuth)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from raphiia_openai import mongo_store, service_registry
from raphiia_openai.mcp_catalog import tool_catalog
from raphiia_openai.mcp_diagnostics import mcp_version
from raphiia_openai.settings import (
    COL_OAUTH_CLIENTS,
    COL_OAUTH_TOKENS,
    MONGO_URI,
    OPS_PANEL_PUBLIC_URL,
    PORTAL_SERVICES_JSON,
    RALFIA_LAN_IP,
)

HOST = RALFIA_LAN_IP
INTEL_HOST = "192.168.1.4"
AMD_HOST = "192.168.1.5"
RALFIA_PANEL_VERSION = "3.1.0"
VERSION_HISTORY_PATH = Path(
    os.getenv(
        "RALFIA_VERSION_HISTORY",
        "/home/rlopez/projects/ralfiia-amd-standby/docs/VERSION_HISTORY.md",
    )
)


def _tcp_open(port: int, host: str = "127.0.0.1", timeout: float = 0.45) -> bool:
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _listen_map() -> dict[int, dict[str, Any]]:
    """Puertos en escucha — deduplica IPv4/IPv6 (mismo PID no es conflicto)."""
    listening: dict[int, dict[str, Any]] = {}
    try:
        ss = subprocess.check_output(["ss", "-tlnp"], text=True, errors="replace")
        for line in ss.splitlines():
            if "LISTEN" not in line:
                continue
            m = re.search(r":(\d+)\s", line)
            if not m:
                continue
            port = int(m.group(1))
            pid_m = re.search(r"pid=(\d+)", line)
            pid = pid_m.group(1) if pid_m else ""
            proc = ""
            if pid:
                try:
                    proc = subprocess.check_output(
                        ["ps", "-p", pid, "-o", "args="],
                        text=True,
                        errors="replace",
                    ).strip()[:120]
                except (OSError, subprocess.CalledProcessError):
                    proc = line.strip()[:80]
            else:
                proc = line.strip()[:80]
            bucket = listening.setdefault(port, {"pids": set(), "procs": []})
            if pid:
                if pid not in bucket["pids"]:
                    bucket["pids"].add(pid)
                    bucket["procs"].append(proc or f"pid:{pid}")
            elif proc and proc not in bucket["procs"]:
                bucket["procs"].append(proc)
    except (OSError, subprocess.CalledProcessError):
        pass
    return listening


def _port_conflict(port: int, bucket: dict[str, Any], registered: list[dict]) -> bool:
    """Conflicto real = 2+ procesos distintos (PID) en el mismo puerto."""
    pids = bucket.get("pids") or set()
    if len(pids) > 1:
        return True
    if len(registered) > 1 and not all(r.get("shared_port") for r in registered):
        return True
    return False


# Puertos operativos RalfIA / PC Doctor (ocultar ruido Java/Mongo interno en vista default)
OPERATIONAL_PORTS = frozenset({
    2002, 3000, 3001, 5173, 5188, 5678, 6333, 8000, 8081, 8082, 8090, 8091, 8095, 8096, 8097, 8098, 8099,
    8100, 8101, 8102, 8103, 8188, 8200, 8800, 9000, 9001, 11434, 11435,
})

SYSTEMD_UNITS = [
    {"unit": "ralfia-portal.service", "label": "Panel :2002"},
    {"unit": "ralfia-mcp.service", "label": "MCP :8102"},
    {"unit": "ralfia-app.service", "label": "Health :8101"},
    {"unit": "ralfia-auth.service", "label": "OAuth :8103"},
    {"unit": "ralfia-voice-gateway.service", "label": "Voice :8200"},
    {"unit": "ralfia-vllm-docker.service", "label": "vLLM Docker :8000"},
    {"unit": "ralfia-ollama-router.service", "label": "Ollama router :11435"},
    {"unit": "ralfia-cloudflared-voice.service", "label": "Cloudflare voz.pcdoctor.ai"},
    {"unit": "ralfia-comfyui.service", "label": "ComfyUI :8188"},
    {"unit": "ralfia-coordination-daemon.service", "label": "AG-25 coordinación"},
    {"unit": "ralfia-dual-node-monitor.service", "label": "Monitor dual-nodo"},
    {"unit": "ralfia-editorial-worker.service", "label": "Worker editorial"},
    {"unit": "ralf-portal.service", "label": "Portal legacy (system)"},
]


def _http_probe(url: str, timeout: float = 4.0) -> str:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RalfIA-Panel/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.status
            if 200 <= code < 400:
                return "up"
            if code in (401, 403):
                return "unauthorized_alive"
            return "degraded"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 406):
            return "unauthorized_alive"
        if exc.code in (301, 302, 307, 308):
            return "up"
        return "down"
    except Exception:
        return "down"


def services_health_enriched(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estado unificado por puerto e id de servicio (TCP + HTTP opcional)."""
    cfg = cfg or _load_services_json()
    listen = _listen_map()
    by_port: dict[int, list[str]] = {}
    services_out: dict[str, str] = {}
    ports_out: dict[str, str] = {}

    for item in _service_items(cfg):
        sid = str(item.get("id", ""))
        port = int(item.get("port") or 0)
        if not port:
            continue
        by_port.setdefault(port, []).append(sid)
        tcp = _tcp_open(port)
        st = "down"
        if tcp:
            st = "up"
            path = item.get("path") or ""
            if item.get("web") is not False and path:
                url = f"http://127.0.0.1:{port}{path if str(path).startswith('/') else '/' + path}"
                http_st = _http_probe(url)
                if http_st in ("up", "unauthorized_alive"):
                    st = http_st if http_st == "unauthorized_alive" else "up"
                elif http_st == "degraded":
                    st = "degraded"
        services_out[sid] = st
        ports_out[str(port)] = st

    for port, bucket in listen.items():
        key = str(port)
        if key not in ports_out and _tcp_open(port):
            ports_out[key] = "up"

    return {"ports": ports_out, "services": services_out, "by_port": {str(k): v for k, v in by_port.items()}}


def systemd_status() -> dict[str, Any]:
    units = []
    for spec in SYSTEMD_UNITS:
        unit = spec["unit"]
        state = "unknown"
        scope = "user"
        for cmd in (
            ["systemctl", "--user", "is-active", unit],
            ["systemctl", "is-active", unit],
        ):
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False)
                out = (proc.stdout or proc.stderr or "").strip()
                if out and out != "inactive":
                    state = out
                    scope = "user" if "--user" in cmd else "system"
                    break
            except (OSError, subprocess.CalledProcessError):
                continue
        units.append({"unit": unit, "label": spec["label"], "state": state, "scope": scope, "ok": state == "active"})
    return {"ok": True, "units": units}


def system_resources() -> dict[str, Any]:
    cpu_count = 1
    load1 = 0.0
    try:
        cpu_count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpu_count = os.cpu_count() or 1
    try:
        load1 = round(float(open("/proc/loadavg").read().split()[0]), 2)
    except OSError:
        pass
    load_pct = min(100, round((load1 / max(cpu_count, 1)) * 100, 1))
    mem = {"used_gb": "-", "used_pct": 0}
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        phys = os.sysconf("SC_PHYS_PAGES")
        avail = os.sysconf("SC_AVPHYS_PAGES")
        total_gb = round(page * phys / (1024**3), 1)
        used_gb = round(page * (phys - avail) / (1024**3), 1)
        mem = {"used_gb": used_gb, "total_gb": total_gb, "used_pct": round(100 * used_gb / max(total_gb, 0.1), 1)}
    except Exception:
        pass
    disk = {"used_gb": "-", "free_gb": "-", "used_pct": 0}
    try:
        du = shutil.disk_usage("/")
        used = round(du.used / (1024**3), 1)
        free = round(du.free / (1024**3), 1)
        disk = {"used_gb": used, "free_gb": free, "used_pct": round(100 * du.used / max(du.total, 1), 1)}
    except OSError:
        pass
    docker = {"running": 0}
    try:
        out = subprocess.check_output(["docker", "ps", "-q"], text=True, stderr=subprocess.DEVNULL, timeout=5)
        docker = {"running": len([l for l in out.splitlines() if l.strip()])}
    except Exception:
        pass
    return {"ok": True, "cpu": {"load1": load1, "count": cpu_count, "load1_pct": load_pct}, "memory": mem, "disk": disk, "docker": docker}


def _load_services_json() -> dict[str, Any]:
    path = Path(PORTAL_SERVICES_JSON)
    if not path.is_file():
        return {"featured": [], "services": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _service_items(cfg: dict[str, Any]):
    for item in cfg.get("featured", []):
        yield item
    for item in cfg.get("services", []):
        yield item


def ports_registry(*, operational_only: bool = True) -> dict[str, Any]:
    """Registro unificado: services.json + Mongo + ss (sin falsos conflictos IPv4/IPv6)."""
    service_registry.seed_defaults(force=False)
    cfg = _load_services_json()
    by_port: dict[int, list[dict[str, Any]]] = {}
    registered_ports: set[int] = set()
    for item in _service_items(cfg):
        port = int(item.get("port") or 0)
        if port:
            registered_ports.add(port)
            by_port.setdefault(port, []).append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "path": item.get("path", ""),
                    "shared_port": item.get("shared_port"),
                }
            )
    mongo_svcs = service_registry.list_services(visible_only=False, limit=300).get("services", [])
    mongo_by_port: dict[int, dict] = {}
    for s in mongo_svcs:
        p = int(s.get("port") or 0)
        if p:
            mongo_by_port[p] = s

    listening = _listen_map()
    health = services_health_enriched(cfg)

    if operational_only:
        port_set = registered_ports | OPERATIONAL_PORTS
    else:
        port_set = set(listening) | registered_ports | set(mongo_by_port)

    rows = []
    summary = {"conflicts": 0, "unregistered": 0, "declared_down": 0, "ok": 0, "shared": 0}
    for port in sorted(port_set):
        registered = by_port.get(port, [])
        mongo_row = mongo_by_port.get(port)
        if mongo_row and not registered:
            registered = [{"id": mongo_row.get("service_id"), "name": mongo_row.get("name")}]
        bucket = listening.get(port, {"pids": set(), "procs": []})
        procs = bucket.get("procs") or []
        tcp_up = _tcp_open(port)
        if not procs and tcp_up:
            procs = [f"tcp:{port} abierto"]
        port_health = health.get("ports", {}).get(str(port), "")
        http_ok = port_health in ("up", "unauthorized_alive")
        is_shared = len(registered) > 1 and all(r.get("shared_port") for r in registered)
        is_conflict = _port_conflict(port, bucket, registered)

        if is_conflict:
            status = "conflict"
            summary["conflicts"] += 1
        elif registered and (procs or http_ok or tcp_up):
            status = "ok" if not is_shared else "shared"
            summary["ok" if not is_shared else "shared"] += 1
        elif registered and not tcp_up:
            status = "declared_down"
            summary["declared_down"] += 1
        elif procs and not registered:
            status = "unregistered"
            summary["unregistered"] += 1
        elif tcp_up:
            status = "ok"
            summary["ok"] += 1
        else:
            status = "unknown"

        rows.append(
            {
                "port": port,
                "status": status,
                "services": registered,
                "listening": {"processes": procs, "pid_count": len(bucket.get("pids") or [])},
                "mongo_status": (mongo_row or {}).get("status"),
                "tcp_up": tcp_up,
                "http_ok": http_ok,
                "health": port_health or status,
                "shared_port": is_shared,
            }
        )
    return {
        "ok": True,
        "ports": rows,
        "summary": summary,
        "panel_url": OPS_PANEL_PUBLIC_URL,
        "operational_only": operational_only,
    }


def oauth_users_payload() -> dict[str, Any]:
    db = mongo_store.get_db()
    users = []
    try:
        hack = MongoClient(MONGO_URI)["hackathon_autopilot"]
        for u in hack.users.find({}, {"username": 1, "role": 1, "oauth_enabled": 1, "oauth_scopes": 1}):
            users.append(
                {
                    "username": u.get("username"),
                    "role": u.get("role", "user"),
                    "oauth_enabled": u.get("oauth_enabled", False),
                    "oauth_scopes": u.get("oauth_scopes", []),
                }
            )
    except Exception:
        users = []
    active = db[COL_OAUTH_TOKENS].count_documents({})
    return {"ok": True, "users": users, "active_tokens": active}


def oauth_clients_payload() -> dict[str, Any]:
    db = mongo_store.get_db()
    clients = [
        {
            "client_id": c.get("client_id"),
            "client_name": c.get("client_name", c.get("client_id")),
            "scope": c.get("scope", ""),
            "redirect_uris": c.get("redirect_uris", []),
        }
        for c in db[COL_OAUTH_CLIENTS].find({}, {"client_id": 1, "client_name": 1, "scope": 1, "redirect_uris": 1})
    ]
    return {"ok": True, "clients": clients}


def revoke_all_oauth_tokens() -> dict[str, Any]:
    db = mongo_store.get_db()
    res = db[COL_OAUTH_TOKENS].delete_many({})
    return {"ok": True, "revoked": res.deleted_count}


def revoke_user_tokens(username: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    res = db[COL_OAUTH_TOKENS].delete_many({"username": username})
    return {"ok": True, "revoked": res.deleted_count, "username": username}


def ops_overview_payload() -> dict[str, Any]:
    from raphiia_openai import handoff_detector, orchestration_store

    mcp = mcp_version()
    service_registry.seed_defaults(force=False)
    services = service_registry.list_services(visible_only=True, limit=80)
    return {
        "ok": True,
        "catalog_version": tool_catalog.MCP_VERSION,
        "mcp": mcp,
        "panel_url": OPS_PANEL_PUBLIC_URL,
        "services_count": services.get("count", 0),
        "tasks": orchestration_store.list_tasks(limit=10),
        "missing_handoffs": handoff_detector.detect_missing_handoff(hours=72),
        "pending_review": service_registry.list_services(visible_only=False, status="pending_review"),
        "systemd": systemd_status(),
    }


def enrich_portal_overview(base: dict[str, Any]) -> dict[str, Any]:
    mcp = mcp_version()
    node = detect_node()
    base["mcp"] = {
        "catalog_version": tool_catalog.MCP_VERSION,
        "bridge_version": mcp.get("bridge_version"),
        "catalog_tool_count": mcp.get("catalog_tool_count"),
        "runtime_tool_count": mcp.get("runtime_tool_count"),
    }
    base["panel_port"] = 2002
    base["panel_url"] = OPS_PANEL_PUBLIC_URL
    base["legacy_port"] = 8800
    base["legacy_redirect"] = True
    base["editorial_url"] = f"http://{HOST}:8101/editorial"
    base["node"] = node
    base["version"] = RALFIA_PANEL_VERSION
    return base


def detect_node() -> dict[str, Any]:
    """Auto-detect Intel vs AMD from RALFIA_LAN_IP / hostname."""
    host = (RALFIA_LAN_IP or "").strip()
    hostname = os.uname().nodename.lower()
    is_amd = (
        host == AMD_HOST
        or host.endswith(".5")
        or "amd" in hostname
        or os.getenv("NODE_ROLE", "").lower() in {"amd", "gpu_worker", "standby"}
    )
    if is_amd:
        return {
            "node_id": "amd",
            "label": "RalfIA AMD",
            "host": host or AMD_HOST,
            "gpu": "AMD R9700 32GB",
            "version": RALFIA_PANEL_VERSION,
            "peer": {
                "node_id": "intel",
                "label": "RalfIA Intel",
                "host": INTEL_HOST,
                "panel_url": f"http://{INTEL_HOST}:2002/",
            },
        }
    return {
        "node_id": "intel",
        "label": "RalfIA Intel",
        "host": host or INTEL_HOST,
        "gpu": "NVIDIA RTX 3060 12GB",
        "version": RALFIA_PANEL_VERSION,
        "peer": {
            "node_id": "amd",
            "label": "RalfIA AMD",
            "host": AMD_HOST,
            "panel_url": f"http://{AMD_HOST}:2002/",
        },
    }


def _run_rocm_smi(*args: str) -> tuple[bool, str]:
    try:
        out = subprocess.check_output(["rocm-smi", *args], text=True, stderr=subprocess.STDOUT, timeout=12)
        return True, out
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        err = getattr(exc, "output", None) or str(exc)
        return False, str(err)[:500]


def _parse_rocm_json(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_rocm_text(raw: str) -> dict[str, Any]:
    """Fallback parser for rocm-smi text output."""
    card = "AMD GPU"
    vram_used_mb = 0
    vram_total_mb = 0
    gpu_use_pct = 0
    for line in raw.splitlines():
        low = line.lower()
        if "card series" in low or "card model" in low:
            card = line.split(":", 1)[-1].strip() or card
        if "vram total" in low:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|MiB|GiB)", line, re.I)
            if m:
                val = float(m.group(1))
                vram_total_mb = int(val * 1024) if m.group(2).upper().startswith("G") else int(val)
        if "vram used" in low:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|MiB|GiB)", line, re.I)
            if m:
                val = float(m.group(1))
                vram_used_mb = int(val * 1024) if m.group(2).upper().startswith("G") else int(val)
        if "gpu use" in low or "gpu activity" in low:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
            if m:
                gpu_use_pct = float(m.group(1))
    return {
        "card": card,
        "vram_used_mb": vram_used_mb,
        "vram_total_mb": vram_total_mb,
        "gpu_use_pct": gpu_use_pct,
    }


def gpu_resources() -> dict[str, Any]:
    """ROCm/GPU stats via rocm-smi — AMD node only."""
    node = detect_node()
    if node["node_id"] != "amd":
        return {
            "ok": True,
            "available": False,
            "reason": "no_amd_gpu",
            "node_id": node["node_id"],
            "hint": "GPU panel solo en nodo AMD (.5)",
        }

    ok_json, raw_json = _run_rocm_smi("--showmeminfo", "vram", "--showuse", "--json")
    card = "AMD R9700"
    vram_used_mb = 0
    vram_total_mb = 32768
    gpu_use_pct = 0.0
    temperature_c: int | None = None
    processes: list[dict[str, Any]] = []

    parsed = _parse_rocm_json(raw_json) if ok_json else None
    if parsed:
        for key, info in parsed.items():
            if not isinstance(info, dict):
                continue
            card = str(info.get("Card series") or info.get("Card model") or card)
            mem = info.get("VRAM Total Memory (B)") or info.get("VRAM Total Memory (MiB)")
            used = info.get("VRAM Total Used Memory (B)") or info.get("VRAM Total Used Memory (MiB)")
            if mem is not None:
                vram_total_mb = int(int(mem) / (1024 * 1024)) if int(mem) > 10_000_000 else int(mem)
            if used is not None:
                vram_used_mb = int(int(used) / (1024 * 1024)) if int(used) > 10_000_000 else int(used)
            use = info.get("GPU use (%)") or info.get("GPU Activity")
            if use is not None:
                gpu_use_pct = float(str(use).replace("%", "").strip() or 0)
            temp = info.get("Temperature (Sensor edge) (C)") or info.get("Temperature (C)")
            if temp is not None:
                try:
                    temperature_c = int(float(temp))
                except (TypeError, ValueError):
                    pass
    else:
        ok_txt, raw_txt = _run_rocm_smi("--showmeminfo", "vram", "--showuse")
        if ok_txt:
            fb = _parse_rocm_text(raw_txt)
            card = fb["card"]
            vram_used_mb = fb["vram_used_mb"]
            vram_total_mb = fb["vram_total_mb"] or vram_total_mb
            gpu_use_pct = fb["gpu_use_pct"]
        else:
            return {"ok": False, "available": False, "error": raw_txt[:300], "node_id": "amd"}

    ok_pid, raw_pid = _run_rocm_smi("--showpidgpus")
    if ok_pid:
        for line in raw_pid.splitlines():
            m = re.match(r"\s*(\d+)\s+\S+\s+(\d+)\s+(\S+)", line)
            if m:
                processes.append({"pid": int(m.group(1)), "gpu": m.group(3), "cmd": ""})
            elif re.match(r"^\s*\d+", line):
                parts = line.split()
                if len(parts) >= 2:
                    processes.append({"pid": int(parts[0]), "gpu": parts[-1], "cmd": " ".join(parts[1:-1])[:80]})

    try:
        ps_out = subprocess.check_output(["ps", "-eo", "pid,args"], text=True, errors="replace", timeout=5)
        ps_map = {}
        for pline in ps_out.splitlines()[1:]:
            pm = re.match(r"\s*(\d+)\s+(.*)", pline)
            if pm:
                ps_map[int(pm.group(1))] = pm.group(2)[:120]
        for proc in processes:
            proc["cmd"] = ps_map.get(proc["pid"], proc.get("cmd") or "?")
    except (OSError, subprocess.CalledProcessError):
        pass

    vram_free_mb = max(0, vram_total_mb - vram_used_mb)
    used_pct = round(100 * vram_used_mb / max(vram_total_mb, 1), 1)
    saturated = used_pct >= 92 or vram_free_mb < 1500
    health = "ok"
    if saturated:
        health = "saturated"
    elif used_pct >= 75:
        health = "high"

    return {
        "ok": True,
        "available": True,
        "node_id": "amd",
        "card": card,
        "vram_used_mb": vram_used_mb,
        "vram_total_mb": vram_total_mb,
        "vram_free_mb": vram_free_mb,
        "vram_used_pct": used_pct,
        "gpu_use_pct": gpu_use_pct,
        "temperature_c": temperature_c,
        "health": health,
        "saturated": saturated,
        "processes": processes[:12],
        "rocm_available": shutil.which("rocm-smi") is not None,
    }


def free_vram(*, include_comfyui: bool = False) -> dict[str, Any]:
    """
    Libera VRAM de forma segura en AMD:
    1. Reinicia ralfia-vllm-docker.service (libera ~14-20 GB del modelo Qwen AWQ)
    2. Opcional: reinicia ralfia-comfyui.service si include_comfyui=true
    No mata procesos arbitrarios — solo unidades systemd permitidas.
    """
    node = detect_node()
    if node["node_id"] != "amd":
        return {"ok": False, "error": "solo_disponible_en_amd", "node_id": node["node_id"]}

    from raphiia_openai import service_control

    actions: list[dict[str, Any]] = []
    before = gpu_resources()

    vllm = service_control.restart_unit("ralfia-vllm-docker.service", scope="user", verify=False)
    actions.append({
        "action": "restart",
        "unit": "ralfia-vllm-docker.service",
        "scope": "user",
        "ok": vllm.get("ok"),
        "note": "Libera VRAM del contenedor vLLM (Qwen2.5-14B AWQ). Tarda ~30-90s en volver.",
        **vllm,
    })

    if include_comfyui:
        comfy = service_control.restart_unit("ralfia-comfyui.service", scope="user", verify=False)
        actions.append({
            "action": "restart",
            "unit": "ralfia-comfyui.service",
            "scope": "user",
            "ok": comfy.get("ok"),
            "note": "Detiene generación de imagen en ComfyUI.",
            **comfy,
        })

    after = gpu_resources()
    return {
        "ok": all(a.get("ok") for a in actions),
        "actions": actions,
        "before": {
            "vram_used_mb": before.get("vram_used_mb"),
            "vram_used_pct": before.get("vram_used_pct"),
        },
        "after": {
            "vram_used_mb": after.get("vram_used_mb"),
            "vram_used_pct": after.get("vram_used_pct"),
        },
        "documentation": (
            "El botón reinicia ralfia-vllm-docker (principal consumidor de VRAM). "
            "Opcionalmente ComfyUI. No ejecuta kill -9 sobre PIDs desconocidos."
        ),
    }


def version_info() -> dict[str, Any]:
    """Versión del panel + changelog markdown."""
    changelog_md = ""
    changelog_path = str(VERSION_HISTORY_PATH)
    if VERSION_HISTORY_PATH.is_file():
        changelog_md = VERSION_HISTORY_PATH.read_text(encoding="utf-8")
    return {
        "ok": True,
        "version": RALFIA_PANEL_VERSION,
        "node": detect_node(),
        "changelog_md": changelog_md,
        "changelog_path": changelog_path,
    }


def vllm_models_info() -> dict[str, Any]:
    """Modelo cargado en vLLM OpenAI API (:8000/v1/models)."""
    url = os.getenv("VLLM_URL", "http://127.0.0.1:8000").rstrip("/") + "/v1/models"
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "RalfIA-Panel/3.1"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode())
        models = data.get("data") or data.get("models") or []
        ids = [str(m.get("id") or m) for m in models if m]
        loaded = ids[0] if ids else None
        return {"ok": True, "url": url, "models": ids, "loaded_model": loaded, "count": len(ids)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)[:300], "models": [], "loaded_model": None}


def unified_services_list(*, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fusiona services.json + Mongo registry + puertos ss (dedupe por puerto)."""
    service_registry.seed_defaults(force=False)
    cfg = cfg or _load_services_json()
    health = services_health_enriched(cfg)
    listen = _listen_map()
    by_port: dict[int, dict[str, Any]] = {}

    def _upsert(port: int, row: dict[str, Any]) -> None:
        if not port:
            return
        existing = by_port.get(port)
        if not existing:
            by_port[port] = row
            return
        for key in ("id", "name", "desc", "path", "node", "section", "unit", "container", "source"):
            if not existing.get(key) and row.get(key):
                existing[key] = row[key]
        if row.get("id") and existing.get("id") and existing["id"] != row["id"]:
            existing["aliases"] = list({*(existing.get("aliases") or []), existing["id"], row["id"]})

    for item in _service_items(cfg):
        port = int(item.get("port") or 0)
        st = health.get("services", {}).get(str(item.get("id")), "") or health.get("ports", {}).get(str(port), "")
        _upsert(
            port,
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "desc": item.get("desc") or "",
                "port": port,
                "path": item.get("path") or "",
                "node": item.get("node") or "both",
                "section": item.get("section") or "",
                "status": st or ("up" if _tcp_open(port) else "down"),
                "source": "services.json",
                "web": item.get("web", True),
            },
        )

    for s in service_registry.list_services(visible_only=False, limit=400).get("services", []):
        port = int(s.get("port") or 0)
        st = s.get("status") or health.get("ports", {}).get(str(port), "")
        _upsert(
            port,
            {
                "id": s.get("service_id"),
                "name": s.get("name"),
                "desc": s.get("description") or "",
                "port": port,
                "path": s.get("path") or "",
                "node": s.get("node") or "both",
                "status": st or ("up" if _tcp_open(port) else "down"),
                "source": "mongo",
                "unit": s.get("systemd_unit") or "",
            },
        )

    for port, bucket in listen.items():
        procs = bucket.get("procs") or []
        if port in by_port:
            by_port[port]["processes"] = procs
            by_port[port]["listening"] = True
            continue
        _upsert(
            port,
            {
                "id": f"port-{port}",
                "name": procs[0][:80] if procs else f"Puerto {port}",
                "desc": "Detectado en escucha (ss)",
                "port": port,
                "path": "",
                "node": detect_node().get("node_id", "both"),
                "status": "up",
                "source": "ss",
                "processes": procs,
                "listening": True,
            },
        )

    rows = sorted(by_port.values(), key=lambda r: (r.get("name") or "", r.get("port") or 0))
    return {"ok": True, "services": rows, "count": len(rows)}


def processes_overview() -> dict[str, Any]:
    """Todos los puertos en escucha + unidades systemd RalfIA."""
    listen = _listen_map()
    ports = []
    for port in sorted(listen):
        bucket = listen[port]
        ports.append(
            {
                "port": port,
                "processes": bucket.get("procs") or [],
                "pid_count": len(bucket.get("pids") or []),
                "tcp_up": _tcp_open(port),
            }
        )
    systemd = systemd_status()
    unit_map = {u["unit"]: u for u in systemd.get("units", [])}
    enriched_units = []
    for spec in SYSTEMD_UNITS:
        unit = spec["unit"]
        info = unit_map.get(unit, {"unit": unit, "state": "unknown", "scope": "user", "ok": False})
        label = spec["label"]
        port_m = re.search(r":(\d+)", label)
        port_hint = int(port_m.group(1)) if port_m else None
        enriched_units.append(
            {
                **info,
                "label": label,
                "port_hint": port_hint,
                "port_open": _tcp_open(port_hint) if port_hint else None,
            }
        )
    return {
        "ok": True,
        "listening_ports": ports,
        "listening_count": len(ports),
        "systemd_units": enriched_units,
        "systemd_active": sum(1 for u in enriched_units if u.get("ok")),
    }
