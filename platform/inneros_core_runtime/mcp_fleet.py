"""MCP dual-nodo Intel (.4) + AMD (.5) — routing por capability y failover."""

from __future__ import annotations

import json
import os
import hashlib
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.mcp_catalog import tool_catalog
from raphiia_openai.settings import MCP_API_KEY, RALFIA_LAN_IP

INTEL_HOST = os.getenv("RALFIA_INTEL_HOST", "192.168.1.4")
AMD_HOST = os.getenv("RALFIA_AMD_HOST", "192.168.1.5")
MCP_PORT = int(os.getenv("MCP_PORT", "8102"))
MCP_SERVER_VERSION = os.getenv("MCP_SERVER_VERSION", "3.5.0")
INNEROS_CORE_ROOT = os.getenv("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core")
PLATFORM_ROOT = Path(INNEROS_CORE_ROOT) / "platform"
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

# Tools que preferentemente ejecuta AMD (GPU, voz, HA proxy, vídeo)
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
        if AMD_HOST in local_ips:
            return "amd"
        if INTEL_HOST in local_ips:
            return "intel"
    except OSError:
        pass
    ip = (RALFIA_LAN_IP or "").strip()
    if ip == AMD_HOST:
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
    host = node_hosts().get(node)
    if not host:
        return {}
    quoted = " ".join(f"'{rel}'" for rel in RUNTIME_FINGERPRINT_FILES)
    script = (
        f"cd {INNEROS_CORE_ROOT}/platform && "
        f"sha256sum {quoted} 2>/dev/null || true"
    )
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-F",
                "/dev/null",
                "-i",
                "/home/rlopez/.ssh/id_rsa",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "UserKnownHostsFile=/home/rlopez/.ssh/known_hosts",
                f"rlopez@{host}",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {rel: None for rel in RUNTIME_FINGERPRINT_FILES}
    hashes: dict[str, str | None] = {rel: None for rel in RUNTIME_FINGERPRINT_FILES}
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1] in hashes:
            hashes[parts[1]] = parts[0]
    return hashes


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


def tool_preferred_node(tool_name: str | None) -> str:
    name = (tool_name or "").strip()
    if not name:
        return local_node_id()
    if name in AMD_PREFERRED_TOOLS:
        return "amd"
    if any(name.startswith(p) for p in AMD_PREFERRED_PREFIXES):
        return "amd"
    return "intel"


def _tcp_open(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_node(node: str, *, force: bool = False) -> dict[str, Any]:
    """Health ligero: TCP :8102 + opcional initialize MCP."""
    hosts = node_hosts()
    host = hosts.get(node, INTEL_HOST)
    cache_key = f"node:{node}"
    cached = _probe_cache.get(cache_key)
    if cached and not force:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["checked_at"])).total_seconds()
        if age < _PROBE_TTL_SEC:
            return cached

    tcp_ok = _tcp_open(host, MCP_PORT)
    mcp_ok = False
    server_version = None
    probe_host = "127.0.0.1" if node == local_node_id() else host
    if tcp_ok:
        if node == local_node_id():
            mcp_ok = True
            server_version = MCP_SERVER_VERSION
        else:
            try:
                req = urllib.request.Request(_version_url(probe_host), method="GET")
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    payload = json.loads(resp.read(4096).decode("utf-8", errors="replace"))
                    mcp_ok = bool(payload.get("ok"))
                    server_version = payload.get("server_version")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                mcp_ok = False

    if tcp_ok and not mcp_ok:
        try:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp-fleet-probe", "version": "1"},
                    },
                }
            ).encode()
            req = urllib.request.Request(
                _mcp_url(probe_host),
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    **({"X-API-Key": MCP_API_KEY} if MCP_API_KEY else {}),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                raw = resp.read(4096).decode("utf-8", errors="replace")
                for line in raw.splitlines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        info = (payload.get("result") or {}).get("serverInfo") or {}
                        server_version = info.get("version")
                        mcp_ok = True
                        break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            mcp_ok = False

    result = {
        "node": node,
        "host": host,
        "tcp_ok": tcp_ok,
        "mcp_ok": mcp_ok,
        "ok": tcp_ok and mcp_ok,
        "server_version": server_version,
        "mcp_url": _mcp_url(host),
        "checked_at": _now_iso(),
    }
    _probe_cache[cache_key] = result
    return result


def get_mcp_urls_ordered(*, tool_name: str | None = None) -> list[str]:
    """URLs MCP en orden de intento: preferido por capability, luego peer si cae."""
    preferred = tool_preferred_node(tool_name)
    peer = peer_node_id(preferred)
    local = local_node_id()

    primary_node = preferred
    secondary_node = peer

    # Si estamos en el nodo peer y el preferido es remoto, intentar local primero si es más rápido
    order = [primary_node, secondary_node]
    if local == secondary_node and primary_node != local:
        # Remoto preferido, local como failover rápido
        order = [primary_node, secondary_node]
    elif local == primary_node:
        order = [primary_node, secondary_node]

    hosts = node_hosts()
    urls: list[str] = []
    for node in order:
        url = _mcp_url(hosts[node])
        if url not in urls:
            urls.append(url)
    return urls


def resolve_mcp_url(tool_name: str | None = None) -> str:
    """Primera URL MCP viva; si ninguna responde, devuelve la preferida."""
    for node in ("intel", "amd"):
        probe_node(node)
    for url in get_mcp_urls_ordered(tool_name=tool_name):
        host = url.split("//")[1].split(":")[0]
        node = "amd" if host == AMD_HOST else "intel"
        if probe_node(node).get("ok"):
            return url
    return get_mcp_urls_ordered(tool_name=tool_name)[0]


def fleet_status(*, force_probe: bool = False) -> dict[str, Any]:
    intel = probe_node("intel", force=force_probe)
    amd = probe_node("amd", force=force_probe)
    local = local_node_id()
    runtime = runtime_fingerprints()
    return {
        "ok": bool((intel.get("ok") or amd.get("ok")) and runtime.get("runtime_consistent")),
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
            "voice_local": resolve_mcp_url(),
        },
        "checked_at": _now_iso(),
    }


def _extract_sse_json(raw: str) -> dict[str, Any]:
    for line in raw.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            result = payload.get("result") or {}
            if result.get("structuredContent") is not None:
                return dict(result.get("structuredContent") or {})
            content = result.get("content") or []
            if content and isinstance(content[0], dict):
                text = content[0].get("text") or "{}"
                return json.loads(text)
            return result
    return {}


def _mcp_post(host: str, payload: dict[str, Any], session_id: str | None = None, timeout: float = 30.0) -> tuple[dict[str, str], str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **({"X-API-Key": MCP_API_KEY} if MCP_API_KEY else {}),
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    req = urllib.request.Request(_mcp_url(host), data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return dict(resp.headers), resp.read(65536).decode("utf-8", errors="replace")


def _sync_intel_from_amd_peer() -> dict[str, Any]:
    try:
        headers, _raw = _mcp_post(
            AMD_HOST,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-fleet-sync-dispatch", "version": "1"},
                },
            },
            timeout=10.0,
        )
        session_id = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        if session_id:
            _mcp_post(AMD_HOST, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, session_id, timeout=10.0)
        _headers, raw = _mcp_post(
            AMD_HOST,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "sync_platform_to_intel", "arguments": {"dry_run": False, "restart_intel": False}},
            },
            session_id,
            timeout=360.0,
        )
        data = _extract_sse_json(raw)
        if data.get("ok"):
            try:
                subprocess.Popen(
                    ["sh", "-lc", "sleep 2; systemctl --user restart ralfia-mcp.service ralfia-app.service"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                data["intel_restart"] = "scheduled_after_response"
            except OSError as exc:
                data["intel_restart"] = False
                data["intel_restart_error"] = str(exc)[:200]
        return {"delegated_to": "amd_mcp", **data}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": "amd_mcp_dispatch_failed", "detail": str(exc)[:500]}


def sync_intel_from_local(*, restart_intel: bool = True) -> dict[str, Any]:
    """Rsync platform hacia Intel y reinicia MCP.

    The public MCP normally runs from Intel. If this function is invoked there,
    delegate the mutation to AMD instead of returning a dead-end error.
    """
    if local_node_id() != "amd":
        return _sync_intel_from_amd_peer()
    src = f"{INNEROS_CORE_ROOT}/platform/"
    dst = f"rlopez@{INTEL_HOST}:{INNEROS_CORE_ROOT}/platform/"
    cmd = [
        "rsync",
        "-az",
        "--delete",
        "--exclude",
        "venv/",
        "--exclude",
        "__pycache__/",
        "--exclude",
        ".git/",
        src,
        dst,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": "rsync_failed", "stderr": (proc.stderr or "")[-500:]}
        if not restart_intel:
            return {"ok": True, "rsync": "ok", "intel_restart": False, "restart_skipped": True}
        restart = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                f"rlopez@{INTEL_HOST}",
                "systemctl --user restart ralfia-mcp.service ralfia-app.service",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "ok": restart.returncode == 0,
            "rsync": "ok",
            "intel_restart": restart.returncode == 0,
            "stderr": (restart.stderr or "")[-300:],
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "error": str(exc)}
