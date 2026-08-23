"""AG-44 Cloud Deployer — GCP / Alibaba / Cloudflare (stub v1 + roadmap)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-44_CLOUD_DEPLOYER"
ROADMAP_DOC = Path("/home/rlopez/data/ai_coordination/HUB/ROADMAP_AGENTES_UNIVERSAL_2026-08-12.md")

PROVIDERS = {
    "gcp": {
        "label": "Google Cloud",
        "status": "stub",
        "targets": ["cloud_run", "gke", "secret_manager"],
        "cli": "gcloud",
        "owner_shared": "antigravity",
        "note": "FEMAR femar-mvp-core ya en Cloud Run — integrar pipeline MCP",
    },
    "alibaba": {
        "label": "Alibaba Cloud",
        "status": "planned",
        "targets": ["ecs", "ack", "oss"],
        "cli": "aliyun",
        "note": "Adapter pendiente — misma interfaz que GCP",
    },
    "cloudflare": {
        "label": "Cloudflare",
        "status": "operational_dns",
        "targets": ["tunnel_systemd", "dns_api", "waf_skip", "mcp_provision_subdomain"],
        "cli": "cloudflared / API / MCP cloudflare_provision_subdomain",
        "note": "Token completo en ~/.config/ralfia/cloudflare.env habilita WAF skip automático",
    },
}


def cloud_deploy_status() -> dict[str, Any]:
    gcp_project = os.getenv("GCP_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    cf_status: dict[str, Any] = {}
    try:
        from raphiia_openai import cloudflare_ops

        cf_status = cloudflare_ops.cloudflare_status()
    except Exception as exc:
        cf_status = {"ok": False, "error": str(exc)[:200]}
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "version": "v2_cloudflare_ops",
        "providers": PROVIDERS,
        "cloudflare": cf_status,
        "env_hints": {
            "gcp_project": gcp_project or "(not set — configure on server)",
            "gcloud_available": _which("gcloud"),
            "cloudflare_token_file": str(
                Path("/home/rlopez/.config/ralfia/cloudflare.env")
            ),
        },
        "roadmap_doc": str(ROADMAP_DOC),
        "next": [
            "CLOUDFLARE_API_TOKEN con DNS+WAF en ~/.config/ralfia/cloudflare.env",
            "MCP: cloudflare_provision_subdomain('foo', 'http://127.0.0.1:PORT')",
        ],
    }


def cloud_deploy_plan(
    provider: str = "gcp",
    service: str = "",
    environment: str = "staging",
) -> dict[str, Any]:
    provider = (provider or "gcp").strip().lower()
    meta = PROVIDERS.get(provider)
    if not meta:
        return {"ok": False, "error": "provider_unknown", "allowed": sorted(PROVIDERS.keys())}
    plan = {
        "provider": provider,
        "service": service or "(unspecified)",
        "environment": environment,
        "steps": [
            f"1. Validar credenciales {meta['cli']} en servidor (no en chat)",
            "2. local_exec: terraform plan en worktree infra/",
            "3. Revisión humana Rafael",
            "4. cloud_deploy_apply (futuro) con lock + evidencia",
            "5. AG-40 reconcile post-deploy",
        ],
        "status": meta["status"],
    }
    record_agent_run(AGENT_ID, action="cloud_deploy_plan", summary=f"{provider}/{service}", project="ralfia-ops")
    return {"ok": True, "agent_id": AGENT_ID, "plan": plan, "provider_meta": meta}


def get_development_roadmap() -> dict[str, Any]:
    if not ROADMAP_DOC.is_file():
        return {"ok": False, "error": "roadmap_missing", "path": str(ROADMAP_DOC)}
    text = ROADMAP_DOC.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "path": str(ROADMAP_DOC),
        "revision_hint": "see file header",
        "content": text[:12000],
        "truncated": len(text) > 12000,
    }


def _which(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None
