"""AG-44 Cloud Deployer — Cloudflare/GCP operations with server-side secrets."""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store, owner_vault
from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-44_CLOUD_DEPLOYER"
ROADMAP_DOC = Path("/home/rlopez/data/ai_coordination/HUB/ROADMAP_AGENTES_UNIVERSAL_2026-08-12.md")
CF_API_BASE = "https://api.cloudflare.com/client/v4"
CF_VAULT_CATEGORY = "cloudflare_pcdoctor_ai"
CF_DEFAULT_ZONE = "pcdoctor.ai"
CF_RULESET_PHASE = "http_request_firewall_custom"
AUDIT_COLLECTION = "ralfia_cloudflare_audit"
GENERIC_AUDIT_COLLECTION = "ralfia_cloud_ops_audit"
GCP_AUTH_REQUEST_COLLECTION = "ralfia_gcp_auth_requests"
GCP_ALLOWLIST_COLLECTION = "ralfia_gcp_allowlist"
_GCP_AUTH_PROCS: dict[str, subprocess.Popen[str]] = {}
_GCP_AUTH_URLS: dict[str, str] = {}
GCP_ALLOWED_IAM_ROLES = {
    "roles/aiplatform.user",
    "roles/artifactregistry.admin",
    "roles/artifactregistry.reader",
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/datastore.owner",
    "roles/logging.viewer",
    "roles/pubsub.admin",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/viewer",
}
GCP_ALLOWED_API_PREFIXES = {
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "firestore.googleapis.com",
    "logging.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
}

PROVIDERS = {
    "gcp": {
        "label": "Google Cloud",
        "status": "dry_run_ready",
        "targets": ["cloud_run", "gke", "secret_manager"],
        "cli": "gcloud",
        "owner_shared": "antigravity",
        "note": "Preflight/dry-run MCP disponible; apply requiere aprobacion explicita.",
    },
    "azure": {
        "label": "Microsoft Azure",
        "status": "dry_run_ready_if_cli_present",
        "targets": ["container_apps", "app_service", "key_vault"],
        "cli": "az",
        "note": "Adapter seguro: status/preflight/plan; apply requiere aprobacion explicita.",
    },
    "alibaba": {
        "label": "Alibaba Cloud",
        "status": "dry_run_ready_if_cli_present",
        "targets": ["ecs", "ack", "oss"],
        "cli": "aliyun",
        "note": "Adapter seguro: status/preflight/plan; apply requiere aprobacion explicita.",
    },
    "cloudflare": {
        "label": "Cloudflare",
        "status": "functional",
        "targets": ["dns_api", "waf_custom_rules", "tunnel_ingress_inspect", "health_checks", "rollback"],
        "cli": "Cloudflare API + cloudflared config inspection",
        "secret_source": f"owner_vault:{CF_VAULT_CATEGORY}",
        "note": "DNS/WAF/health/rollback cableados server-side; secretos no salen del host.",
    },
}


def cloud_deploy_status() -> dict[str, Any]:
    gcp_project = os.getenv("GCP_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    cf = cloudflare_status()
    providers_status = {name: cloud_provider_status(name) for name in PROVIDERS}
    return {
        "ok": bool(cf.get("ok")),
        "agent_id": AGENT_ID,
        "version": "cloud_control_plane_v0",
        "providers": PROVIDERS,
        "providers_status": providers_status,
        "env_hints": {
            "gcp_project": gcp_project or "(not set — configure on server)",
            "gcloud_available": _which("gcloud"),
            "azure_cli_available": _which("az"),
            "alibaba_cli_available": _which("aliyun"),
            "terraform_available": _which("terraform"),
            "docker_available": _which("docker"),
            "apply_enabled": _apply_enabled(),
        },
        "cloudflare": cf,
        "roadmap_doc": str(ROADMAP_DOC),
        "next": [
            "Use cloud_provider_status(provider) for provider-specific readiness.",
            "Use cloud_deploy_dry_run(provider, ...) before any cloud apply.",
            "cloud_deploy_apply is gated by RALFIA_CLOUD_APPLY_ENABLED=true plus approval_id.",
            "Use cloudflare_prepare_hostname(hostname, ...) for future pcdoctor.ai subdomains.",
            "Use cloudflare_waf_skip_challenge(hostname) for minimal hostname challenge bypass.",
            "Use cloudflare_dns_upsert/delete for allowlisted DNS changes.",
        ],
    }


def cloud_deploy_plan(provider: str = "gcp", service: str = "", environment: str = "staging") -> dict[str, Any]:
    provider = (provider or "gcp").strip().lower()
    meta = PROVIDERS.get(provider)
    if not meta:
        return {"ok": False, "error": "provider_unknown", "allowed": sorted(PROVIDERS.keys())}
    if provider == "cloudflare":
        plan = {
            "provider": provider,
            "service": service or "(hostname pending)",
            "environment": environment,
            "steps": [
                "1. Validate hostname belongs to the owner allowlist.",
                "2. Read Cloudflare secrets from owner_vault server-side.",
                "3. Optional DNS upsert/delete through Cloudflare API.",
                "4. Optional WAF skip rule scoped to http.host only.",
                "5. Inspect cloudflared tunnel ingress for hostname.",
                "6. Verify public HTTPS status and cf-mitigated header.",
                "7. Log audit event in Mongo with redacted evidence.",
            ],
            "tools": [
                "cloudflare_status",
                "cloudflare_dns_upsert",
                "cloudflare_dns_delete",
                "cloudflare_waf_skip_challenge",
                "cloudflare_waf_delete_hostname_rules",
                "cloudflare_tunnel_ingress_status",
                "cloudflare_hostname_health_check",
                "cloudflare_prepare_hostname",
            ],
            "status": meta["status"],
        }
    else:
        plan = {
            "provider": provider,
            "service": service or "(unspecified)",
            "environment": environment,
            "steps": [
                f"1. Validar credenciales {meta['cli']} en servidor (no en chat)",
                "2. local_exec: terraform plan en worktree infra/",
                "3. Revisión humana Rafael",
                "4. cloud_deploy_apply futuro con lock + evidencia",
                "5. AG-40 reconcile post-deploy",
            ],
            "status": meta["status"],
        }
    record_agent_run(AGENT_ID, action="cloud_deploy_plan", summary=f"{provider}/{service}", project="ralfia-ops")
    return {"ok": True, "agent_id": AGENT_ID, "plan": plan, "provider_meta": meta}


def cloud_provider_status(provider: str = "gcp") -> dict[str, Any]:
    """Read-only readiness check for one cloud provider."""
    provider = _normalize_provider(provider)
    meta = PROVIDERS[provider]
    cli = str(meta.get("cli") or "")
    cli_path = shutil.which(cli) if cli else None
    status: dict[str, Any] = {
        "ok": True,
        "agent_id": AGENT_ID,
        "provider": provider,
        "label": meta["label"],
        "cli": cli,
        "cli_available": bool(cli_path),
        "cli_path": cli_path,
        "apply_enabled": _apply_enabled(),
        "secret_policy": "server-side only; raw credentials are never returned",
    }
    if provider == "gcp":
        status.update(_gcp_readiness(cli_path))
    elif provider == "azure":
        status.update(_azure_readiness(cli_path))
    elif provider == "alibaba":
        status.update(_alibaba_readiness(cli_path))
    elif provider == "cloudflare":
        status["cloudflare"] = cloudflare_status()
    return status


def cloud_deploy_dry_run(
    provider: str,
    repo: str,
    service: str,
    environment: str = "staging",
    project_id: str = "",
    region: str = "",
    image: str = "",
    source_path: str = "",
) -> dict[str, Any]:
    """Build a provider-specific deploy plan without mutating cloud resources."""
    provider = _normalize_provider(provider)
    if not _valid_repo(repo):
        return {"ok": False, "error": "repo_must_be_owner_name"}
    if not _safe_name(service):
        return {"ok": False, "error": "service_name_invalid"}
    if environment not in {"dev", "staging", "hackathon", "prod", "production"}:
        return {"ok": False, "error": "environment_not_allowed"}
    readiness = cloud_provider_status(provider)
    commands = _provider_dry_run_commands(provider, service, environment, project_id, region, image, source_path)
    result = {
        "ok": True,
        "agent_id": AGENT_ID,
        "provider": provider,
        "repo": repo,
        "service": service,
        "environment": environment,
        "dry_run": True,
        "readiness": readiness,
        "commands": commands,
        "will_mutate": False,
        "apply_gate": {
            "enabled": _apply_enabled(),
            "requires_env": "RALFIA_CLOUD_APPLY_ENABLED=true",
            "requires_approval_id": True,
            "requires_human": "RAFAEL",
        },
        "next": [
            "Have ChatGPT commit deploy config through local_exec_* first.",
            "Run this dry-run again after credentials/project are configured.",
            "Use cloud_deploy_apply only after Rafael approval and server-side apply gate.",
        ],
    }
    _audit("cloud_deploy_dry_run", service, {"provider": provider, "repo": repo, "environment": environment, "project_id": project_id, "region": region})
    return result


def cloud_deploy_apply(
    provider: str,
    repo: str,
    service: str,
    approval_id: str,
    environment: str = "staging",
    project_id: str = "",
    region: str = "",
    image: str = "",
    source_path: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Guarded apply entrypoint. It is intentionally closed unless both gates are present."""
    plan = cloud_deploy_dry_run(provider, repo, service, environment, project_id, region, image, source_path)
    if dry_run:
        plan["apply_result"] = "dry_run_only"
        return plan
    if not _apply_enabled():
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "error": "cloud_apply_disabled",
            "hint": "Set RALFIA_CLOUD_APPLY_ENABLED=true server-side after Rafael approval.",
            "plan": plan,
        }
    if not _valid_approval_id(approval_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "approval_id_required"}
    return {
        "ok": False,
        "agent_id": AGENT_ID,
        "error": "provider_apply_not_implemented",
        "provider": _normalize_provider(provider),
        "approval_id": approval_id,
        "plan": plan,
        "next": "Implement the provider adapter command executor with RACB lock and post-deploy evidence before enabling mutations.",
    }


def gcp_auth_bootstrap() -> dict[str, Any]:
    """Report server-side GCP auth posture without returning credentials."""
    cli_path = shutil.which("gcloud")
    readiness = _gcp_readiness(cli_path)
    return {
        "ok": bool(readiness.get("auth", {}).get("ok")),
        "agent_id": AGENT_ID,
        "provider": "gcp",
        "auth_mode": "server_side_gcloud_or_owner_vault_service_account",
        "secret_policy": "credentials stay on server; raw values are never returned",
        "readiness": readiness,
        "next": [
            "Configure a service account or OAuth login on the server only.",
            "Set GCP_PROJECT_ID/GOOGLE_CLOUD_PROJECT and optional GCP_REGION.",
            "Set RALFIA_GCP_ALLOWED_PROJECTS_JSON and RALFIA_GCP_ALLOWED_BILLING_ACCOUNTS_JSON before apply.",
        ],
    }


def cloud_authorization_request(
    provider: str,
    purpose: str,
    project_id: str = "",
    requested_scopes: list[str] | None = None,
    risk_level: str = "moderate_write",
    target_agent: str = "CHATGPT",
) -> dict[str, Any]:
    """Create an owner-facing cloud authorization request without exposing secrets."""
    provider = _normalize_provider(provider)
    clean_purpose = (purpose or "").strip()[:1000]
    if not clean_purpose:
        return {"ok": False, "agent_id": AGENT_ID, "error": "purpose_required"}
    if risk_level not in {"read_only", "low_write", "moderate_write", "high_write"}:
        return {"ok": False, "agent_id": AGENT_ID, "error": "risk_level_invalid"}
    request_id = f"auth_{provider}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    owner_action = _cloud_owner_action(provider, project_id, requested_scopes or [], risk_level)
    if provider == "gcp":
        owner_action["mcp_flow"] = {
            "begin_tool": "gcp_auth_begin",
            "status_tool": "gcp_auth_status",
            "submit_tool": "gcp_auth_submit_code",
            "request_id": request_id,
            "account_hint": os.getenv("RALFIA_GCP_OWNER_ACCOUNT", "pcdoctorgye@gmail.com"),
            "secret_policy": "Only Google consent URL and one-time authorization code are handled; no password, token, service-account JSON, or private key is requested.",
        }
    doc = {
        "request_id": request_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent_id": AGENT_ID,
        "provider": provider,
        "purpose": clean_purpose,
        "project_id": project_id,
        "requested_scopes": requested_scopes or [],
        "risk_level": risk_level,
        "status": "pending_owner_authorization",
        "target_agent": target_agent,
        "owner_action": owner_action,
        "secret_policy": "owner authorizes on provider/server side; raw secrets never go through LLM messages",
    }
    try:
        mongo_store.get_db()[GENERIC_AUDIT_COLLECTION].insert_one({**doc, "action": "cloud_authorization_request"})
    except Exception:
        pass
    record_agent_run(AGENT_ID, action="cloud_authorization_request", summary=f"{provider}:{project_id or 'no-project'}", project="ralfia-cloud-ops")
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "request_id": request_id,
        "status": doc["status"],
        "provider": provider,
        "owner_action": owner_action,
        "next_for_chatgpt": [
            "Send this request_id and owner_action to Rafael.",
            "After Rafael authorizes server-side, call cloud_authorization_status(request_id).",
            "Then rerun provider status/preflight and only use apply tools with approval_id.",
        ],
    }


def gcp_auth_begin(
    request_id: str,
    account_hint: str = "",
    force: bool = False,
    update_adc: bool = True,
) -> dict[str, Any]:
    """Start a headless Google owner-consent flow and return only the consent URL."""
    clean = _valid_gcp_auth_request_id(request_id)
    if not clean:
        return {"ok": False, "agent_id": AGENT_ID, "error": "request_id_invalid"}
    cli_path = shutil.which("gcloud")
    if not cli_path:
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcloud_missing"}
    existing = _GCP_AUTH_PROCS.get(clean)
    if existing and existing.poll() is None:
        return _gcp_auth_status_from_process(clean, {"note": "auth_flow_already_running"})

    account = _clean_email(account_hint or os.getenv("RALFIA_GCP_OWNER_ACCOUNT", "pcdoctorgye@gmail.com"))
    argv = [cli_path, "auth", "login"]
    if account:
        argv.append(account)
    argv += ["--no-launch-browser"]
    if update_adc:
        argv.append("--update-adc")
    if force:
        argv.append("--force")

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcloud_auth_start_failed", "detail": str(exc)[:300]}

    _GCP_AUTH_PROCS[clean] = proc
    captured = _read_process_available(proc, timeout_sec=25.0)
    consent_url = _extract_google_auth_url(captured)
    if consent_url:
        _GCP_AUTH_URLS[clean] = consent_url
    status = "pending_owner_code" if consent_url and proc.poll() is None else "start_failed"
    evidence = {
        "request_id": clean,
        "provider": "gcp",
        "status": status,
        "account_hint": account,
        "update_adc": bool(update_adc),
        "force": bool(force),
        "has_consent_url": bool(consent_url),
        "consent_url": consent_url,
        "returncode": proc.poll(),
        "sanitized_output": _sanitize_gcloud_auth_output(captured),
    }
    _upsert_gcp_auth_request(clean, evidence)
    _audit_cloud_ops("gcp_auth_begin", {k: v for k, v in evidence.items() if k != "sanitized_output"})
    if not consent_url:
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "request_id": clean,
            "status": status,
            "error": "consent_url_not_found",
            "sanitized_output": evidence["sanitized_output"],
            "secret_policy": "No raw credentials returned.",
        }
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "request_id": clean,
        "provider": "gcp",
        "status": status,
        "account_hint": account,
        "consent_url": consent_url,
        "owner_action": [
            "Open consent_url in Rafael's browser and sign in with the owner Google account.",
            "Copy the one-time authorization code shown by Google.",
            "Submit it with gcp_auth_submit_code(request_id, authorization_code). Do not paste passwords, tokens, JSON keys, or private keys.",
        ],
        "next_for_chatgpt": [
            "Give Rafael only the consent_url and request_id.",
            "After Rafael provides the one-time authorization code, call gcp_auth_submit_code.",
            "Then poll gcp_auth_status and gcp_auth_bootstrap.",
        ],
        "secret_policy": "The authorization code is one-time owner consent; credentials are stored by gcloud server-side and never returned.",
    }


def gcp_auth_submit_code(request_id: str, authorization_code: str) -> dict[str, Any]:
    """Complete the pending headless gcloud auth flow with a one-time Google code."""
    clean = _valid_gcp_auth_request_id(request_id)
    if not clean:
        return {"ok": False, "agent_id": AGENT_ID, "error": "request_id_invalid"}
    code = (authorization_code or "").strip()
    if not code or len(code) > 4096 or "\n" in code or "\r" in code:
        return {"ok": False, "agent_id": AGENT_ID, "error": "authorization_code_invalid"}
    proc = _GCP_AUTH_PROCS.get(clean)
    if not proc or proc.poll() is not None or not proc.stdin:
        return {
            "ok": False,
            "agent_id": AGENT_ID,
            "request_id": clean,
            "error": "auth_flow_not_running",
            "status": gcp_auth_status(clean),
        }
    try:
        proc.stdin.write(code + "\n")
        proc.stdin.flush()
    except Exception as exc:
        return {"ok": False, "agent_id": AGENT_ID, "request_id": clean, "error": "authorization_code_submit_failed", "detail": str(exc)[:300]}

    captured = _read_process_available(proc, timeout_sec=90.0)
    readiness = cloud_provider_status("gcp")
    auth_ok = bool((readiness.get("auth") or {}).get("ok"))
    status = "authorized" if auth_ok else ("failed" if proc.poll() not in (None, 0) else "pending")
    evidence = {
        "request_id": clean,
        "provider": "gcp",
        "status": status,
        "authorization_ready": auth_ok,
        "returncode": proc.poll(),
        "sanitized_output": _sanitize_gcloud_auth_output(captured),
        "accounts_count": (readiness.get("auth") or {}).get("accounts_count"),
    }
    _upsert_gcp_auth_request(clean, evidence)
    _audit_cloud_ops("gcp_auth_submit_code", {k: v for k, v in evidence.items() if k != "sanitized_output"})
    if proc.poll() is not None:
        _GCP_AUTH_PROCS.pop(clean, None)
    return {
        "ok": auth_ok,
        "agent_id": AGENT_ID,
        "request_id": clean,
        "provider": "gcp",
        "status": status,
        "authorization_ready": auth_ok,
        "readiness": readiness,
        "sanitized_output": evidence["sanitized_output"],
        "secret_policy": "Authorization code was not stored or returned; gcloud credentials remain server-side.",
        "next": "Run gcp_auth_bootstrap, then GCP read/preflight tools. Writes still require allowlist and approval gates.",
    }


def gcp_auth_status(request_id: str) -> dict[str, Any]:
    """Poll a GCP owner-consent request without exposing credentials."""
    clean = _valid_gcp_auth_request_id(request_id)
    if not clean:
        return {"ok": False, "agent_id": AGENT_ID, "error": "request_id_invalid"}
    return _gcp_auth_status_from_process(clean)


def cloud_authorization_status(request_id: str) -> dict[str, Any]:
    """Check whether a cloud authorization request can proceed."""
    clean = (request_id or "").strip()
    if not re.fullmatch(r"auth_[a-z0-9_-]+_[0-9]{14}", clean):
        return {"ok": False, "agent_id": AGENT_ID, "error": "request_id_invalid"}
    provider = clean.split("_", 2)[1]
    if provider == "gcp":
        auth_flow = gcp_auth_status(clean)
    else:
        auth_flow = None
    status = cloud_provider_status(provider)
    auth_ok = bool((status.get("auth") or {}).get("ok")) if provider != "cloudflare" else bool((status.get("cloudflare") or status).get("ok"))
    return {
        "ok": auth_ok,
        "agent_id": AGENT_ID,
        "request_id": clean,
        "provider": provider,
        "authorization_ready": auth_ok,
        "auth_flow": auth_flow,
        "provider_status": status,
        "next": "Proceed with dry_run/apply gates only after authorization_ready=true and Rafael approval_id is present.",
    }


def gcp_list_projects() -> dict[str, Any]:
    cli_path = shutil.which("gcloud")
    if not cli_path:
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcloud_missing"}
    result = _run_readonly([cli_path, "projects", "list", "--format=json"], timeout=40)
    projects = _json_list(result.get("stdout"))
    return {
        "ok": bool(result.get("ok")),
        "agent_id": AGENT_ID,
        "provider": "gcp",
        "projects_count": len(projects),
        "projects": [_redact_gcp_project(p) for p in projects[:200]],
        "cli": result,
    }


def gcp_billing_accounts_list(open_only: bool = False) -> dict[str, Any]:
    result = _gcp_read_json("gcp_billing_accounts_list", ["billing", "accounts", "list", "--format=json"])
    accounts = result.get("data") if isinstance(result.get("data"), list) else (result.get("data", {}).get("items") if isinstance(result.get("data"), dict) else [])
    if not isinstance(accounts, list):
        accounts = []
    redacted = [_redact_billing_account(a) for a in accounts if not open_only or bool(a.get("open"))]
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "accounts_count": len(redacted), "accounts": redacted, "cli": result.get("cli")}


def gcp_list_billing_accounts(open_only: bool = False) -> dict[str, Any]:
    return gcp_billing_accounts_list(open_only=open_only)


def gcp_billing_projects_list(billing_account_id: str) -> dict[str, Any]:
    account = _normalize_billing_account_id(billing_account_id)
    if not account:
        return {"ok": False, "agent_id": AGENT_ID, "error": "billing_account_id_invalid"}
    return _gcp_read_json("gcp_billing_projects_list", ["billing", "projects", "list", "--billing-account", account, "--format=json"], timeout=60)


def gcp_project_billing_info(project_id: str) -> dict[str, Any]:
    if not _valid_gcp_project_id(project_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcp_project_id_invalid"}
    return _gcp_read_json("gcp_project_billing_info", ["billing", "projects", "describe", project_id, "--format=json"])


def gcp_get_project_billing(project_id: str) -> dict[str, Any]:
    return gcp_project_billing_info(project_id)


def gcp_billing_credits_status(billing_account_id: str = "") -> dict[str, Any]:
    account = _normalize_billing_account_id(billing_account_id)
    accounts = gcp_billing_accounts_list(open_only=False)
    budgets = gcp_budgets_list(account) if account else {"ok": False, "error": "billing_account_id_required_for_budgets"}
    return {"ok": bool(accounts.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "billing_account_id": account, "accounts": accounts.get("accounts", []), "budgets": budgets, "credits_visibility": {"ok": False, "reason": "gcloud does not expose promotional credit grant balances directly for this account surface", "safe_next": ["Use Google Cloud Console Billing > Credits for owner-visible grant details.", "Use budgets with credit_types_treatment to protect spend.", "If Billing Export to BigQuery is configured later, add a read-only cost/credit query tool against that dataset."]}, "secret_policy": "No credentials or payment instruments returned."}


def gcp_allowlist_project(project_id: str, approval_id: str, note: str = "", dry_run: bool = True) -> dict[str, Any]:
    if not _valid_gcp_project_id(project_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcp_project_id_invalid", "project_id": project_id}
    validation = _approval_validation("allowlist_project", approval_id, dry_run=dry_run)
    payload = {"kind": "project", "value": project_id, "approval_id": approval_id, "note": note[:300], "provider": "gcp"}
    if validation.get("ok") and not dry_run:
        _upsert_gcp_allowlist(payload)
    _audit_cloud_ops("gcp_allowlist_project", {"provider": "gcp", "validation": validation, **payload, "executed": bool(validation.get("ok") and not dry_run)})
    return {"ok": bool(validation.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "dry_run": dry_run, "validation": validation, "allowlisted": _gcp_project_allowed(project_id), "payload": payload}


def gcp_allowlist_billing_account(billing_account_id: str, approval_id: str, note: str = "", dry_run: bool = True) -> dict[str, Any]:
    account = _normalize_billing_account_id(billing_account_id)
    if not account:
        return {"ok": False, "agent_id": AGENT_ID, "error": "billing_account_id_invalid"}
    validation = _approval_validation("allowlist_billing_account", approval_id, dry_run=dry_run)
    payload = {"kind": "billing_account", "value": account, "approval_id": approval_id, "note": note[:300], "provider": "gcp"}
    if validation.get("ok") and not dry_run:
        _upsert_gcp_allowlist(payload)
    _audit_cloud_ops("gcp_allowlist_billing_account", {"provider": "gcp", "validation": validation, **payload, "executed": bool(validation.get("ok") and not dry_run)})
    return {"ok": bool(validation.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "dry_run": dry_run, "validation": validation, "allowlisted": _gcp_billing_allowed(account), "payload": payload}


def gcp_budgets_list(billing_account_id: str) -> dict[str, Any]:
    account = _normalize_billing_account_id(billing_account_id)
    if not account:
        return {"ok": False, "agent_id": AGENT_ID, "error": "billing_account_id_invalid"}
    return _gcp_read_json("gcp_budgets_list", ["beta", "billing", "budgets", "list", "--billing-account", account, *_gcp_billing_project_args(), "--format=json"], timeout=60)


def gcp_budget_list(billing_account_id: str) -> dict[str, Any]:
    return gcp_budgets_list(billing_account_id)


def gcp_budget_status(billing_account_id: str, budget_name: str = "") -> dict[str, Any]:
    budgets = gcp_budgets_list(billing_account_id)
    data = budgets.get("data")
    items = data if isinstance(data, list) else (data or {}).get("items", [])
    if budget_name:
        needle = budget_name.strip()
        items = [item for item in items if item.get("name") == needle or item.get("displayName") == needle]
    return {
        "ok": bool(budgets.get("ok")),
        "agent_id": AGENT_ID,
        "provider": "gcp",
        "billing_account_id": _normalize_billing_account_id(billing_account_id),
        "budgets_count": len(items),
        "budgets": items,
        "source": "gcloud beta billing budgets list",
        "cli": budgets.get("cli"),
    }


def gcp_budget_create(billing_account_id: str, display_name: str, amount: str, threshold_percents: list[float] | None = None, credit_types_treatment: str = "include-all-credits", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    account = _normalize_billing_account_id(billing_account_id)
    if not account:
        return {"ok": False, "agent_id": AGENT_ID, "error": "billing_account_id_invalid"}
    validation = _approval_validation("budget_create", approval_id, dry_run=dry_run) if _gcp_billing_allowed(account) else {"ok": False, "error": "gcp_billing_account_not_allowlisted"}
    clean_name = (display_name or "").strip()[:60]
    clean_amount = (amount or "").strip().upper()
    if not clean_name:
        validation = {"ok": False, "error": "display_name_required"}
    if not re.fullmatch(r"\d+(\.\d{1,2})?[A-Z]{3}", clean_amount):
        validation = {"ok": False, "error": "amount_must_look_like_100USD"}
    argv = ["gcloud", "beta", "billing", "budgets", "create", "--billing-account", account, *_gcp_billing_project_args(), "--display-name", clean_name, "--budget-amount", clean_amount, "--credit-types-treatment", credit_types_treatment]
    for pct in threshold_percents or [0.5, 0.9, 1.0]:
        argv += ["--threshold-rule", f"percent={float(pct):.2f}"]
    return _gcp_candidate("gcp_budget_create", validation, argv, mutates=True)


def gcp_costs_query(billing_account_id: str = "", project_id: str = "", days: int = 30) -> dict[str, Any]:
    return {"ok": False, "agent_id": AGENT_ID, "provider": "gcp", "billing_account_id": _normalize_billing_account_id(billing_account_id), "project_id": project_id, "days": max(1, min(int(days or 30), 366)), "error": "billing_export_not_configured", "safe_next": "Configure Cloud Billing export to BigQuery, then expose a read-only query tool for exact cost/credit consumption.", "fallback_tools": ["gcp_billing_accounts_list", "gcp_budgets_list", "gcp_billing_credits_status"]}


def gcp_billing_cost_summary(billing_account_id: str = "", project_id: str = "", days: int = 30) -> dict[str, Any]:
    return gcp_costs_query(billing_account_id=billing_account_id, project_id=project_id, days=days)


def gcp_quotas_list(project_id: str, service: str = "run.googleapis.com", limit: int = 100) -> dict[str, Any]:
    if not _valid_gcp_project_id(project_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcp_project_id_invalid"}
    return _gcp_read_json("gcp_quotas_list", ["alpha", "services", "quota", "list", "--service", service, "--consumer", f"projects/{project_id}", "--limit", str(max(1, min(int(limit or 100), 500))), "--format=json"], timeout=80)


def gcp_project_iam_policy(project_id: str) -> dict[str, Any]:
    if not _valid_gcp_project_id(project_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcp_project_id_invalid"}
    return _gcp_read_json("gcp_project_iam_policy", ["projects", "get-iam-policy", project_id, "--format=json"], timeout=60)


def gcp_project_iam_add_binding(project_id: str, member: str, role: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("project_iam_add_binding", project_id, approval_id, dry_run=dry_run)
    if role not in GCP_ALLOWED_IAM_ROLES:
        validation = {"ok": False, "error": "iam_role_not_allowlisted", "allowed_roles": sorted(GCP_ALLOWED_IAM_ROLES)}
    if not re.fullmatch(r"(user|serviceAccount|group):[A-Za-z0-9_.%+@-]+", (member or "").strip()):
        validation = {"ok": False, "error": "iam_member_invalid"}
    return _gcp_candidate("gcp_project_iam_add_binding", validation, ["gcloud", "projects", "add-iam-policy-binding", project_id, "--member", member, "--role", role], mutates=True)


def gcp_artifact_registry_list(project_id: str, region: str = "") -> dict[str, Any]:
    if not _valid_gcp_project_id(project_id):
        return {"ok": False, "agent_id": AGENT_ID, "error": "gcp_project_id_invalid"}
    return _gcp_read_json("gcp_artifact_registry_list", ["artifacts", "repositories", "list", "--project", project_id, "--location", _gcp_region(region), "--format=json"], timeout=60)


def gcp_artifact_registry_create(project_id: str, repository: str, region: str = "", format: str = "docker", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("artifact_registry_create", project_id, approval_id, dry_run=dry_run)
    if not _safe_name(repository):
        validation = {"ok": False, "error": "repository_name_invalid"}
    if format not in {"docker", "npm", "python", "maven", "apt", "yum"}:
        validation = {"ok": False, "error": "artifact_format_not_allowed"}
    return _gcp_candidate("gcp_artifact_registry_create", validation, ["gcloud", "artifacts", "repositories", "create", repository, "--project", project_id, "--location", _gcp_region(region), "--repository-format", format], mutates=True)


def gcp_project_setup_preflight(project_id: str, billing_account_id: str = "", apis: list[str] | None = None, region: str = "") -> dict[str, Any]:
    account = _normalize_billing_account_id(billing_account_id)
    api_list = [api.strip() for api in (apis or []) if api and api.strip()]
    return {"ok": True, "agent_id": AGENT_ID, "provider": "gcp", "project_id": project_id, "region": _gcp_region(region), "auth": cloud_provider_status("gcp").get("auth"), "project_id_valid": _valid_gcp_project_id(project_id), "project_allowlisted": _gcp_project_allowed(project_id), "billing_account_id": account, "billing_allowlisted": _gcp_billing_allowed(account) if account else None, "apis_allowed": sorted(set(api_list) & GCP_ALLOWED_API_PREFIXES), "apis_blocked": sorted(set(api_list) - GCP_ALLOWED_API_PREFIXES), "apply_gate": {"requires": ["RALFIA_CLOUD_APPLY_ENABLED=true", "valid approval_id", "allowlisted project/billing"], "current_apply_enabled": _apply_enabled()}}


def gcp_create_project(project_id: str, name: str = "", billing_account_id: str = "", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("create_project", project_id, approval_id, dry_run=dry_run, billing_account_id=billing_account_id)
    command = ["gcloud", "projects", "create", project_id, "--name", name or project_id]
    return _gcp_candidate("gcp_create_project", validation, command, mutates=True)


def gcp_link_billing(project_id: str, billing_account_id: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("link_billing", project_id, approval_id, dry_run=dry_run, billing_account_id=billing_account_id)
    command = ["gcloud", "billing", "projects", "link", project_id, "--billing-account", billing_account_id]
    return _gcp_candidate("gcp_link_billing", validation, command, mutates=True)


def gcp_enable_apis(project_id: str, apis: list[str], dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    clean_apis = [api.strip() for api in (apis or []) if api and api.strip()]
    blocked = [api for api in clean_apis if api not in GCP_ALLOWED_API_PREFIXES]
    validation = _gcp_apply_validation("enable_apis", project_id, approval_id, dry_run=dry_run)
    if blocked:
        validation = {"ok": False, "error": "gcp_api_not_allowlisted", "blocked": blocked, "allowed": sorted(GCP_ALLOWED_API_PREFIXES)}
    command = ["gcloud", "services", "enable", *clean_apis, "--project", project_id]
    return _gcp_candidate("gcp_enable_apis", validation, command, mutates=True)


def gcp_cloud_run_status(project_id: str, service: str, region: str = "") -> dict[str, Any]:
    return _gcp_read_json("gcp_cloud_run_status", ["run", "services", "describe", service, "--region", _gcp_region(region), "--project", project_id, "--format=json"])


def gcp_cloud_run_deploy(project_id: str, service: str, image: str, region: str = "", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("cloud_run_deploy", project_id, approval_id, dry_run=dry_run)
    if not _safe_name(service):
        validation = {"ok": False, "error": "service_name_invalid"}
    command = ["gcloud", "run", "deploy", service, "--image", image, "--region", _gcp_region(region), "--project", project_id, "--platform", "managed"]
    return _gcp_candidate("gcp_cloud_run_deploy", validation, command, mutates=True)


def gcp_cloud_run_revisions(project_id: str, service: str, region: str = "") -> dict[str, Any]:
    return _gcp_read_json("gcp_cloud_run_revisions", ["run", "revisions", "list", "--service", service, "--region", _gcp_region(region), "--project", project_id, "--format=json"])


def gcp_cloud_run_traffic(project_id: str, service: str, region: str = "") -> dict[str, Any]:
    return _gcp_read_json("gcp_cloud_run_traffic", ["run", "services", "describe", service, "--region", _gcp_region(region), "--project", project_id, "--format=json"], selector="traffic")


def gcp_cloud_run_rollback(project_id: str, service: str, revision: str, region: str = "", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("cloud_run_rollback", project_id, approval_id, dry_run=dry_run)
    command = ["gcloud", "run", "services", "update-traffic", service, "--to-revisions", f"{revision}=100", "--region", _gcp_region(region), "--project", project_id]
    return _gcp_candidate("gcp_cloud_run_rollback", validation, command, mutates=True)


def gcp_logs_query(project_id: str, query: str = "", limit: int = 50) -> dict[str, Any]:
    clean_limit = max(1, min(int(limit or 50), 200))
    log_filter = query or 'resource.type="cloud_run_revision"'
    return _gcp_read_json("gcp_logs_query", ["logging", "read", log_filter, "--project", project_id, "--limit", str(clean_limit), "--format=json"], timeout=60)


def gcp_secret_manager_metadata(project_id: str, secret_id: str) -> dict[str, Any]:
    return _gcp_read_json("gcp_secret_manager_metadata", ["secrets", "describe", secret_id, "--project", project_id, "--format=json"])


def gcp_secret_manager_create_version(project_id: str, secret_id: str, secret_ref: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    if not secret_ref or any(marker in secret_ref.lower() for marker in ("-----begin", "password=", "token=", "secret=")):
        return {"ok": False, "agent_id": AGENT_ID, "error": "secret_ref_required_no_raw_secret", "hint": "Pass an owner_vault reference, never the raw value."}
    validation = _gcp_apply_validation("secret_manager_create_version", project_id, approval_id, dry_run=dry_run)
    command = ["gcloud", "secrets", "versions", "add", secret_id, "--data-file", f"owner_vault:{secret_ref}", "--project", project_id]
    return _gcp_candidate("gcp_secret_manager_create_version", validation, command, mutates=True)


def gcp_firestore_status(project_id: str) -> dict[str, Any]:
    return _gcp_read_json("gcp_firestore_status", ["firestore", "databases", "list", "--project", project_id, "--format=json"])


def gcp_firestore_create_db(project_id: str, database: str = "(default)", location: str = "nam5", dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("firestore_create_db", project_id, approval_id, dry_run=dry_run)
    command = ["gcloud", "firestore", "databases", "create", "--database", database, "--location", location, "--project", project_id]
    return _gcp_candidate("gcp_firestore_create_db", validation, command, mutates=True)


def gcp_pubsub_list(project_id: str) -> dict[str, Any]:
    topics = _gcp_read_json("gcp_pubsub_topics", ["pubsub", "topics", "list", "--project", project_id, "--format=json"])
    subs = _gcp_read_json("gcp_pubsub_subscriptions", ["pubsub", "subscriptions", "list", "--project", project_id, "--format=json"])
    return {"ok": bool(topics.get("ok")) and bool(subs.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "topics": topics, "subscriptions": subs}


def gcp_pubsub_create_topic(project_id: str, topic: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("pubsub_create_topic", project_id, approval_id, dry_run=dry_run)
    command = ["gcloud", "pubsub", "topics", "create", topic, "--project", project_id]
    return _gcp_candidate("gcp_pubsub_create_topic", validation, command, mutates=True)


def gcp_pubsub_create_subscription(project_id: str, topic: str, subscription: str, dry_run: bool = True, approval_id: str = "") -> dict[str, Any]:
    validation = _gcp_apply_validation("pubsub_create_subscription", project_id, approval_id, dry_run=dry_run)
    command = ["gcloud", "pubsub", "subscriptions", "create", subscription, "--topic", topic, "--project", project_id]
    return _gcp_candidate("gcp_pubsub_create_subscription", validation, command, mutates=True)


def gcp_gemini_or_vertex_status(project_id: str = "", region: str = "") -> dict[str, Any]:
    project = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
    status = cloud_provider_status("gcp")
    enabled = _gcp_read_json("gcp_vertex_services", ["services", "list", "--enabled", "--filter", "aiplatform.googleapis.com", "--project", project, "--format=json"]) if project else {"ok": False, "error": "project_required"}
    return {"ok": bool(status.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "region": _gcp_region(region), "readiness": status, "vertex_api": enabled}


def gcp_service_health_check(project_id: str, service: str, region: str = "", path: str = "/") -> dict[str, Any]:
    svc = gcp_cloud_run_status(project_id, service, region)
    url = ((svc.get("data") or {}).get("status") or {}).get("url", "")
    if not url:
        return {"ok": False, "agent_id": AGENT_ID, "error": "service_url_not_found", "service_status": svc}
    target = url.rstrip("/") + "/" + (path or "/").lstrip("/")
    try:
        with urllib.request.urlopen(target, timeout=15) as resp:
            return {"ok": 200 <= resp.status < 500, "agent_id": AGENT_ID, "url": target, "status": resp.status, "headers": dict(resp.headers)}
    except Exception as exc:
        return {"ok": False, "agent_id": AGENT_ID, "url": target, "error": str(exc)[:300], "service_status": svc}


def cloudflare_status(zone_name: str = CF_DEFAULT_ZONE) -> dict[str, Any]:
    try:
        creds = _cloudflare_credentials()
        zone = _get_zone(zone_name, creds=creds)
        ruleset = _get_or_create_custom_ruleset(zone["id"], creds=creds, create=False)
        dns_permission = {"ok": True, "records_count": None}
        try:
            dns_permission["records_count"] = _cf_request("GET", f"/zones/{zone['id']}/dns_records?per_page=1", creds=creds).get("result_info", {}).get("total_count")
        except RuntimeError as exc:
            dns_permission = {"ok": False, "error": _classify_cloudflare_auth_error(str(exc))}
        return {
            "ok": True,
            "agent_id": AGENT_ID,
            "provider": "cloudflare",
            "zone": {"name": zone.get("name"), "id": zone.get("id")},
            "account_id": creds["account_id"],
            "vault_category": CF_VAULT_CATEGORY,
            "custom_ruleset": _redact_ruleset(ruleset) if ruleset else None,
            "dns_permission": dns_permission,
            "secret_policy": "owner_vault server-side only; raw values never returned",
        }
    except Exception as exc:
        return {"ok": False, "agent_id": AGENT_ID, "provider": "cloudflare", "error": str(exc), "secret_policy": "redacted"}


def cloudflare_dns_upsert(
    hostname: str,
    record_type: str,
    content: str,
    *,
    proxied: bool = True,
    ttl: int = 1,
    zone_name: str = CF_DEFAULT_ZONE,
    dry_run: bool = False,
) -> dict[str, Any]:
    host = _validate_hostname(hostname, zone_name)
    rtype = (record_type or "").strip().upper()
    if rtype not in {"A", "AAAA", "CNAME", "TXT"}:
        return {"ok": False, "error": "record_type_not_allowed", "allowed": ["A", "AAAA", "CNAME", "TXT"]}
    if not content.strip():
        return {"ok": False, "error": "content_required"}
    creds = _cloudflare_credentials()
    zone = _get_zone(zone_name, creds=creds)
    payload = {
        "type": rtype,
        "name": host,
        "content": content.strip(),
        "ttl": int(ttl or 1),
        "proxied": bool(proxied) if rtype in {"A", "AAAA", "CNAME"} else False,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "action": "upsert", "zone": zone["name"], "record": _redact_dns(payload), "note": "dry_run does not read existing DNS records"}
    existing = _find_dns_record(zone["id"], host, rtype, creds=creds)
    action = "update" if existing else "create"
    if existing:
        result = _cf_request("PATCH", f"/zones/{zone['id']}/dns_records/{existing['id']}", body=payload, creds=creds).get("result")
    else:
        result = _cf_request("POST", f"/zones/{zone['id']}/dns_records", body=payload, creds=creds).get("result")
    _audit("dns_upsert", host, {"action": action, "record_type": rtype, "proxied": payload["proxied"], "ttl": payload["ttl"]})
    return {"ok": True, "action": action, "zone": zone["name"], "record": _redact_dns(result)}


def cloudflare_dns_delete(hostname: str, record_type: str = "", zone_name: str = CF_DEFAULT_ZONE, dry_run: bool = False) -> dict[str, Any]:
    host = _validate_hostname(hostname, zone_name)
    rtype = (record_type or "").strip().upper()
    creds = _cloudflare_credentials()
    zone = _get_zone(zone_name, creds=creds)
    records = _list_dns_records(zone["id"], host, rtype or None, creds=creds)
    if dry_run:
        return {"ok": True, "dry_run": True, "matches": [_redact_dns(r) for r in records], "count": len(records)}
    deleted = []
    for record in records:
        _cf_request("DELETE", f"/zones/{zone['id']}/dns_records/{record['id']}", creds=creds)
        deleted.append(_redact_dns(record))
    _audit("dns_delete", host, {"record_type": rtype or "*", "deleted_count": len(deleted)})
    return {"ok": True, "deleted_count": len(deleted), "deleted": deleted}


def cloudflare_waf_skip_challenge(hostname: str, *, zone_name: str = CF_DEFAULT_ZONE, dry_run: bool = False, note: str = "") -> dict[str, Any]:
    host = _validate_hostname(hostname, zone_name)
    creds = _cloudflare_credentials()
    zone = _get_zone(zone_name, creds=creds)
    ruleset = _get_or_create_custom_ruleset(zone["id"], creds=creds, create=not dry_run)
    existing_rules = list((ruleset or {}).get("rules") or [])
    expression = f'(http.host eq "{host}")'
    desc = f"ralfia AG-44 skip Cloudflare challenges for {host}"
    existing = next((r for r in existing_rules if r.get("expression") == expression and r.get("action") == "skip"), None)
    rule = {
        "action": "skip",
        "description": desc,
        "enabled": True,
        "expression": expression,
        "logging": {"enabled": True},
        "action_parameters": {
            "ruleset": "current",
            "phases": ["http_request_firewall_managed", "http_ratelimit", "http_request_sbfm"],
            "products": ["waf", "securityLevel", "bic", "uaBlock", "zoneLockdown", "rateLimit"],
        },
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "zone": zone["name"], "would_update": bool(existing), "rule": _redact_rule(rule)}
    if existing:
        rule["id"] = existing["id"]
        new_rules = [rule if r.get("id") == existing["id"] else r for r in existing_rules]
        action = "updated"
    else:
        new_rules = [rule] + existing_rules
        action = "created"
    updated = _cf_request("PUT", f"/zones/{zone['id']}/rulesets/{ruleset['id']}", body={**ruleset, "rules": new_rules}, creds=creds).get("result")
    saved = next((r for r in updated.get("rules", []) if r.get("expression") == expression and r.get("action") == "skip"), rule)
    _audit("waf_skip_challenge", host, {"action": action, "rule_id": saved.get("id"), "note": note[:200]})
    return {"ok": True, "action": action, "zone": zone["name"], "ruleset_id": updated.get("id"), "rule": _redact_rule(saved)}


def cloudflare_waf_delete_hostname_rules(hostname: str, zone_name: str = CF_DEFAULT_ZONE, dry_run: bool = True) -> dict[str, Any]:
    host = _validate_hostname(hostname, zone_name)
    creds = _cloudflare_credentials()
    zone = _get_zone(zone_name, creds=creds)
    ruleset = _get_or_create_custom_ruleset(zone["id"], creds=creds, create=False)
    if not ruleset:
        return {"ok": True, "deleted_count": 0, "message": "custom_ruleset_missing"}
    expression = f'(http.host eq "{host}")'
    rules = list(ruleset.get("rules") or [])
    matches = [r for r in rules if r.get("expression") == expression]
    if dry_run:
        return {"ok": True, "dry_run": True, "matches": [_redact_rule(r) for r in matches], "count": len(matches)}
    kept = [r for r in rules if r.get("expression") != expression]
    updated = _cf_request("PUT", f"/zones/{zone['id']}/rulesets/{ruleset['id']}", body={**ruleset, "rules": kept}, creds=creds).get("result")
    _audit("waf_delete_hostname_rules", host, {"deleted_count": len(matches), "ruleset_id": updated.get("id")})
    return {"ok": True, "deleted_count": len(matches), "ruleset_id": updated.get("id")}


def cloudflare_tunnel_ingress_status(hostname: str = "", config_path: str = "") -> dict[str, Any]:
    paths = [Path(config_path)] if config_path else sorted(Path("/home/rlopez/.cloudflared").glob("*.yml")) + sorted(Path("/home/rlopez/.cloudflared").glob("*.yaml"))
    host = (hostname or "").strip().lower()
    matches = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        tunnel = _extract_yaml_scalar(text, "tunnel")
        for item in _extract_ingress(text):
            if host and item.get("hostname") != host:
                continue
            matches.append({"config_path": str(path), "tunnel": tunnel, **item})
    return {"ok": True, "hostname": host or None, "count": len(matches), "matches": matches}


def cloudflare_hostname_health_check(hostname: str, *, path: str = "/", timeout: float = 12.0) -> dict[str, Any]:
    host = _validate_hostname(hostname, CF_DEFAULT_ZONE)
    url = f"https://{host}{path if path.startswith('/') else '/' + path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ralfia-ag44-health/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(20000).decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            title = ""
            match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()[:120]
            return {
                "ok": 200 <= resp.status < 400 and headers.get("cf-mitigated", "").lower() != "challenge",
                "url": url,
                "status": resp.status,
                "cf_mitigated": headers.get("cf-mitigated"),
                "server": headers.get("server"),
                "content_type": headers.get("content-type"),
                "title": title,
                "body_preview": body[:180],
            }
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in exc.headers.items()}
        return {"ok": False, "url": url, "status": exc.code, "cf_mitigated": headers.get("cf-mitigated"), "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def cloudflare_prepare_hostname(
    hostname: str,
    *,
    dns_type: str = "",
    dns_content: str = "",
    proxied: bool = True,
    ensure_waf_skip: bool = True,
    health_path: str = "/",
    dry_run: bool = False,
) -> dict[str, Any]:
    host = _validate_hostname(hostname, CF_DEFAULT_ZONE)
    steps: list[dict[str, Any]] = []
    if dns_type or dns_content:
        if not dns_type or not dns_content:
            return {"ok": False, "error": "dns_type_and_dns_content_required_together"}
        steps.append({"step": "dns_upsert", "result": cloudflare_dns_upsert(host, dns_type, dns_content, proxied=proxied, dry_run=dry_run)})
    if ensure_waf_skip:
        steps.append({"step": "waf_skip_challenge", "result": cloudflare_waf_skip_challenge(host, dry_run=dry_run, note="cloudflare_prepare_hostname")})
    steps.append({"step": "tunnel_ingress_status", "result": cloudflare_tunnel_ingress_status(host)})
    if not dry_run:
        steps.append({"step": "health_check", "result": cloudflare_hostname_health_check(host, path=health_path)})
    ok = all(step["result"].get("ok") for step in steps if step["step"] != "tunnel_ingress_status")
    _audit("prepare_hostname", host, {"dry_run": dry_run, "dns_type": dns_type, "ensure_waf_skip": ensure_waf_skip, "ok": ok})
    return {"ok": ok, "hostname": host, "dry_run": dry_run, "steps": steps}


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


def _cloudflare_credentials() -> dict[str, str]:
    def get(key: str) -> str:
        res = owner_vault.get_owner_credential(key, category=CF_VAULT_CATEGORY, reveal=True, actor="RAFAEL")
        return str(res.get("secret") or "").strip()

    account_id = get("cloudflare_account_id")
    token = get("cloudflare_api_token")
    if not account_id or not token:
        raise RuntimeError(f"cloudflare_credentials_missing:{CF_VAULT_CATEGORY}")
    return {"account_id": account_id, "token": token}


def _cf_request(method: str, path: str, *, body: dict[str, Any] | None = None, creds: dict[str, str] | None = None) -> dict[str, Any]:
    creds = creds or _cloudflare_credentials()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        CF_API_BASE + path,
        data=data,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {creds['token']}",
            "Content-Type": "application/json",
            "User-Agent": "ralfia-ag44-cloud-deployer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"cloudflare_api_http_{exc.code}:{detail}") from exc
    if not payload.get("success", False):
        raise RuntimeError(f"cloudflare_api_error:{payload.get('errors') or payload}")
    return payload


def _get_zone(zone_name: str, *, creds: dict[str, str]) -> dict[str, Any]:
    zone = _validate_zone(zone_name)
    query = urllib.parse.urlencode({"name": zone, "account.id": creds["account_id"]})
    data = _cf_request("GET", f"/zones?{query}", creds=creds)
    results = data.get("result") or []
    if not results:
        raise RuntimeError(f"zone_not_found:{zone}")
    return results[0]


def _get_or_create_custom_ruleset(zone_id: str, *, creds: dict[str, str], create: bool) -> dict[str, Any] | None:
    try:
        data = _cf_request("GET", f"/zones/{zone_id}/rulesets/phases/{CF_RULESET_PHASE}/entrypoint", creds=creds)
        result = data.get("result")
        if result:
            return result
    except RuntimeError as exc:
        if "cloudflare_api_http_404" not in str(exc):
            raise
    if not create:
        return None
    return _cf_request(
        "POST",
        f"/zones/{zone_id}/rulesets",
        body={"name": "default", "description": "Ralphi IA custom firewall rules", "kind": "zone", "phase": CF_RULESET_PHASE, "rules": []},
        creds=creds,
    ).get("result")


def _find_dns_record(zone_id: str, hostname: str, record_type: str, *, creds: dict[str, str]) -> dict[str, Any] | None:
    records = _list_dns_records(zone_id, hostname, record_type, creds=creds)
    return records[0] if records else None


def _list_dns_records(zone_id: str, hostname: str, record_type: str | None, *, creds: dict[str, str]) -> list[dict[str, Any]]:
    qs = {"name": hostname, "per_page": "100"}
    if record_type:
        qs["type"] = record_type
    data = _cf_request("GET", f"/zones/{zone_id}/dns_records?{urllib.parse.urlencode(qs)}", creds=creds)
    return list(data.get("result") or [])


def _validate_zone(zone_name: str) -> str:
    zone = (zone_name or CF_DEFAULT_ZONE).strip().lower().rstrip(".")
    if zone != CF_DEFAULT_ZONE:
        raise ValueError(f"zone_not_allowlisted:{zone}")
    return zone


def _validate_hostname(hostname: str, zone_name: str) -> str:
    zone = _validate_zone(zone_name)
    host = (hostname or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ValueError("hostname_invalid")
    if host != zone and not host.endswith("." + zone):
        raise ValueError(f"hostname_not_allowlisted:{host}")
    return host


def _normalize_provider(provider: str) -> str:
    value = (provider or "gcp").strip().lower()
    aliases = {"google": "gcp", "google-cloud": "gcp", "azure": "azure", "aliyun": "alibaba", "ali": "alibaba", "cloudflare": "cloudflare"}
    value = aliases.get(value, value)
    if value not in PROVIDERS:
        raise ValueError(f"provider_unknown:{value}")
    return value


def _safe_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,80}", (value or "").strip()))


def _gcp_region(region: str = "") -> str:
    return (region or os.getenv("GCP_REGION") or "us-central1").strip()


def _gcp_billing_project_args() -> list[str]:
    project = (
        os.getenv("GCP_BILLING_QUOTA_PROJECT")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT_ID")
        or "pc-doctor-gcp"
    ).strip()
    return ["--billing-project", project] if project else []


def _json_list(text: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(text or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _json_obj(text: str | None) -> dict[str, Any]:
    try:
        data = json.loads(text or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {"items": data}


def _redact_gcp_project(project: dict[str, Any]) -> dict[str, Any]:
    return {k: project.get(k) for k in ("projectId", "name", "projectNumber", "lifecycleState", "createTime") if k in project}


def _normalize_billing_account_id(value: str) -> str:
    raw = (value or "").strip()
    return raw.removeprefix("billingAccounts/")


def _redact_billing_account(account: dict[str, Any]) -> dict[str, Any]:
    name = str(account.get("name") or "")
    normalized = _normalize_billing_account_id(name)
    return {
        "name": f"billingAccounts/{normalized}" if normalized else name,
        "billingAccountId": normalized,
        "displayName": account.get("displayName"),
        "open": account.get("open"),
        "currencyCode": account.get("currencyCode"),
        "masterBillingAccount": account.get("masterBillingAccount") or "",
    }


def _valid_gcp_project_id(project_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", (project_id or "").strip()))


def _allowed_json_env(name: str) -> set[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except Exception:
        return set()
    if isinstance(data, list):
        return {str(item) for item in data}
    return set()


def _gcp_project_allowed(project_id: str) -> bool:
    allowed = _allowed_json_env("RALFIA_GCP_ALLOWED_PROJECTS_JSON")
    if project_id in allowed:
        return True
    if project_id in _mongo_allowlist_values("project"):
        return True
    prefixes = [p.strip() for p in os.getenv("RALFIA_GCP_ALLOWED_PROJECT_PREFIXES", "innerops-,ralfia-,pcdoctor-").split(",") if p.strip()]
    return any(project_id.startswith(prefix) for prefix in prefixes)


def _gcp_billing_allowed(billing_account_id: str) -> bool:
    account = _normalize_billing_account_id(billing_account_id)
    if not account:
        return True
    allowed = _allowed_json_env("RALFIA_GCP_ALLOWED_BILLING_ACCOUNTS_JSON")
    return account in allowed or account in _mongo_allowlist_values("billing_account")


def _mongo_allowlist_values(kind: str) -> set[str]:
    try:
        docs = mongo_store.get_db()[GCP_ALLOWLIST_COLLECTION].find({"kind": kind, "active": {"$ne": False}}, {"_id": 0, "value": 1})
        return {str(doc.get("value")) for doc in docs if doc.get("value")}
    except Exception:
        return set()


def _upsert_gcp_allowlist(payload: dict[str, Any]) -> None:
    try:
        now = datetime.now(timezone.utc).isoformat()
        mongo_store.get_db()[GCP_ALLOWLIST_COLLECTION].update_one(
            {"kind": payload["kind"], "value": payload["value"]},
            {"$set": {**payload, "active": True, "updated_at": now}, "$setOnInsert": {"created_at": now, "agent_id": AGENT_ID}},
            upsert=True,
        )
    except Exception:
        pass


def _approval_validation(action: str, approval_id: str, *, dry_run: bool) -> dict[str, Any]:
    auth = _gcp_readiness(shutil.which("gcloud")).get("auth", {})
    if not auth.get("ok"):
        return {"ok": False, "error": "gcp_auth_required", "auth": auth}
    if dry_run:
        return {"ok": True, "dry_run": True, "action": action}
    if not _valid_approval_id(approval_id):
        return {"ok": False, "error": "approval_id_required"}
    return {"ok": True, "dry_run": False, "action": action, "approval_id": approval_id}


def _gcp_apply_validation(action: str, project_id: str, approval_id: str, *, dry_run: bool, billing_account_id: str = "") -> dict[str, Any]:
    if not _valid_gcp_project_id(project_id):
        return {"ok": False, "error": "gcp_project_id_invalid", "project_id": project_id}
    if not _gcp_project_allowed(project_id):
        return {"ok": False, "error": "gcp_project_not_allowlisted", "project_id": project_id}
    if billing_account_id and not _gcp_billing_allowed(billing_account_id):
        return {"ok": False, "error": "gcp_billing_account_not_allowlisted"}
    auth = _gcp_readiness(shutil.which("gcloud")).get("auth", {})
    if not auth.get("ok"):
        return {"ok": False, "error": "gcp_auth_required", "auth": auth}
    if dry_run:
        return {"ok": True, "dry_run": True}
    if not _apply_enabled():
        return {"ok": False, "error": "cloud_apply_disabled", "requires_env": "RALFIA_CLOUD_APPLY_ENABLED=true"}
    if not _valid_approval_id(approval_id):
        return {"ok": False, "error": "approval_id_required"}
    return {"ok": True, "dry_run": False, "action": action, "approval_id": approval_id}


def _gcp_candidate(action: str, validation: dict[str, Any], command: list[str], *, mutates: bool) -> dict[str, Any]:
    result = {
        "ok": bool(validation.get("ok")),
        "agent_id": AGENT_ID,
        "provider": "gcp",
        "action": action,
        "validation": validation,
        "command": command,
        "mutates": mutates,
        "executed": False,
        "secret_policy": "server-side only; raw credentials are never returned",
    }
    _audit_cloud_ops(action, {"provider": "gcp", "validation": validation, "command": command, "executed": False})
    if validation.get("ok") and not validation.get("dry_run"):
        if not _apply_enabled():
            result["ok"] = False
            result["error"] = "cloud_apply_disabled"
            result["hint"] = "Set RALFIA_CLOUD_APPLY_ENABLED=true server-side only for approved apply windows."
            return result
        if not command or command[0] != "gcloud" or any(part in {"&&", ";", "|"} for part in command):
            result["ok"] = False
            result["error"] = "unsafe_command_rejected"
            return result
        cli_path = shutil.which("gcloud")
        if not cli_path:
            result["ok"] = False
            result["error"] = "gcloud_missing"
            return result
        exec_result = _run_readonly([cli_path, *command[1:]], timeout=180)
        result["executed"] = True
        result["execution"] = exec_result
        result["ok"] = bool(exec_result.get("ok"))
        _audit_cloud_ops(action, {"provider": "gcp", "validation": validation, "command": command, "executed": True, "returncode": exec_result.get("returncode")})
    return result


def _gcp_read_json(action: str, args: list[str], *, selector: str = "", timeout: int = 40) -> dict[str, Any]:
    cli_path = shutil.which("gcloud")
    if not cli_path:
        return {"ok": False, "agent_id": AGENT_ID, "provider": "gcp", "action": action, "error": "gcloud_missing"}
    result = _run_readonly([cli_path, *args], timeout=timeout)
    data: Any = _json_obj(result.get("stdout"))
    if selector and isinstance(data, dict):
        data = data.get(selector)
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, "provider": "gcp", "action": action, "data": data, "cli": result}


def _cloud_owner_action(provider: str, project_id: str, scopes: list[str], risk_level: str) -> dict[str, Any]:
    scope_text = scopes or ["least privilege needed for requested action"]
    if provider == "gcp":
        return {
            "summary": "Authorize Google Cloud through MCP owner-consent flow; credentials stay server-side.",
            "human_steps": [
                "Ask ChatGPT to call gcp_auth_begin(request_id, account_hint).",
                "Open the returned Google consent URL in Rafael's browser.",
                "Submit only the one-time Google authorization code through gcp_auth_submit_code.",
                "Set project/region env server-side and allowlist the exact project/billing account.",
                "Never paste passwords, OAuth tokens, service-account JSON, or private keys.",
            ],
            "server_env_expected": [
                "GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT",
                "GCP_REGION",
                "RALFIA_GCP_ALLOWED_PROJECTS_JSON",
                "RALFIA_GCP_ALLOWED_BILLING_ACCOUNTS_JSON when billing is needed",
                "RALFIA_CLOUD_APPLY_ENABLED=true only for approved apply windows",
            ],
            "project_id": project_id,
            "requested_scopes": scope_text,
            "risk_level": risk_level,
        }
    return {
        "summary": f"Authorize {PROVIDERS[provider]['label']} using provider-specific OAuth/owner_vault on the server.",
        "human_steps": [
            "Use official provider login/console or owner_vault; never paste raw secrets to an LLM.",
            "Allowlist exact accounts/resources/domains before any write.",
            "Return only request_id and confirmation, then let ChatGPT rerun status/preflight.",
        ],
        "requested_scopes": scope_text,
        "risk_level": risk_level,
    }


def _audit_cloud_ops(action: str, evidence: dict[str, Any]) -> None:
    try:
        mongo_store.get_db()[GENERIC_AUDIT_COLLECTION].insert_one(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent_id": AGENT_ID,
                "provider": evidence.get("provider", "unknown"),
                "action": action,
                "evidence": evidence,
                "secret_policy": "redacted_server_side",
            }
        )
    except Exception:
        pass
    record_agent_run(AGENT_ID, action=f"cloud_ops_{action}", summary=str(evidence.get("provider", "cloud"))[:80], project="ralfia-cloud-ops")


def _valid_gcp_auth_request_id(request_id: str) -> str:
    clean = (request_id or "").strip()
    return clean if re.fullmatch(r"auth_gcp_[0-9]{14}", clean) else ""


def _clean_email(value: str) -> str:
    clean = (value or "").strip().lower()
    return clean if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", clean) else ""


def _read_process_available(proc: subprocess.Popen[str], timeout_sec: float = 5.0) -> str:
    chunks: list[str] = []
    deadline = time.time() + max(0.1, timeout_sec)
    stream = proc.stdout
    fd = stream.fileno() if stream else None
    while stream and fd is not None and time.time() < deadline:
        if proc.poll() is not None:
            ready, _, _ = select.select([fd], [], [], 0)
            if ready:
                remaining = os.read(fd, 65536).decode("utf-8", errors="replace")
                if remaining:
                    chunks.append(remaining)
            break
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096).decode("utf-8", errors="replace")
        except BlockingIOError:
            continue
        if not chunk:
            break
        chunks.append(chunk)
        joined = "".join(chunks)
        if "Enter authorization code" in joined or _extract_google_auth_url(joined):
            break
    return "".join(chunks)


def _extract_google_auth_url(text: str) -> str:
    match = re.search(r"https://accounts\.google\.com/[^\s'\"<>]+", text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,")


def _sanitize_gcloud_auth_output(text: str) -> str:
    value = _redact_text(text or "")
    value = re.sub(r"(?i)(authorization code\s*[:=]?\s*)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(Enter authorization code.*)", "Enter authorization code: [PENDING]", value)
    return value[:4000]


def _upsert_gcp_auth_request(request_id: str, evidence: dict[str, Any]) -> None:
    try:
        now = datetime.now(timezone.utc).isoformat()
        clean_evidence = {k: v for k, v in evidence.items() if k != "request_id"}
        mongo_store.get_db()[GCP_AUTH_REQUEST_COLLECTION].update_one(
            {"request_id": request_id},
            {
                "$set": {**clean_evidence, "updated_at": now, "secret_policy": "no raw credentials stored"},
                "$setOnInsert": {"created_at": now, "request_id": request_id, "agent_id": AGENT_ID},
            },
            upsert=True,
        )
    except Exception:
        pass


def _load_gcp_auth_request(request_id: str) -> dict[str, Any]:
    try:
        doc = mongo_store.get_db()[GCP_AUTH_REQUEST_COLLECTION].find_one({"request_id": request_id}, {"_id": 0})
        return doc or {}
    except Exception:
        return {}


def _gcp_auth_status_from_process(request_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    proc = _GCP_AUTH_PROCS.get(request_id)
    captured = _read_process_available(proc, timeout_sec=0.5) if proc else ""
    readiness = cloud_provider_status("gcp")
    auth_ok = bool((readiness.get("auth") or {}).get("ok"))
    if auth_ok:
        status = "authorized"
    elif proc and proc.poll() is None:
        status = "pending_owner_code"
    elif proc and proc.poll() not in (None, 0):
        status = "failed"
    else:
        status = (_load_gcp_auth_request(request_id).get("status") or "not_started")
    evidence = {
        "request_id": request_id,
        "provider": "gcp",
        "status": status,
        "authorization_ready": auth_ok,
        "returncode": proc.poll() if proc else None,
        "sanitized_output": _sanitize_gcloud_auth_output(captured),
        "accounts_count": (readiness.get("auth") or {}).get("accounts_count"),
        **(extra or {}),
    }
    _upsert_gcp_auth_request(request_id, evidence)
    if proc and proc.poll() is not None:
        _GCP_AUTH_PROCS.pop(request_id, None)
    return {
        "ok": auth_ok or status == "pending_owner_code",
        "agent_id": AGENT_ID,
        "request_id": request_id,
        "provider": "gcp",
        "status": status,
        "authorization_ready": auth_ok,
        "consent_url": _GCP_AUTH_URLS.get(request_id) or _load_gcp_auth_request(request_id).get("consent_url") or "",
        "readiness": readiness,
        "sanitized_output": evidence["sanitized_output"],
        "secret_policy": "Credentials stay server-side; no raw secrets returned.",
        "next": "If status=pending_owner_code, submit the one-time Google code with gcp_auth_submit_code. If authorized, run gcp_auth_bootstrap.",
    }


def _valid_repo(repo: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", (repo or "").strip()))


def _valid_approval_id(value: str) -> bool:
    return bool(re.fullmatch(r"(ops|msg|approval)_[A-Za-z0-9_-]{8,80}", (value or "").strip()))


def _apply_enabled() -> bool:
    return os.getenv("RALFIA_CLOUD_APPLY_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _run_readonly(argv: list[str], timeout: int = 20) -> dict[str, Any]:
    if not argv:
        return {"ok": False, "error": "argv_required"}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": _redact_text(proc.stdout)[:4000],
            "stderr": _redact_text(proc.stderr)[:4000],
            "argv": argv,
        }
    except FileNotFoundError:
        return {"ok": False, "error": "cli_missing", "argv": argv}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "argv": argv}


def _redact_text(text: str) -> str:
    value = text or ""
    value = re.sub(r"(ya29\\.[A-Za-z0-9._-]+|gh[opsu]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)", "[REDACTED]", value)
    value = re.sub(r"(?i)(access[_-]?key|secret|token|password)\\s*[:=]\\s*\\S+", r"\\1=[REDACTED]", value)
    return value


def _gcp_readiness(cli_path: str | None) -> dict[str, Any]:
    if not cli_path:
        return {"auth": {"ok": False, "error": "gcloud_missing"}}
    auth = _run_readonly([cli_path, "auth", "list", "--format=json"], timeout=20)
    config = _run_readonly([cli_path, "config", "list", "--format=json"], timeout=20)
    accounts = []
    project = ""
    try:
        accounts = json.loads(auth.get("stdout") or "[]")
    except Exception:
        accounts = []
    try:
        cfg = json.loads(config.get("stdout") or "{}")
        project = ((cfg.get("core") or {}).get("project") or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "")
    except Exception:
        project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
    return {
        "auth": {"ok": bool(accounts), "accounts_count": len(accounts)},
        "project": project or "",
        "project_configured": bool(project),
        "cli_checks": {"auth_list": auth, "config_list": config},
    }


def _azure_readiness(cli_path: str | None) -> dict[str, Any]:
    if not cli_path:
        return {"auth": {"ok": False, "error": "az_missing"}}
    account = _run_readonly([cli_path, "account", "show", "--output", "json"], timeout=20)
    return {"auth": {"ok": bool(account.get("ok"))}, "cli_checks": {"account_show": account}}


def _alibaba_readiness(cli_path: str | None) -> dict[str, Any]:
    if not cli_path:
        return {"auth": {"ok": False, "error": "aliyun_missing"}}
    config = _run_readonly([cli_path, "configure", "list"], timeout=20)
    return {"auth": {"ok": bool(config.get("ok"))}, "cli_checks": {"configure_list": config}}


def _provider_dry_run_commands(provider: str, service: str, environment: str, project_id: str, region: str, image: str, source_path: str) -> list[dict[str, Any]]:
    if provider == "gcp":
        project = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "<project-id-required>"
        deploy_region = region or os.getenv("GCP_REGION") or "us-central1"
        deploy_image = image or f"gcr.io/{project}/{service}:<tag>"
        return [
            {"purpose": "auth", "argv": ["gcloud", "auth", "list", "--format=json"], "mutates": False},
            {"purpose": "project", "argv": ["gcloud", "config", "set", "project", project], "mutates": "local_config_only"},
            {"purpose": "cloud_run_describe", "argv": ["gcloud", "run", "services", "describe", service, "--region", deploy_region, "--project", project, "--format=json"], "mutates": False},
            {"purpose": "deploy_apply_candidate", "argv": ["gcloud", "run", "deploy", service, "--image", deploy_image, "--region", deploy_region, "--project", project], "mutates": True, "blocked_until_approved": True},
        ]
    if provider == "azure":
        return [
            {"purpose": "auth", "argv": ["az", "account", "show", "--output", "json"], "mutates": False},
            {"purpose": "container_app_show", "argv": ["az", "containerapp", "show", "--name", service, "--resource-group", "<resource-group-required>"], "mutates": False},
            {"purpose": "deploy_apply_candidate", "argv": ["az", "containerapp", "update", "--name", service, "--resource-group", "<resource-group-required>", "--image", image or "<image-required>"], "mutates": True, "blocked_until_approved": True},
        ]
    if provider == "alibaba":
        return [
            {"purpose": "auth", "argv": ["aliyun", "configure", "list"], "mutates": False},
            {"purpose": "service_status", "argv": ["aliyun", "fc-open", "GET", "/2023-03-30/services/<service>"], "mutates": False},
            {"purpose": "deploy_apply_candidate", "argv": ["aliyun", "fc-open", "PUT", "/2023-03-30/services/<service>"], "mutates": True, "blocked_until_approved": True},
        ]
    return [{"purpose": "cloudflare", "argv": ["cloudflare_prepare_hostname", service], "mutates": "depends_on_dry_run"}]


def _audit(action: str, hostname: str, evidence: dict[str, Any]) -> None:
    try:
        mongo_store.get_db()[AUDIT_COLLECTION].insert_one(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent_id": AGENT_ID,
                "provider": "cloudflare",
                "action": action,
                "hostname": hostname,
                "evidence": evidence,
                "secret_policy": "redacted_server_side_owner_vault",
            }
        )
    except Exception:
        pass
    record_agent_run(AGENT_ID, action=f"cloudflare_{action}", summary=hostname[:80], project="ralfia-cloudflare")


def _classify_cloudflare_auth_error(error: str) -> str:
    if "cloudflare_api_http_403" in error or "authentication error" in error.lower():
        return "cloudflare_token_missing_required_permission"
    if "cloudflare_api_http_401" in error:
        return "cloudflare_token_invalid_or_expired"
    return error[:300]


def _redact_dns(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {k: record.get(k) for k in ("id", "type", "name", "content", "proxied", "ttl", "created_on", "modified_on") if k in record}


def _redact_rule(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    if not rule:
        return None
    return {k: rule.get(k) for k in ("id", "action", "description", "enabled", "expression", "logging") if k in rule}


def _redact_ruleset(ruleset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ruleset.get("id"),
        "name": ruleset.get("name"),
        "phase": ruleset.get("phase"),
        "rules_count": len(ruleset.get("rules") or []),
        "hostname_rules": [_redact_rule(r) for r in (ruleset.get("rules") or []) if "http.host" in str(r.get("expression") or "")],
    }


def _extract_yaml_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip().strip('"').strip("'") if match else ""


def _extract_ingress(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("- hostname:"):
            if current:
                items.append(current)
            current = {"hostname": line.split(":", 1)[1].strip().strip('"').strip("'")}
        elif current and line.startswith("service:"):
            current["service"] = line.split(":", 1)[1].strip().strip('"').strip("'")
    if current:
        items.append(current)
    return items


def _which(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None
