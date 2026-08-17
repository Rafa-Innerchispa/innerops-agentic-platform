"""Vista unificada Intel (.4) + AMD (.5) — panel fleet."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any

from raphiia_openai.settings import RALFIA_LAN_IP

INTEL_HOST = "192.168.1.4"
AMD_HOST = "192.168.1.5"
LOCAL_HOST = RALFIA_LAN_IP or AMD_HOST

NODES: list[dict[str, Any]] = [
    {
        "node_id": "intel",
        "label": "RalfIA Intel",
        "host": INTEL_HOST,
        "role": "primary",
        "gpu": "NVIDIA RTX 3060 12GB",
        "ngrok": True,
        "panel_url": f"http://{INTEL_HOST}:2002/",
        "probes": [
            {"id": "portal", "name": "Panel RalfIA", "url": f"http://{INTEL_HOST}:2002/api/ops/health"},
            {"id": "mcp", "name": "MCP", "url": f"http://{INTEL_HOST}:8101/status"},
            {"id": "uipath", "name": "UiPath Copilot", "url": f"http://{INTEL_HOST}:8097/status"},
            {"id": "ngrok", "name": "ngrok público", "url": "https://sworn-profusely-alongside.ngrok-free.dev/uipath/dashboard", "headers": {"ngrok-skip-browser-warning": "true"}},
            {"id": "evolution", "name": "Evolution WhatsApp", "url": f"http://{INTEL_HOST}:8082/"},
            {"id": "ollama", "name": "Ollama", "port": 11434},
        ],
    },
    {
        "node_id": "amd",
        "label": "RalfIA AMD",
        "host": AMD_HOST,
        "role": "gpu_worker",
        "gpu": "AMD Radeon AI PRO R9700 — 32GB VRAM RDNA4 ROCm",
        "ngrok": False,
        "panel_url": f"http://{AMD_HOST}:2002/",
        "probes": [
            {"id": "portal", "name": "Panel RalfIA", "url": f"http://{AMD_HOST}:2002/api/ops/health"},
            {"id": "mcp", "name": "MCP", "url": f"http://{AMD_HOST}:8101/status"},
            {"id": "voice", "name": "Voice Gateway", "url": f"http://{AMD_HOST}:8200/api/voice/health"},
            {
                "id": "vllm",
                "name": "vLLM ROCm",
                "url": f"http://{AMD_HOST}:8000/v1/models",
                "local_url": "http://127.0.0.1:8000/v1/models",
                "local_only": True,
            },
            {"id": "whisper", "name": "Whisper STT", "port": 9000},
            {"id": "evolution", "name": "Evolution AMD", "url": f"http://{AMD_HOST}:8082/"},
            {"id": "ollama", "name": "Ollama", "port": 11434},
            {"id": "ollama-router", "name": "Ollama Router", "url": f"http://{AMD_HOST}:11435/health"},
            {"id": "openwebui", "name": "Open WebUI", "url": f"http://{AMD_HOST}:3000/"},
            {"id": "comfyui", "name": "ComfyUI", "port": 8188},
        ],
    },
]


def _http_probe(url: str, *, headers: dict[str, str] | None = None, timeout: float = 6.0) -> dict[str, Any]:
    hdrs = {"User-Agent": "RalfIA-Fleet/1.0", **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": "up", "http": resp.status}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 406):
            return {"ok": True, "status": "unauthorized_alive", "http": exc.code}
        if exc.code in (301, 302, 307, 308):
            return {"ok": True, "status": "up", "http": exc.code}
        return {"ok": False, "status": "down", "http": exc.code, "error": str(exc.reason)[:80]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": "down", "error": str(exc)[:120]}


def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "status": "up"}
    except OSError as exc:
        return {"ok": False, "status": "down", "error": str(exc)[:80]}


def _ssh_probe(host: str) -> dict[str, Any]:
    import socket as _socket

    local_ips = {"127.0.0.1", "localhost", LOCAL_HOST, INTEL_HOST, AMD_HOST, _socket.gethostname()}
    try:
        local_ips.update(_socket.gethostbyname_ex(_socket.gethostname())[2])
    except OSError:
        pass
    if host in local_ips or host.replace(".", "") in "".join(local_ips):
        return {"ok": True, "hostname": _socket.gethostname(), "local": True}
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout=5", f"rlopez@{host}", "hostname"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if proc.returncode == 0:
            return {"ok": True, "hostname": (proc.stdout or "").strip()}
        return {"ok": False, "error": (proc.stderr or proc.stdout or "")[:120]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:120]}


def _local_host_ips() -> set[str]:
    local_ips = {"127.0.0.1", "localhost", LOCAL_HOST, INTEL_HOST, AMD_HOST, socket.gethostname()}
    try:
        local_ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return local_ips


def _is_local_host(host: str) -> bool:
    return host in _local_host_ips()


def _probe_one(host: str, spec: dict[str, Any]) -> dict[str, Any]:
    url = spec.get("url")
    if url and spec.get("local_url") and _is_local_host(host):
        url = spec["local_url"]
    if url:
        result = _http_probe(url, headers=spec.get("headers"))
        if spec.get("local_only") and not _is_local_host(host):
            result = {
                **result,
                "ok": True,
                "status": "local_only",
                "note": "vLLM escucha solo en 127.0.0.1 (sin auth OpenAI API)",
            }
    elif spec.get("port"):
        result = _tcp_probe(host, int(spec["port"]))
    else:
        result = {"ok": False, "status": "unknown"}
    out = {
        "id": spec.get("id"),
        "name": spec.get("name"),
        **result,
    }
    if spec.get("local_only") and _is_local_host(host):
        out["note"] = "solo localhost — no exponer a LAN sin API key"
    return out


def fleet_overview() -> dict[str, Any]:
    nodes_out: list[dict[str, Any]] = []
    for node in NODES:
        host = str(node["host"])
        ssh = _ssh_probe(host)
        probes = [_probe_one(host, p) for p in node.get("probes", [])]
        up = sum(1 for p in probes if p.get("ok"))
        nodes_out.append(
            {
                **{k: node[k] for k in ("node_id", "label", "host", "role", "gpu", "ngrok", "panel_url")},
                "ssh": ssh,
                "probes": probes,
                "summary": f"{up}/{len(probes)} servicios OK",
                "ok": ssh.get("ok") and up == len(probes),
            }
        )
    return {
        "ok": all(n.get("ok") for n in nodes_out),
        "nodes": nodes_out,
        "hint": "Panel unificado — usa /api/ops/fleet desde :2002 en Intel",
    }


def fleet_json_pretty() -> str:
    return json.dumps(fleet_overview(), ensure_ascii=False, indent=2)
