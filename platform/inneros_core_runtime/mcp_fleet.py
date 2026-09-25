"""Estado y enrutamiento federado del ecosistema MCP InnerOS (Intel + AMD).

Proporciona:
- fleet_status(): salud agregada, versiones, planos y conectividad.
- get_mcp_urls_ordered(): URLs ordenadas por prioridad según capacidades.
- resolve_mcp_url(): URL óptima para una tool específica.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
from typing import Any
import urllib.error
import urllib.request

from inneros_core_runtime import tool_catalog

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
INNEROS_CORE_ROOT = PLATFORM_ROOT.parent

RALFIA_LAN_IP = os.getenv("RALFIA_LAN_IP", "192.168.1.4")
INTEL_HOST = os.getenv("RALFIA_INTEL_HOST", "192.168.1.4")
AMD_HOST = os.getenv("RALFIA_AMD_HOST", "100.72.153.124")
AMD_LAN_FALLBACK = os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5")
MCP_PORT = int(os.getenv("MCP_PORT", "8102"))
MCP_SERVER_VERSION = os.getenv("MCP_SERVER_VERSION", "3.5.0")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")

RUNTIME_FINGERPRINT_FILES = (
    "inneros_core_runtime/dev_swarm_scheduler.py",
    "inneros_core_runtime/local_execution_plane.py",
    "inneros_core_runtime/mcp_profiles.py",
    "inneros_core_runtime/mcp_fleet.py",
    "inneros_core_runtime/agents/ag41_peer_ops_executor.py",
    "inneros_core_runtime/notifications/whatsapp_service_ops.py",
    "inneros_core_runtime/coordination_liveness.py",
    "inneros_core_runtime/universal_bootstrap.py",
    "inneros_core_runtime/session_guard.py",
    "inneros_core_runtime/auth_server.py",
    "inneros_core_runtime/oauth_store.py",
    "inneros_core_runtime/inneros_auth_middleware.py",
)

AMD_PREFERRED_PREFIXES = (
    "ha_",
    "hubitat_",
    "run_home_ops",
    "video_",
    "generate_video",
    "publish_video",
)
AMD_PREFERRED_TOOLS = frozenset(
    {
        "ha_ping",
        "ha_list_entities",
        "ha_get_entity",
        "ha_turn_on_light",
        "ha_turn_off_light",
        "ha_call_service",
        "ha_home_status",
        "hubitat_discover",
        "hubitat_status",
        "run_home_ops_cycle",
        "generate_video_content",
        "publish_video_content",
        "video_pipeline_health",
        "local_model_health",
        "generate_local_image",
    }
)

_probe_cache: dict[str, dict[str, Any]] = {}
_PROBE_TTL_SEC = float(os.getenv("MCP_FLEET_PROBE_TTL", "12"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_node_id() -> str:
    try:
        local_ips = set(socket.gethostbyname_ex(socket.gethostname())[2])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            local_ips.add(sock.getsockname()[0])
        if AMD_HOST in local_ips or AMD_LAN_FALLBACK in local_ips:
            return "amd"
        if INTEL_HOST in local_ips:
            return "intel"
    except OSError:
        pass
    ip = (RALFIA_LAN_IP or "").strip()
    if ip in (AMD_HOST, AMD_LAN_FALLBACK):
        return "amd"
    if ip == INTEL_HOST:
        return "intel"
    try:
        host = socket.gethostname().lower()
        if "amd" in host:
            return "amd"
    except OSError:
        pass
    return "intel"


def peer_node_id(node: str | None = None) -> str:
    node = node or local_node_id()
    return "amd" if node == "intel" else "intel"


def _mcp_base(host: str) -> str:
    return f"http://{host}:{MCP_PORT}"


def _mcp_url(host: str) -> str:
    return f"{_mcp_base(host)}/mcp"


def _version_url(host: str) -> str:
    return f"{_mcp_base(host)}/version"


def node_hosts() -> dict[str, str]:
    return {"intel": INTEL_HOST, "amd": AMD_HOST}


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _local_runtime_hashes() -> dict[str, str | None]:
    return {rel: _sha256_file(PLATFORM_ROOT / rel) for rel in RUNTIME_FINGERPRINT_FILES}


def _remote_runtime_hashes(node: str) -> dict[str, str | None]:
    if node == local_node_id():
        return _local_runtime_hashes()
    hosts = [node_hosts().get(node)]
    if node == "amd":
        hosts.append(AMD_LAN_FALLBACK)
    quoted = " ".join(f"'{rel}'" for rel in RUNTIME_FINGERPRINT_FILES)
    script = (
        f"cd {INNEROS_CORE_ROOT}/platform && "
        f"sha256sum {quoted} 2>/dev/null || true"
    )
    for host in hosts:
        if not host:
            continue
        try:
            proc = subprocess.run(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=5",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    f"rlopez@{host}",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                hashes: dict[str, str | None] = {rel: None for rel in RUNTIME_FINGERPRINT_FILES}
                for line in proc.stdout.splitlines():
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2 and parts[1] in hashes:
                        hashes[parts[1]] = parts[0]
                if any(hashes.values()):
                    return hashes
        except (subprocess.TimeoutExpired, OSError):
            continue
    return {rel: None for rel in RUNTIME_FINGERPRINT_FILES}


def runtime_fingerprints() -> dict[str, Any]:
    hashes = {node: _remote_runtime_hashes(node) for node in ("intel", "amd")}
    divergences = []
    for rel in RUNTIME_FINGERPRINT_FILES:
        intel_hash = hashes.get("intel", {}).get(rel)
        amd_hash = hashes.get("amd", {}).get(rel)
        if not intel_hash or not amd_hash or intel_hash != amd_hash:
            divergences.append({"file": rel, "intel": intel_hash, "amd": amd_hash})
    return {
        "ok": not divergences,
        "runtime_consistent": not divergences,
        "files": list(RUNTIME_FINGERPRINT_FILES),
        "hashes": hashes,
        "divergences": divergences,
    }


def _probe_tcp(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_http(host: str, timeout: float = 2.0) -> dict[str, Any]:
    url = f"http://{host}:{MCP_PORT}/version"
    req = urllib.request.Request(url, headers={"User-Agent": "inneros-mcp-fleet/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def probe_node(node: str, *, force: bool = False) -> dict[str, Any]:
    cached = _probe_cache.get(node)
    now = datetime.now(timezone.utc).timestamp()
    if not force and cached and (now - cached.get("_ts", 0)) < _PROBE_TTL_SEC:
        out = dict(cached)
        out.pop("_ts", None)
        return out

    hosts = [node_hosts().get(node)]
    if node == "amd":
        hosts.append(AMD_LAN_FALLBACK)

    best_result = None
    for host in hosts:
        if not host:
            continue
        tcp_ok = _probe_tcp(host, MCP_PORT)
        http_res = _probe_http(host) if tcp_ok else {"ok": False, "error": "tcp_unreachable"}
        mcp_ok = bool(http_res.get("ok"))
        data = http_res.get("data") or {}
        server_version = data.get("server_version") or data.get("version") or (MCP_SERVER_VERSION if mcp_ok else None)

        res = {
            "node": node,
            "host": host,
            "tcp_ok": tcp_ok,
            "mcp_ok": mcp_ok,
            "ok": tcp_ok and mcp_ok,
            "server_version": server_version,
            "mcp_url": _mcp_url(host),
            "checked_at": _now_iso(),
            "_ts": now,
        }
        if res["ok"]:
            best_result = res
            break
        if best_result is None:
            best_result = res

    _probe_cache[node] = best_result or {}
    out = dict(best_result or {})
    out.pop("_ts", None)
    return out


def tool_preferred_node(tool_name: str) -> str:
    name = (tool_name or "").strip()
    if name in AMD_PREFERRED_TOOLS:
        return "amd"
    if any(name.startswith(pfx) for pfx in AMD_PREFERRED_PREFIXES):
        return "amd"
    return "intel"


def get_mcp_urls_ordered(
    *,
    tool_name: str | None = None,
    preferred_node: str | None = None,
    active_only: bool = True,
) -> list[str]:
    target = preferred_node or (tool_preferred_node(tool_name) if tool_name else "intel")
    order = ["intel", "amd"] if target == "intel" else ["amd", "intel"]
    urls: list[str] = []
    hosts = node_hosts()
    for node in order:
        host = hosts.get(node)
        if not host:
            continue
        if active_only:
            pr = probe_node(node)
            if not pr.get("ok"):
                continue
        urls.append(_mcp_url(host))
    if not urls:
        urls = [_mcp_url(hosts.get("intel", INTEL_HOST)), _mcp_url(hosts.get("amd", AMD_HOST))]
    return urls


def resolve_mcp_url(tool_name: str | None = None) -> str:
    urls = get_mcp_urls_ordered(tool_name=tool_name, active_only=True)
    if urls:
        return urls[0]
    return _mcp_url(INTEL_HOST)


def fleet_status(*, force_probe: bool = False) -> dict[str, Any]:
    intel = probe_node("intel", force=force_probe)
    amd = probe_node("amd", force=force_probe)
    local = local_node_id()
    runtime = runtime_fingerprints()
    return {
        "ok": bool(intel.get("ok") and amd.get("ok") and runtime.get("runtime_consistent")),
        "logical_version": MCP_SERVER_VERSION,
        "catalog_version": tool_catalog.MCP_VERSION,
        "catalog_tool_count": len(tool_catalog.ALL_MCP_TOOL_NAMES),
        "runtime_consistent": runtime.get("runtime_consistent"),
        "runtime_fingerprints": runtime,
        "local_node": local,
        "peer_node": peer_node_id(local),
        "nodes": {"intel": intel, "amd": amd},
        "routing": {
            "model": "one_logical_mcp_two_planes",
            "intel_plane": "business, memory, coordination, contifico, whatsapp",
            "amd_plane": "voice, gpu media, ha proxy, video pipeline",
            "failover": "capability_preferred_then_peer",
        },
        "public_entrypoints": {
            "chatgpt_ngrok": "https://sworn-profusely-alongside.ngrok-free.dev/raphiia-mcp/mcp",
            "voice_local": f"http://{INTEL_HOST}:{MCP_PORT}/mcp",
        },
        "checked_at": _now_iso(),
    }
