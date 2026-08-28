"""AG-40 Runtime Reconciler — inventario read-only dual-nodo, sin mutar producción."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.settings import RALFIA_AMD_HOST, RALFIA_INTEL_HOST

AGENT_ID = "AG-40_RUNTIME_RECONCILER"
COL_REPORTS = "ralfia_runtime_reconcile_reports"
REPORT_DIR = Path(__file__).resolve().parents[2] / "var" / "runtime_reconcile"

EXPECTED_INACTIVE_UNITS = frozenset({
    "ralfia-atlas-hydrator.service",
    "ralfia-boot-verify.service",
    "ralfia-disk-steward.service",
    "ralfia-app.service",
})

CORE_BY_NODE: dict[str, list[tuple[str, int, str, str]]] = {
    "intel": [
        ("raphiia-mcp", 8102, "/health", "critical"),
        ("raphiia-oauth", 8103, "/health", "critical"),
        ("raphiia-health", 8101, "/status", "high"),
        ("portal-control-center", 2002, "/login", "critical"),
        ("ralfia-voice-gateway", 8200, "/", "medium"),
    ],
    "amd": [
        ("raphiia-mcp", 8102, "/health", "critical"),
        ("vllm-rocm", 8000, "/health", "on_demand"),
        ("ollama-router", 11435, "/api/tags", "on_demand"),
        ("comfyui-amd", 8188, "/", "on_demand"),
        ("whisper-amd", 9000, "/health", "on_demand"),
    ],
}

CORE_UNITS = [
    "ralfia-mcp.service",
    "ralfia-auth.service",
    "ralfia-coordination-daemon.service",
    "opportunityops-cloudflared.service",
    "ralfia-voice-gateway.service",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tcp(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http(host: str, port: int, path: str, timeout: float = 8.0) -> int | str | None:
    url = f"http://{host}:{port}{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AG-40/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:
        return str(exc)[:80]


def _systemctl(host: str | None, unit: str) -> str:
    is_local = not host or host in {"127.0.0.1", "localhost"}
    try:
        hostname = socket.gethostname().lower()
        if host == RALFIA_AMD_HOST and "amd" in hostname:
            is_local = True
        elif host == RALFIA_INTEL_HOST and "amd" not in hostname:
            is_local = True
    except Exception:
        pass

    cmd = ["systemctl", "--user", "is-active", unit]
    if not is_local:
        cmd = ["ssh", "-o", "BatchMode=yes", f"rlopez@{host}", "systemctl", "--user", "is-active", unit]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (proc.stdout or proc.stderr or "unknown").strip()
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"


def _classify_registry_entry(s: dict[str, Any], local_node: str) -> str | None:
    sid = str(s.get("service_id") or s.get("id") or "")
    st = s.get("status", "unknown")
    if st in ("up", "unauthorized_alive"):
        return None
    if sid.startswith("discovered-"):
        return "AUTO_DISCOVERED_STALE"
    if sid.startswith("portal-") and sid.replace("portal-", "") in sid:
        return "PORTAL_MIRROR"
    if sid in {"ngrok-public-tunnel", "public-gateway", "uipath-copilot", "portal-8800-redirect"}:
        return "LEGACY"
    if any(x in sid for x in ("hydrator", "boot-verify", "disk-steward")):
        return "ON_DEMAND_TIMER"
    if sid in {"ralfia-app", "editorial-hub"}:
        return "ON_DEMAND"
    preferred = s.get("preferred_node") or s.get("eligible_nodes")
    if preferred and local_node not in str(preferred) and st == "down":
        return "FALSE_DOWN_WRONG_NODE"
    if s.get("risk_level") == "critical" and sid in {"raphiia-mcp", "raphiia-oauth", "portal-control-center"}:
        return "CORE_DEGRADED"
    if st in ("down", "timeout", "failed"):
        return "REAL_DOWN"
    if st == "unknown":
        return "UNMONITORED"
    return "REVIEW"


def _probe_core_matrix() -> list[dict[str, Any]]:
    hosts = {"intel": RALFIA_INTEL_HOST, "amd": RALFIA_AMD_HOST}
    rows: list[dict[str, Any]] = []
    for node, probes in CORE_BY_NODE.items():
        host = hosts[node]
        for name, port, path, tier in probes:
            tcp_ok = _tcp(host, port)
            http = _http(host, port, path) if tcp_ok else None
            ok = tcp_ok and (http is None or (isinstance(http, int) and http < 500))
            rows.append({
                "node": node,
                "host": host,
                "service": name,
                "port": port,
                "tier": tier,
                "tcp_ok": tcp_ok,
                "http": http,
                "ok": ok,
                "expected_on_node": True,
            })
    return rows


def reconcile_runtime_state(*, dry_run: bool = True, node: str | None = None) -> dict[str, Any]:
    """Read-only: fleet MCP, registry dual-nodo, cockpit AG-31, matriz core."""
    from raphiia_openai import mcp_fleet, service_registry
    from raphiia_openai.agents import ag31_service_recovery_agent as ag31

    service_registry.seed_defaults(force=False)
    fleet = mcp_fleet.fleet_status(force_probe=True)
    local_node = fleet.get("local_node") or "intel"

    # Checks desde nodo local; no mutar si dry_run — usar estado ya en mongo
    registry = service_registry.list_services(visible_only=False, limit=250)
    cockpit = ag31._cockpit_snapshot()
    watch_registry = ag31._registry_snapshot()

    core_matrix = _probe_core_matrix()
    unit_rows = []
    for unit in CORE_UNITS:
        intel_st = _systemctl(RALFIA_INTEL_HOST, unit) if unit != "ralfia-auth.service" or True else "n/a"
        amd_st = _systemctl(RALFIA_AMD_HOST, unit)
        # auth solo intel
        if unit == "ralfia-auth.service":
            amd_st = "not_applicable"
        if unit == "opportunityops-cloudflared.service":
            amd_st = "not_applicable"
        unit_rows.append({"unit": unit, "intel": intel_st, "amd": amd_st})

    classified: list[dict[str, Any]] = []
    for s in registry.get("services") or []:
        cls = _classify_registry_entry(s, local_node)
        if not cls:
            continue
        classified.append({
            "service_id": s.get("service_id") or s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "risk": s.get("risk_level"),
            "classification": cls,
        })

    cls_counts = dict(Counter(c["classification"] for c in classified))
    false_down_ids = [c["service_id"] for c in classified if c["classification"] in {
        "AUTO_DISCOVERED_STALE", "PORTAL_MIRROR", "FALSE_DOWN_WRONG_NODE", "LEGACY", "ON_DEMAND", "ON_DEMAND_TIMER", "UNMONITORED"
    }]
    real_core = [r for r in core_matrix if not r["ok"] and r["tier"] in ("critical", "high")]
    real_down_registry = [c for c in classified if c["classification"] in ("CORE_DEGRADED", "REAL_DOWN")][:25]

    warm_standby = {
        "amd_always": ["raphiia-mcp", "ralfia-voice-gateway (optional peer)"],
        "amd_on_demand": ["vllm-rocm", "ollama-router", "comfyui-amd", "whisper-amd", "ralfia-app"],
        "intel_only": ["raphiia-oauth", "opportunityops-cloudflared", "portal-control-center", "ralfia-coordination-daemon (primary)"],
        "note": "Registry debe marcar preferred_node/eligible_nodes para evitar falsos DOWN cruzados",
    }

    report = {
        "ok": len(real_core) == 0 and fleet.get("ok"),
        "agent_id": AGENT_ID,
        "dry_run": dry_run,
        "generated_at": _now_iso(),
        "ts_display": ralfia_time.format_log(),
        "local_node": local_node,
        "fleet_nodes": fleet.get("nodes"),
        "cockpit": cockpit,
        "watch_registry": watch_registry,
        "core_matrix": core_matrix,
        "systemd_units_dual": unit_rows,
        "registry_classification_counts": cls_counts,
        "false_down_corrected_count": len(false_down_ids),
        "false_down_sample": false_down_ids[:20],
        "real_core_issues": real_core,
        "real_down_registry_sample": real_down_registry,
        "warm_standby_amd": warm_standby,
        "summary": {
            "fleet_ok": fleet.get("ok"),
            "core_issues": len(real_core),
            "false_down_corrected": len(false_down_ids),
            "registry_degraded": sum(v for k, v in cls_counts.items() if k not in ("AUTO_DISCOVERED_STALE", "PORTAL_MIRROR")),
        },
        "next_steps": [
            "Actualizar service_registry con preferred_node por servicio",
            "Archivar discovered-* stale del registry",
            "vLLM/Comfy/Ollama: levantar on-demand en AMD cuando route_ai_task lo pida",
            "Failover dry-run: scripts/failover_intel_to_amd.sh sin --execute",
        ],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest = REPORT_DIR / "latest_matrix.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if not dry_run:
        mongo_store.get_db()[COL_REPORTS].insert_one({**report, "stored_at": _now_iso()})

    record_agent_run(
        AGENT_ID,
        action="reconcile_runtime_state",
        summary=f"core_issues={len(real_core)} false_down={len(false_down_ids)} fleet={fleet.get('ok')}",
        project="ralfia-ops",
        metadata={"summary": report["summary"]},
    )
    return report
