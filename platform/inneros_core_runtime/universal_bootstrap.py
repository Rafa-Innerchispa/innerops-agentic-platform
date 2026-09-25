"""InnerOS Universal Bootstrap v3 ? Route-Aware Access Plane.

Authoritative discovery and dynamic connectivity resolution across:
- Tier 1: Local Loopback / LAN (127.0.0.1, 192.168.1.4 Intel, 192.168.1.5 AMD)
- Tier 2: Tailscale Mesh (100.94.99.12 Intel, 100.72.153.124 AMD, 100.103.151.40 Bellini)
- Tier 3: Cloudflare Edge HTTPS (mcp.pcdoctor.ai, auth.pcdoctor.ai, sovereign-devos.pcdoctor.ai)

Provides zero-configuration fresh-session auto-bootstrap, Intel/AMD transparent failover,
and one-time device enrollment without exposing raw internal ports to the public Internet.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BOOTSTRAP_VERSION = "3.0.0"
CONFIG_DIR = Path(os.path.expanduser("~/.inneros"))
CONFIG_FILE = CONFIG_DIR / "bootstrap_profile.json"

TOPOLOGY = {
    "intel": {
        "node_id": "ralphi-ia-intel",
        "lan_ip": "192.168.1.4",
        "ts_ip": "100.94.99.12",
        "mcp_port": 8102,
        "auth_port": 8103,
        "devos_port": 2002,
        "mongo_port": 27017,
    },
    "amd": {
        "node_id": "ralphi-ia-amd",
        "lan_ip": "192.168.1.5",
        "ts_ip": "100.72.153.124",
        "mcp_port": 8102,
        "auth_port": 8103,
        "devos_port": 2002,
        "mongo_port": 27017,
    },
    "bellini_lobby": {
        "node_id": "bellini-lobby",
        "ts_ip": "100.103.151.40",
        "subnet": "192.168.3.0/24",
    },
    "cloudflare_edge": {
        "mcp_full": "https://mcp.pcdoctor.ai/mcp",
        "mcp_compact": "https://mcp-chatgpt.creatorcore.ai/mcp",
        "auth_server": "https://auth.pcdoctor.ai",
        "devos": "https://sovereign-devos.pcdoctor.ai",
    },
}

PRIVATE_INTERNAL_PORTS = {8102, 8103, 11434, 8001, 27017, 8123, 22, 554, 8554}


@dataclass
class ProbeResult:
    target: str
    tier: str
    reachable: bool
    latency_ms: float
    status_code: int | None = None
    error: str | None = None


def probe_tcp(host: str, port: int, timeout_sec: float = 0.8) -> tuple[bool, float, str | None]:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            latency = (time.perf_counter() - start) * 1000.0
            return True, round(latency, 2), None
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000.0
        return False, round(latency, 2), f"{type(exc).__name__}: {exc}"


def probe_http(url: str, timeout_sec: float = 1.5) -> tuple[bool, float, int | None, str | None]:
    start = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": f"InnerOS-UniversalBootstrap/{BOOTSTRAP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            latency = (time.perf_counter() - start) * 1000.0
            return True, round(latency, 2), resp.status, None
    except urllib.error.HTTPError as exc:
        latency = (time.perf_counter() - start) * 1000.0
        reachable = exc.code in {200, 204, 301, 302, 307, 308, 400, 401, 403, 404, 405}
        return reachable, round(latency, 2), exc.code, None
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000.0
        return False, round(latency, 2), None, f"{type(exc).__name__}: {exc}"


def get_enrolled_device_profile() -> dict[str, Any]:
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "enrolled": False,
        "device_name": socket.gethostname(),
        "registered_at": None,
        "preferred_tier": "auto",
    }


def enroll_device(
    device_name: str | None = None,
    preferred_tier: str = "auto",
    custom_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    name = (device_name or socket.gethostname()).strip()
    profile = {
        "enrolled": True,
        "device_name": name,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "preferred_tier": preferred_tier,
        "metadata": custom_metadata or {},
        "version": BOOTSTRAP_VERSION,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    return profile


def probe_route_access_plane(
    http_prober: Callable[[str, float], tuple[bool, float, int | None, str | None]] = probe_http,
    tcp_prober: Callable[[str, int, float], tuple[bool, float, str | None]] = probe_tcp,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []

    # 1. Loopback
    ok, lat, err = tcp_prober("127.0.0.1", 8102, 0.4)
    results.append(ProbeResult("loopback_mcp", "lan", ok, lat, None, err))

    # 2. LAN Intel & AMD
    ok, lat, err = tcp_prober(TOPOLOGY["intel"]["lan_ip"], 8102, 0.6)
    results.append(ProbeResult("intel_lan_mcp", "lan", ok, lat, None, err))
    ok, lat, err = tcp_prober(TOPOLOGY["amd"]["lan_ip"], 8102, 0.6)
    results.append(ProbeResult("amd_lan_mcp", "lan", ok, lat, None, err))

    # 3. Tailscale Mesh Intel & AMD
    ok, lat, err = tcp_prober(TOPOLOGY["intel"]["ts_ip"], 8102, 0.8)
    results.append(ProbeResult("intel_ts_mcp", "tailscale", ok, lat, None, err))
    ok, lat, err = tcp_prober(TOPOLOGY["amd"]["ts_ip"], 8102, 0.8)
    results.append(ProbeResult("amd_ts_mcp", "tailscale", ok, lat, None, err))

    # 4. Cloudflare Edge HTTPS (Public Tiers)
    ok, lat, code, err = http_prober(TOPOLOGY["cloudflare_edge"]["mcp_full"], 1.5)
    results.append(ProbeResult("cloudflare_mcp_full", "cloudflare_https", ok, lat, code, err))

    ok, lat, code, err = http_prober(TOPOLOGY["cloudflare_edge"]["mcp_compact"], 1.5)
    results.append(ProbeResult("cloudflare_mcp_compact", "cloudflare_https", ok, lat, code, err))

    return results


def resolve_universal_bootstrap(
    client_env: str = "auto",
    force_tier: str | None = None,
    custom_prober: Callable[..., list[ProbeResult]] | None = None,
) -> dict[str, Any]:
    probes = (custom_prober or probe_route_access_plane)()
    probe_map = {p.target: p for p in probes}
    device = get_enrolled_device_profile()

    intel_lan_ok = probe_map.get("intel_lan_mcp", ProbeResult("", "", False, 0)).reachable
    amd_lan_ok = probe_map.get("amd_lan_mcp", ProbeResult("", "", False, 0)).reachable
    intel_ts_ok = probe_map.get("intel_ts_mcp", ProbeResult("", "", False, 0)).reachable
    amd_ts_ok = probe_map.get("amd_ts_mcp", ProbeResult("", "", False, 0)).reachable
    loopback_ok = probe_map.get("loopback_mcp", ProbeResult("", "", False, 0)).reachable

    active_node = "intel"
    failover_available = False
    if intel_lan_ok or intel_ts_ok:
        active_node = "intel"
        failover_available = amd_lan_ok or amd_ts_ok
    elif amd_lan_ok or amd_ts_ok:
        active_node = "amd"
        failover_available = False
    elif loopback_ok:
        active_node = "intel"
        failover_available = False

    selected_tier = "cloudflare_https"
    if force_tier in {"lan", "tailscale", "cloudflare_https"}:
        selected_tier = force_tier
    elif loopback_ok or intel_lan_ok or amd_lan_ok:
        selected_tier = "lan"
    elif intel_ts_ok or amd_ts_ok:
        selected_tier = "tailscale"
    else:
        selected_tier = "cloudflare_https"

    mcp_full = ""
    mcp_compact = ""
    auth_ep = ""
    devos_ep = ""
    mongo_uri = None

    if selected_tier == "lan":
        host = "127.0.0.1" if loopback_ok else (TOPOLOGY[active_node]["lan_ip"])
        mcp_full = f"http://{host}:8102/mcp"
        mcp_compact = f"http://{host}:8102/mcp"
        auth_ep = f"http://{host}:8103"
        devos_ep = f"http://{host}:2002"
        mongo_uri = f"mongodb://{host}:27017"
    elif selected_tier == "tailscale":
        host = TOPOLOGY[active_node]["ts_ip"]
        mcp_full = f"http://{host}:8102/mcp"
        mcp_compact = f"http://{host}:8102/mcp"
        auth_ep = f"http://{host}:8103"
        devos_ep = f"http://{host}:2002"
        mongo_uri = f"mongodb://{host}:27017"
    else:
        mcp_full = TOPOLOGY["cloudflare_edge"]["mcp_full"]
        mcp_compact = TOPOLOGY["cloudflare_edge"]["mcp_compact"]
        auth_ep = TOPOLOGY["cloudflare_edge"]["auth_server"]
        devos_ep = TOPOLOGY["cloudflare_edge"]["devos"]
        mongo_uri = None

    return {
        "version": BOOTSTRAP_VERSION,
        "tier_selected": selected_tier,
        "active_node": active_node,
        "failover_available": failover_available,
        "endpoints": {
            "mcp_full": mcp_full,
            "mcp_compact": mcp_compact,
            "auth_server": auth_ep,
            "devos": devos_ep,
            "mongo_uri": mongo_uri,
        },
        "topology": TOPOLOGY,
        "enrolled_device": device,
        "probe_matrix": [asdict(p) for p in probes],
        "fresh_session_auto_bootstrap": True,
        "legacy_ngrok_deprecated": True,
        "security_policy": "Raw ports (8102, 8103, 11434, 8001, 27017, SSH) restricted to LAN/Tailscale. Public access via Cloudflare HTTPS only.",
    }
