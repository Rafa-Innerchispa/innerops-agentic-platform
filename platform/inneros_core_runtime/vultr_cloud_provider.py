"""Vultr Cloud Provider Adapter for InnerOS Resource Fabric.

All mutating actions are strictly gated by dry_run=True by default and require
explicit owner approval. API credentials live only in owner_vault and are NEVER
exposed in logs, returns, or exceptions.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from raphiia_openai import mongo_store, owner_vault
from raphiia_openai.agents import ag44_cloud_deployer as cloud_gate

PROVIDER_ID = "vultr-cloud"
VAULT_CATEGORY = "cloud_provider"
VAULT_KEY = "vultr_api_key"
FALLBACK_CATEGORIES = ("vultr", "vultr_cloud")
AUDIT_COLLECTION = "ralfia_vultr_audit"
API_BASE = "https://api.vultr.com/v2"
DEFAULT_SPEND_LIMIT_USD = 25.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, evidence: dict[str, Any]) -> None:
    clean = _redact(evidence)
    clean.setdefault("provider", PROVIDER_ID)
    clean.setdefault("action", action)
    clean.setdefault("timestamp", _now())
    try:
        db = mongo_store.get_db()
        db[AUDIT_COLLECTION].insert_one(clean)
    except Exception:
        pass


def _redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if any(s in str(k).lower() for s in ("token", "secret", "key", "password", "auth", "credential")):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(payload, list):
        return [_redact(i) for i in payload]
    if isinstance(payload, str) and len(payload) > 20 and any(c.isdigit() for c in payload) and any(c.isalpha() for c in payload):
        if re.match(r"^[A-Za-z0-9_-]{20,}$", payload):
            return f"{payload[:4]}...{payload[-4:]}"
    return payload


def _token() -> str:
    # 1. Primary lookup: category="cloud_provider", key="vultr_api_key"
    cred = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True)
    if cred and cred.get("ok") and cred.get("secret"):
        return str(cred["secret"]).strip()
    
    # 2. Fallbacks
    for cat in FALLBACK_CATEGORIES:
        for k in (VAULT_KEY, "api_key", "token"):
            cred = owner_vault.get_owner_credential(k, category=cat, reveal=True)
            if cred and cred.get("ok") and cred.get("secret"):
                return str(cred["secret"]).strip()

    # 3. Environment fallback (strictly for development / test isolation)
    env_tok = os.getenv("VULTR_API_KEY", "").strip()
    if env_tok:
        return env_tok
    return ""


def _headers() -> dict[str, str]:
    tok = _token()
    if not tok:
        raise PermissionError("Vultr API key is not configured in owner_vault.")
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "InnerOS-ResourceFabric/1.0 (+https://innerchispa.us)",
    }


def _request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            msg = parsed.get("error") or raw
        except Exception:
            msg = raw
        raise RuntimeError(f"Vultr API {exc.code} on {method} {path}: {msg}") from exc
    except Exception as exc:
        raise RuntimeError(f"Vultr network error on {method} {path}: {exc}") from exc


def status() -> dict[str, Any]:
    """Returns connectivity and health status of Vultr Cloud Provider."""
    try:
        tok = _token()
        if not tok:
            return {
                "ok": False,
                "provider": PROVIDER_ID,
                "status": "unconfigured",
                "error": "missing_credentials",
                "message": "Vultr API key not found in owner_vault.",
            }
        acct = account()
        return {
            "ok": True,
            "provider": PROVIDER_ID,
            "status": "active",
            "balance": acct.get("balance"),
            "pending_charges": acct.get("pending_charges"),
            "credit_available_usd": acct.get("credit_available_usd", 0.0),
            "updated_at": _now(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": PROVIDER_ID,
            "status": "error",
            "error": str(exc),
            "updated_at": _now(),
        }


def account() -> dict[str, Any]:
    """Retrieves account balance and pending charges from Vultr API."""
    data = _request("GET", "/account")
    acct = data.get("account", {})
    raw_bal = float(acct.get("balance", 0.0))
    pending = float(acct.get("pending_charges", 0.0))
    # In Vultr, negative balance indicates credit on account (e.g. -250 means $250 credit)
    credit_avail = abs(raw_bal) if raw_bal < 0 else 0.0

    res = {
        "ok": True,
        "provider": PROVIDER_ID,
        "balance": raw_bal,
        "pending_charges": pending,
        "credit_available_usd": credit_avail,
        "raw_balance_usd": raw_bal,
        "source": "vultr_api_v2_account",
        "retrieved_at": _now(),
    }
    _audit("account_query", res)
    return res


def list_instances(region: str = "", label: str = "") -> dict[str, Any]:
    """Lists real instances currently provisioned in Vultr."""
    data = _request("GET", "/instances")
    instances = data.get("instances", [])
    filtered = []
    for inst in instances:
        if region and inst.get("region") != region:
            continue
        if label and label.lower() not in (inst.get("label") or "").lower():
            continue
        filtered.append({
            "id": inst.get("id"),
            "label": inst.get("label"),
            "status": inst.get("status"),
            "power_status": inst.get("power_status"),
            "main_ip": inst.get("main_ip"),
            "internal_ip": inst.get("internal_ip"),
            "vcpu_count": inst.get("vcpu_count"),
            "ram_mb": inst.get("ram"),
            "disk_gb": inst.get("disk"),
            "plan": inst.get("plan"),
            "region": inst.get("region"),
            "os": inst.get("os"),
            "date_created": inst.get("date_created"),
            "tags": inst.get("tags") or [],
        })
    res = {
        "ok": True,
        "provider": PROVIDER_ID,
        "count": len(filtered),
        "instances": filtered,
        "retrieved_at": _now(),
    }
    _audit("list_instances", {"count": len(filtered)})
    return res


def get_instance(instance_id: str) -> dict[str, Any]:
    """Fetches details for a specific Vultr instance."""
    inst_id = (instance_id or "").strip()
    if not inst_id:
        return {"ok": False, "error": "instance_id_required"}
    data = _request("GET", f"/instances/{inst_id}")
    inst = data.get("instance", {})
    return {"ok": True, "provider": PROVIDER_ID, "instance": inst}


def list_regions() -> dict[str, Any]:
    """Lists available regions in Vultr."""
    data = _request("GET", "/regions")
    regions = data.get("regions", [])
    res = {
        "ok": True,
        "provider": PROVIDER_ID,
        "count": len(regions),
        "regions": [{
            "id": r.get("id"),
            "city": r.get("city"),
            "country": r.get("country"),
            "continent": r.get("continent"),
            "options": r.get("options", []),
        } for r in regions],
    }
    return res


def list_plans(plan_type: str = "") -> dict[str, Any]:
    """Lists available compute plans in Vultr."""
    data = _request("GET", "/plans")
    plans = data.get("plans", [])
    filtered = []
    for p in plans:
        if plan_type and plan_type.lower() not in (p.get("type") or "").lower():
            continue
        filtered.append({
            "id": p.get("id"),
            "vcpu_count": p.get("vcpu_count"),
            "ram_mb": p.get("ram"),
            "disk_gb": p.get("disk"),
            "bandwidth_gb": p.get("bandwidth"),
            "monthly_cost": p.get("monthly_cost"),
            "type": p.get("type"),
            "locations": p.get("locations", []),
        })
    return {"ok": True, "provider": PROVIDER_ID, "count": len(filtered), "plans": filtered}


def list_os() -> dict[str, Any]:
    """Lists available operating system images in Vultr."""
    data = _request("GET", "/os")
    return {"ok": True, "provider": PROVIDER_ID, "os": data.get("os", [])}


def list_ssh_keys() -> dict[str, Any]:
    """Lists registered SSH keys in Vultr with redacted public keys."""
    data = _request("GET", "/ssh-keys")
    keys = []
    for k in data.get("ssh_keys", []):
        keys.append({
            "id": k.get("id"),
            "name": k.get("name"),
            "date_created": k.get("date_created"),
            "ssh_key": _redact(k.get("ssh_key")),
        })
    return {"ok": True, "provider": PROVIDER_ID, "ssh_keys": keys}


def plan_instance(
    region: str = "mia",
    plan: str = "vc2-1c-1gb",
    os_id: int = 2105, # Ubuntu 24.04 LTS x64
    label: str = "inneros-preview-vm",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Generates a dry-run specification plan and cost estimate without creating resources."""
    plans_res = list_plans()
    matched_plan = None
    for p in plans_res.get("plans", []):
        if p.get("id") == plan:
            matched_plan = p
            break

    monthly_cost = matched_plan.get("monthly_cost", 5.0) if matched_plan else 5.0
    vcpu = matched_plan.get("vcpu_count", 1) if matched_plan else 1
    ram_mb = matched_plan.get("ram_mb", 1024) if matched_plan else 1024
    disk_gb = matched_plan.get("disk_gb", 25) if matched_plan else 25

    return {
        "ok": True,
        "provider": PROVIDER_ID,
        "dry_run": True,
        "action": "plan_instance",
        "proposed_configuration": {
            "region": region,
            "plan": plan,
            "os_id": os_id,
            "label": label,
            "tags": tags or ["inneros", "automated"],
            "vcpu": vcpu,
            "ram_mb": ram_mb,
            "disk_gb": disk_gb,
        },
        "estimated_pricing": {
            "monthly_usd": monthly_cost,
            "hourly_usd": round(monthly_cost / 720.0, 4),
            "currency": "USD",
        },
        "governance": {
            "spend_approval_required": True,
            "spend_limit_usd": DEFAULT_SPEND_LIMIT_USD,
            "policy": "Requires explicit AG-44 owner approval before live execution",
        },
        "generated_at": _now(),
    }


def create_instance(
    region: str,
    plan: str,
    os_id: int,
    label: str,
    ssh_key_ids: list[str] | None = None,
    tags: list[str] | None = None,
    dry_run: bool = True,
    owner_approved: bool = False,
    task_id: str = "",
) -> dict[str, Any]:
    """Creates a new instance in Vultr. Defaults strictly to dry_run=True.
    
    Live creation is REJECTED without owner_approved=True.
    """
    if dry_run or not owner_approved:
        plan_doc = plan_instance(region=region, plan=plan, os_id=os_id, label=label, tags=tags)
        plan_doc["dry_run"] = True
        plan_doc["status"] = "dry_run_approved" if dry_run else "rejected_unauthorized"
        if not owner_approved and not dry_run:
            plan_doc["ok"] = False
            plan_doc["error"] = "owner_approval_required"
            plan_doc["message"] = "Mutating operations in Vultr require explicit owner approval."
        _audit("create_instance_dry_run", plan_doc)
        return plan_doc

    # Live execution path
    payload: dict[str, Any] = {
        "region": region,
        "plan": plan,
        "os_id": os_id,
        "label": label,
        "tags": tags or ["inneros"],
    }
    if ssh_key_ids:
        payload["sshkey_id"] = ssh_key_ids

    _audit("create_instance_live_request", payload)
    data = _request("POST", "/instances", payload)
    inst = data.get("instance", {})
    res = {
        "ok": True,
        "provider": PROVIDER_ID,
        "dry_run": False,
        "status": "creating",
        "instance_id": inst.get("id"),
        "label": inst.get("label"),
        "main_ip": inst.get("main_ip"),
        "created_at": _now(),
    }
    _audit("create_instance_live_success", res)
    return res


def destroy_instance(
    instance_id: str,
    dry_run: bool = True,
    owner_approved: bool = False,
    task_id: str = "",
) -> dict[str, Any]:
    """Destroys an instance in Vultr. Strictly fails closed without owner approval."""
    inst_id = (instance_id or "").strip()
    if not inst_id:
        return {"ok": False, "error": "instance_id_required"}

    if dry_run or not owner_approved:
        res = {
            "ok": not (not owner_approved and not dry_run),
            "provider": PROVIDER_ID,
            "dry_run": True,
            "action": "destroy_instance",
            "instance_id": inst_id,
            "status": "dry_run_only" if dry_run else "rejected_unauthorized",
            "error": "owner_approval_required" if not owner_approved and not dry_run else None,
            "message": "Destructive operations on Vultr require explicit owner approval.",
        }
        _audit("destroy_instance_dry_run", res)
        return res

    _audit("destroy_instance_live_request", {"instance_id": inst_id})
    _request("DELETE", f"/instances/{inst_id}")
    res = {
        "ok": True,
        "provider": PROVIDER_ID,
        "dry_run": False,
        "status": "destroyed",
        "instance_id": inst_id,
        "destroyed_at": _now(),
    }
    _audit("destroy_instance_live_success", res)
    return res


def resource_provider_document() -> dict[str, Any]:
    """Returns provider document for registration in InnerOS Resource Fabric."""
    return {
        "provider_id": PROVIDER_ID,
        "label": "Vultr Cloud Platform",
        "kind": "cloud_infrastructure",
        "capabilities": [
            "cloud_vm",
            "cloud_compute",
            "cloud_deploy",
            "pricing_query",
            "inventory_query",
            "dry_run_provisioning",
        ],
        "local_first": False,
        "auth_mode": "vault_bearer_token",
        "secret_category": VAULT_CATEGORY,
        "risk_level": "financial_cost_bearing_gated",
        "status": "active",
        "cost_policy": "explicit_approval_required_for_mutations",
        "governance": "All provisioning requires owner authorization; dry-run safe by default.",
        "registered_at": _now(),
    }
