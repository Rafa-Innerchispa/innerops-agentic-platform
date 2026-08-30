"""Dual deployment contract for InnerOS cloud and local runtimes.

This module is deliberately read-only by default. It reports where the product
can run, which providers are active, and what degraded/offline behavior is
allowed without claiming data replication that has not been implemented.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AMD_NODE = "192.168.1.5"
INTEL_NODE = "192.168.1.4"
GCP_PROJECT = "innerops-agentic-platform"
GCP_REGION = "us-central1"

LOCAL_RUNTIME_SERVICES = [
    {
        "service_id": "inneros-mcp",
        "unit": "ralfia-mcp.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:8102/mcp",
        "role": "mcp_ecosystem_entrypoint",
    },
    {
        "service_id": "inneros-portal",
        "unit": "ralfia-portal.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:2002/",
        "role": "local_control_center",
    },
    {
        "service_id": "workforce-local",
        "unit": "femar-mvp-core.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:3010/",
        "role": "local_workforce_shell",
    },
    {
        "service_id": "vllm-rocm10",
        "unit": "inneros-vllm-canary-rocm10.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:8000/v1/models",
        "role": "local_ai_inference",
    },
    {
        "service_id": "local-model-worker",
        "unit": "inneros-local-model-worker.service",
        "node": "amd",
        "local_url": "",
        "role": "local_agent_queue_worker",
    },
    {
        "service_id": "quoteops",
        "unit": "ralfia-quoteops.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:8765/health",
        "role": "quoteops_module",
    },
    {
        "service_id": "founderos",
        "unit": "ralfia-founderos.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:8766/health",
        "role": "founderos_module",
    },
    {
        "service_id": "iskcon-desk",
        "unit": "iskcon-desk.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:2027/",
        "role": "iskcon_module",
    },
    {
        "service_id": "visitors-backend",
        "unit": "vigilos-cursor.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:8011/health",
        "role": "visitors_backend",
    },
    {
        "service_id": "visitors-frontend",
        "unit": "vigilos-cursor-frontend.service",
        "node": "amd",
        "local_url": "http://127.0.0.1:5175/",
        "role": "visitors_frontend",
    },
]

CLOUD_SURFACES = [
    {
        "service_id": "inneros-cloud-run",
        "provider": "gcp_cloud_run",
        "project": GCP_PROJECT,
        "region": GCP_REGION,
        "public_url": "https://inneros.pcdoctor.ai/",
        "role": "managed_cloud_inneros_shell",
    },
    {
        "service_id": "inneros-creatorcore",
        "provider": "cloudflare_route",
        "public_url": "https://inneros.creatorcore.ai/app/login",
        "role": "primary_inneros_login",
    },
    {
        "service_id": "workforce-creatorcore",
        "provider": "cloudflare_route",
        "public_url": "https://workforce.creatorcore.ai/",
        "role": "current_workforce_entrypoint",
    },
    {
        "service_id": "iskcon-inneros",
        "provider": "cloudflare_route",
        "public_url": "https://inneros.iskconguayaquil.org/app/login",
        "role": "iskcon_inneros_entrypoint",
    },
]

IDENTITY_CONTRACT = {
    "tenant_identity": "shared tenant membership and module entitlement contract across cloud and local",
    "cloud_source_of_truth": ["GCP/Firestore and managed service state where already implemented"],
    "local_source_of_truth": ["Mongo/RACB/Resource Fabric and local module stores already owned by InnerOS"],
    "no_blind_db_duplication": True,
    "auth_boundary": "Cloud login remains managed/OAuth; local degraded mode may use secure existing session or explicitly scoped local auth only.",
}

OFFLINE_MODE = {
    "allowed_when_cloud_unreachable": [
        "serve local control plane health",
        "use local MCP/RACB coordination",
        "route local AI tasks to AMD ROCm/vLLM or local worker",
        "queue syncable operations with idempotency keys",
        "read local cached/module-owned data when ownership is explicit",
    ],
    "not_allowed": [
        "claim replicated Firestore/GCP data without a recorded mirror",
        "open shell/general execution outside existing Local Execution Plane allowlists",
        "perform destructive sync conflict resolution automatically",
        "treat degraded output as PASS evidence",
    ],
    "conflict_policy": "idempotent queue first; human or owner-approved resolver for destructive/cross-source conflicts",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_status(url: str, timeout: float = 4.0) -> dict[str, Any]:
    if not url:
        return {"status": "not_applicable"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InnerOS-DualDeployment/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"status": "up" if 200 <= resp.status < 400 else "degraded", "http_status": resp.status}
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 406}:
            return {"status": "unauthorized_alive", "http_status": exc.code}
        return {"status": "down", "http_status": exc.code}
    except Exception as exc:
        return {"status": "down", "error": type(exc).__name__}


def _systemd_state(unit: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception as exc:
        return {"state": "unknown", "ok": False, "error": type(exc).__name__}
    state = (proc.stdout or proc.stderr or "").strip() or "unknown"
    return {"state": state, "ok": state == "active"}


def _gcloud_run_services() -> dict[str, Any]:
    gcloud = Path.home() / ".local" / "bin" / "gcloud"
    if not gcloud.exists():
        return {"ok": False, "status": "unavailable", "error": "gcloud_not_found"}
    try:
        proc = subprocess.run(
            [
                str(gcloud),
                "run",
                "services",
                "list",
                "--project",
                GCP_PROJECT,
                "--region",
                GCP_REGION,
                "--format=json",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "status": "unavailable", "error": type(exc).__name__}
    if proc.returncode != 0:
        return {"ok": False, "status": "degraded", "returncode": proc.returncode, "stderr": proc.stderr[-1000:]}
    try:
        services = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        services = []
    return {
        "ok": True,
        "status": "up",
        "project": GCP_PROJECT,
        "region": GCP_REGION,
        "services": [
            {
                "name": item.get("metadata", {}).get("name"),
                "url": item.get("status", {}).get("url"),
                "ready": next(
                    (
                        cond.get("status")
                        for cond in item.get("status", {}).get("conditions", [])
                        if cond.get("type") == "Ready"
                    ),
                    None,
                ),
            }
            for item in services
        ],
    }


def _resource_fabric_snapshot() -> dict[str, Any]:
    try:
        from inneros_core_runtime import resource_fabric

        return resource_fabric.resource_fabric_status(limit=20)
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def dual_deployment_status(probe_http: bool = True, include_cloud: bool = True) -> dict[str, Any]:
    local_services = []
    for service in LOCAL_RUNTIME_SERVICES:
        systemd = _systemd_state(service["unit"])
        http = _http_status(service["local_url"]) if probe_http else {"status": "not_checked"}
        status = "up" if systemd.get("ok") and http.get("status") in {"up", "unauthorized_alive", "not_applicable"} else "degraded"
        if not systemd.get("ok"):
            status = "down"
        local_services.append({**service, "systemd": systemd, "http": http, "status": status})

    cloud_services = []
    if include_cloud:
        for surface in CLOUD_SURFACES:
            http = _http_status(surface["public_url"])
            cloud_services.append({**surface, "http": http, "status": http.get("status")})

    cloud_run = _gcloud_run_services() if include_cloud else {"status": "not_checked"}
    resource_fabric = _resource_fabric_snapshot()
    local_up = sum(1 for item in local_services if item["status"] == "up")
    cloud_up = sum(1 for item in cloud_services if item.get("status") in {"up", "unauthorized_alive"})
    overall = "up" if local_up >= 4 and (not include_cloud or cloud_up >= 1) else "degraded"
    if local_up == 0:
        overall = "down"

    return {
        "ok": overall in {"up", "degraded"},
        "overall": overall,
        "generated_at": _now(),
        "topology": {
            "cloud": {"provider": "gcp_cloud_run_cloudflare", "project": GCP_PROJECT, "region": GCP_REGION},
            "local": {
                "amd": {"host": AMD_NODE, "roles": ["gpu_inference", "mcp", "modules", "local_worker"]},
                "intel": {"host": INTEL_NODE, "roles": ["light_services", "ollama_fallback", "browser_review_when_enabled"]},
            },
        },
        "identity_contract": IDENTITY_CONTRACT,
        "offline_mode": OFFLINE_MODE,
        "local_services": local_services,
        "cloud_surfaces": cloud_services,
        "cloud_run": cloud_run,
        "resource_fabric": resource_fabric,
        "sync_contract": {
            "queue": "idempotent operation queue required before online reconciliation",
            "conflicts": "audit first; destructive resolution requires owner-approved policy",
            "current_status": "contract_ready; data-specific mirrors must declare ownership before PASS",
        },
        "pass_criteria": [
            "cloud surface responds or is unauthorized_alive",
            "local MCP/portal/model path responds",
            "same tenant/module entitlement contract is used on both sides",
            "offline mode never claims non-replicated cloud data",
            "recovery reconciliation records idempotency and conflicts",
        ],
    }
