"""DigitalOcean / AMD cloud-burst adapter for InnerOS Resource Fabric.

All mutating actions are gated. Tokens live only in owner_vault and are never
returned by public functions.
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
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store, owner_vault
from raphiia_openai.agents import ag44_cloud_deployer as cloud_gate

PROVIDER_ID = "digitalocean-amd-cloud"
MODEL_PROVIDER_ID = "amd-cloud-burst"
VAULT_CATEGORY = "digitalocean_amd_cloud"
VAULT_KEY = "personal_access_token"
AUDIT_COLLECTION = "ralfia_digitalocean_amd_audit"
SESSIONS_COLLECTION = "ralfia_cloud_burst_sessions"
DEFAULT_SPEND_LIMIT_USD = 20.0
DEFAULT_IDLE_MINUTES = 30
API_BASE = "https://api.digitalocean.com/v2"
ACTIVE_SESSION_STATUSES = {"creating", "active", "bootstrapping", "running", "idle"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, evidence: dict[str, Any]) -> None:
    clean = _redact(evidence)
    try:
        mongo_store.get_db()[AUDIT_COLLECTION].insert_one(
            {"ts": _now(), "provider": PROVIDER_ID, "action": action, "evidence": clean, "secret_policy": "redacted_server_side"}
        )
    except Exception:
        pass


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("<redacted>" if re.search(r"(?i)(token|secret|password|authorization|api[_-]?key)", str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and re.search(r"(?i)(dop_v1_|bearer\\s+|token=|api[_-]?key)", value):
        return "<redacted>"
    return value


def _token() -> str:
    cred = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True)
    if not cred.get("ok"):
        return ""
    return str(cred.get("secret") or "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} if token else {}


def _request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    headers = _headers()
    if not headers:
        return {"ok": False, "error": "digitalocean_pat_missing", "secret_location": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}"}
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": parsed}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body[:2000]}
        return {"ok": False, "status": exc.code, "error": "digitalocean_http_error", "data": _redact(parsed)}
    except Exception as exc:
        return {"ok": False, "error": "digitalocean_request_failed", "detail": str(exc)[:300]}


def _request_all(collection: str, path: str, timeout: int = 30) -> dict[str, Any]:
    """Read all pages for DigitalOcean list endpoints."""
    separator = "&" if "?" in path else "?"
    current = f"{path}{separator}per_page=200"
    rows: list[dict[str, Any]] = []
    pages = 0
    while current and pages < 20:
        result = _request("GET", current, timeout=timeout)
        if not result.get("ok"):
            return result
        data = result.get("data") or {}
        rows.extend(data.get(collection) or [])
        pages += 1
        next_url = ((data.get("links") or {}).get("pages") or {}).get("next")
        if not next_url:
            break
        parsed = urllib.parse.urlparse(next_url)
        current = parsed.path.replace("/v2", "", 1)
        if parsed.query:
            current = f"{current}?{parsed.query}"
    return {"ok": True, "status": 200, collection: rows, "pages": pages}


def _is_gpu_size(size: dict[str, Any]) -> bool:
    blob = json.dumps(size, sort_keys=True).lower()
    slug = str(size.get("slug") or "").lower()
    return "gpu" in slug or "mi300" in blob or "mi325" in blob or "mi350" in blob or "mi355" in blob or "amd" in blob


def _size_hourly_rate(size_slug: str) -> float | None:
    sizes = list_sizes(gpu_only=False)
    if not sizes.get("ok"):
        return None
    for size in sizes.get("sizes") or []:
        if str(size.get("slug") or "") == size_slug:
            try:
                return float(size.get("price_hourly"))
            except Exception:
                return None
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def balance() -> dict[str, Any]:
    result = _request("GET", "/customers/my/balance")
    if not result.get("ok"):
        return _redact(result)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "provider": PROVIDER_ID,
        "generated_at": data.get("generated_at"),
        "account_balance": data.get("account_balance"),
        "month_to_date_balance": data.get("month_to_date_balance"),
        "month_to_date_usage": data.get("month_to_date_usage"),
        "account_balance_usd": _as_float(data.get("account_balance")),
        "month_to_date_usage_usd": _as_float(data.get("month_to_date_usage")),
        "credit_policy": "read_only_api_value; do not infer promotional credit or expiry unless DigitalOcean returns it explicitly",
    }


def store_pat_server_side(secret: str, label: str = "DigitalOcean AMD Cloud PAT", actor: str = "RAFAEL") -> dict[str, Any]:
    """Store PAT in owner_vault. Do not call from chat with visible secrets."""
    if not secret or len(secret.strip()) < 20:
        return {"ok": False, "error": "secret_required"}
    result = owner_vault.save_owner_credential(
        key=VAULT_KEY,
        secret=secret.strip(),
        category=VAULT_CATEGORY,
        label=label,
        metadata={"provider": PROVIDER_ID, "scopes_required": ["read", "write droplets/images/sizes/regions"], "stored_at": _now()},
        actor=actor,
    )
    _audit("store_pat_server_side", {"ok": result.get("ok"), "vault_id": result.get("vault_id")})
    return {"ok": bool(result.get("ok")), "vault_id": result.get("vault_id"), "category": VAULT_CATEGORY, "key": VAULT_KEY, "secret_returned": False}


def status() -> dict[str, Any]:
    token_present = bool(_token())
    account = _request("GET", "/account") if token_present else {"ok": False, "error": "digitalocean_pat_missing"}
    bal = balance() if token_present and account.get("ok") else {"ok": False, "error": "balance_not_checked"}
    out = {
        "ok": True,
        "provider": PROVIDER_ID,
        "model_provider": MODEL_PROVIDER_ID,
        "token_present": token_present,
        "account_reachable": bool(account.get("ok")),
        "balance_reachable": bool(bal.get("ok")),
        "balance": {k: bal.get(k) for k in ("generated_at", "account_balance", "month_to_date_balance", "month_to_date_usage", "credit_policy")} if bal.get("ok") else None,
        "secret_location": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}",
        "mutations_require": ["approval_id", "cloud apply window", "explicit owner approval", "allowlisted region/size/image"],
        "local_first": True,
    }
    _audit("status", out)
    return out


def preflight() -> dict[str, Any]:
    manifest = {
        "id": PROVIDER_ID,
        "auth_mode": "owner_vault",
        "secret_category": VAULT_CATEGORY,
        "capabilities": ["status", "preflight", "list_regions", "list_sizes", "list_images", "list_ssh_keys", "list_droplets", "create_gpu_droplet", "destroy_droplet", "cost_session_status"],
        "risk_level": "high_write",
        "allowed_resources": ["droplets", "ssh_keys", "firewalls", "images", "sizes", "regions"],
        "rate_limits": {"reads_per_minute": 60, "writes_per_hour": 4, "default_spend_limit_usd": DEFAULT_SPEND_LIMIT_USD},
    }
    bal = balance() if bool(_token()) else {"ok": False, "error": "digitalocean_pat_missing"}
    checks = {
        "token_present": bool(_token()),
        "account_reachable": bool(status().get("account_reachable")) if bool(_token()) else False,
        "balance_reachable": bool(bal.get("ok")),
        "approval_gate_registered": True,
        "no_project_id_hardcoded": True,
        "funding_global": True,
        "create_requires_approval": True,
        "destroy_requires_approval": True,
    }
    return {"ok": True, "provider": PROVIDER_ID, "checks": checks, "manifest_candidate": manifest, "balance": bal if bal.get("ok") else {"ok": False, "error": bal.get("error")}, "token_step": "Use digitalocean_store_pat_server_side on the server, not chat."}


def resource_provider_document() -> dict[str, Any]:
    current = status()
    return {
        "provider_id": PROVIDER_ID,
        "label": "DigitalOcean AMD Cloud Burst",
        "kind": "ephemeral_cloud_gpu",
        "capabilities": ["coding", "heavy_reasoning", "gpu_inference", "cloud_burst", "ephemeral_runtime"],
        "model_provider": MODEL_PROVIDER_ID,
        "local_first": False,
        "status": "active" if current.get("token_present") and current.get("account_reachable") else "configured_needs_token",
        "requires": ["owner_vault PAT", "approval_id", "cloud apply window", "allowlisted region/size/image", "destroy evidence"],
        "mutations_require": current.get("mutations_require") or ["approval_id", "cloud apply window"],
        "balance": current.get("balance"),
        "cost_policy": "explicit_burst_only",
        "updated_at": _now(),
    }


def model_provider_document() -> dict[str, Any]:
    return {
        "model_provider": MODEL_PROVIDER_ID,
        "provider_id": PROVIDER_ID,
        "task_classes": ["coding", "heavy_reasoning", "gpu_inference"],
        "priority": 50,
        "cost_policy": "explicit_burst_only",
        "lifecycle": "create->health->bootstrap->task->evidence->idle_destroy",
        "default": False,
    }


def list_regions() -> dict[str, Any]:
    result = _request_all("regions", "/regions")
    if result.get("ok"):
        result = {"ok": True, "provider": PROVIDER_ID, "count": len(result.get("regions") or []), "regions": result.get("regions") or [], "pages": result.get("pages")}
    return _redact(result)


def list_sizes(gpu_only: bool = True) -> dict[str, Any]:
    result = _request_all("sizes", "/sizes")
    if not result.get("ok"):
        return _redact(result)
    sizes = result.get("sizes") or []
    if gpu_only:
        sizes = [s for s in sizes if _is_gpu_size(s)]
    return {"ok": True, "provider": PROVIDER_ID, "count": len(sizes), "sizes": sizes, "pages": result.get("pages")}


def list_images() -> dict[str, Any]:
    result = _request_all("images", "/images?type=distribution")
    if result.get("ok"):
        images = result.get("images") or []
        result = {"ok": True, "provider": PROVIDER_ID, "count": len(images), "images": images, "pages": result.get("pages")}
    return _redact(result)


def list_ssh_keys() -> dict[str, Any]:
    result = _request_all("ssh_keys", "/account/keys")
    if not result.get("ok"):
        return _redact(result)
    keys = result.get("ssh_keys") or []
    return {
        "ok": True,
        "provider": PROVIDER_ID,
        "count": len(keys),
        "ssh_keys": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "fingerprint": item.get("fingerprint"),
                "public_key_present": bool(item.get("public_key")),
            }
            for item in keys
            if isinstance(item, dict)
        ],
        "pages": result.get("pages"),
    }


def create_ssh_key(name: str, public_key: str, dry_run: bool = True) -> dict[str, Any]:
    key_name = str(name or "").strip()[:80]
    key_material = str(public_key or "").strip()
    if not key_name:
        return {"ok": False, "provider": PROVIDER_ID, "error": "ssh_key_name_required"}
    if not re.match(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521)\s+\S+", key_material):
        return {"ok": False, "provider": PROVIDER_ID, "error": "ssh_public_key_invalid_or_missing"}
    payload = {"name": key_name, "public_key": key_material}
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": PROVIDER_ID, "payload": {"name": key_name, "public_key_present": True}, "executed": False}
    result = _request("POST", "/account/keys", payload)
    key = (result.get("data") or {}).get("ssh_key") or {}
    if not result.get("ok"):
        return {"ok": False, "provider": PROVIDER_ID, "executed": False, "error": result.get("error"), "detail": _redact(result.get("data") or {})}
    _audit("create_ssh_key", {"ok": True, "name": key_name, "id": key.get("id"), "fingerprint": key.get("fingerprint")})
    return {
        "ok": True,
        "provider": PROVIDER_ID,
        "executed": True,
        "ssh_key": {"id": key.get("id"), "name": key.get("name"), "fingerprint": key.get("fingerprint"), "public_key_present": bool(key.get("public_key"))},
    }


def register_server_public_ssh_key(name: str = "inneros-amd-5-id-ed25519", public_key_path: str = "~/.ssh/id_ed25519.pub", dry_run: bool = True) -> dict[str, Any]:
    raw_path = str(public_key_path or "~/.ssh/id_ed25519.pub").strip()
    path = Path(raw_path).expanduser().resolve()
    ssh_dir = (Path.home() / ".ssh").resolve()
    if ssh_dir not in path.parents or path.suffix != ".pub":
        return {"ok": False, "provider": PROVIDER_ID, "error": "public_key_path_not_allowlisted", "allowed_dir": str(ssh_dir)}
    try:
        public_key = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {"ok": False, "provider": PROVIDER_ID, "error": "public_key_read_failed", "detail": str(exc), "path": str(path)}
    existing = list_ssh_keys()
    if existing.get("ok"):
        for item in existing.get("ssh_keys") or []:
            if str(item.get("name") or "") == str(name or "").strip():
                return {"ok": True, "provider": PROVIDER_ID, "already_exists": True, "executed": False, "ssh_key": item}
    return create_ssh_key(name=name, public_key=public_key, dry_run=dry_run)


def list_droplets(tag_name: str = "inneros-cloud-burst") -> dict[str, Any]:
    query = f"?tag_name={urllib.parse.quote(tag_name)}" if tag_name else ""
    result = _request_all("droplets", f"/droplets{query}")
    if result.get("ok"):
        droplets = result.get("droplets") or []
        result = {"ok": True, "provider": PROVIDER_ID, "count": len(droplets), "droplets": droplets, "pages": result.get("pages")}
    return _redact(result)


def _mutation_allowed(action: str, approval_id: str, project_id: str = "") -> dict[str, Any]:
    approval = cloud_gate.cloud_approval_status(approval_id)
    window = cloud_gate.cloud_apply_window_status(provider=PROVIDER_ID, project_id=project_id)
    if not approval.get("active") or not window.get("apply_enabled"):
        return {"ok": False, "error": "active_approval_and_apply_window_required", "approval": approval, "window": window, "action": action}
    return {"ok": True, "approval": approval, "window": window}


def _validate_create_inputs(region: str, size: str, image: str, spend_limit_usd: float, idle_minutes: int) -> dict[str, Any]:
    region_slug = (region or "").strip()
    size_slug = (size or "").strip()
    image_slug = (image or "").strip()
    if not region_slug or not size_slug or not image_slug:
        return {"ok": False, "error": "region_size_image_required"}
    try:
        limit = float(spend_limit_usd)
    except (TypeError, ValueError):
        return {"ok": False, "error": "spend_limit_invalid"}
    if limit <= 0 or limit > DEFAULT_SPEND_LIMIT_USD:
        return {"ok": False, "error": "spend_limit_out_of_policy", "max_spend_limit_usd": DEFAULT_SPEND_LIMIT_USD}
    if int(idle_minutes or 0) <= 0 or int(idle_minutes or 0) > 240:
        return {"ok": False, "error": "idle_minutes_out_of_policy", "max_idle_minutes": 240}
    if not _token():
        return {"ok": False, "error": "digitalocean_pat_missing"}
    sizes = list_sizes(gpu_only=True)
    if not sizes.get("ok"):
        return {"ok": False, "error": "sizes_preflight_failed", "detail": sizes}
    matching_size = next((s for s in sizes.get("sizes") or [] if str(s.get("slug") or "") == size_slug), None)
    if not matching_size:
        return {"ok": False, "error": "gpu_size_not_allowlisted", "size": size_slug, "available_gpu_sizes": [s.get("slug") for s in sizes.get("sizes") or []]}
    size_regions = [str(r) for r in (matching_size.get("regions") or [])]
    if size_regions and region_slug not in size_regions:
        return {"ok": False, "error": "size_not_available_in_region", "size": size_slug, "region": region_slug, "available_regions": size_regions}
    images = list_images()
    if images.get("ok"):
        image_ok = any(str(img.get("slug") or img.get("id") or "") == image_slug for img in images.get("images") or [])
        if not image_ok:
            return {"ok": False, "error": "image_not_allowlisted", "image": image_slug, "allowed_examples": [str(img.get("slug") or img.get("id")) for img in (images.get("images") or [])[:20]]}
    return {"ok": True, "region": region_slug, "size": matching_size, "image": image_slug, "hourly_rate_usd": _as_float(matching_size.get("price_hourly"))}


def create_gpu_droplet(
    *,
    name: str,
    region: str,
    size: str,
    image: str,
    ssh_key_ids: list[str] | None = None,
    project_id: str = "",
    task_id: str = "",
    approval_id: str = "",
    dry_run: bool = True,
    spend_limit_usd: float = DEFAULT_SPEND_LIMIT_USD,
    idle_minutes: int = DEFAULT_IDLE_MINUTES,
) -> dict[str, Any]:
    guard = _mutation_allowed("create_gpu_droplet", approval_id, project_id)
    validation = _validate_create_inputs(region, size, image, spend_limit_usd, idle_minutes)
    payload = {
        "name": name[:80],
        "region": region,
        "size": size,
        "image": image,
        "ssh_keys": ssh_key_ids or [],
        "backups": False,
        "ipv6": False,
        "monitoring": True,
        "tags": ["inneros-cloud-burst", "amd-cloud-burst", project_id or "global"],
        "user_data": _cloud_init_stub(),
    }
    hourly_rate = validation.get("hourly_rate_usd") if validation.get("ok") else None
    session = _session_doc(project_id=project_id, task_id=task_id, droplet_id="", status="planned", size=size, region=region, hourly_rate_usd=hourly_rate, spend_limit_usd=spend_limit_usd, idle_minutes=idle_minutes)
    if dry_run or not guard.get("ok") or not validation.get("ok"):
        return {"ok": bool(dry_run and validation.get("ok")), "dry_run": True, "provider": PROVIDER_ID, "guard": guard, "validation": _redact(validation), "payload": _redact(payload), "session": session, "executed": False}
    result = _request("POST", "/droplets", payload)
    droplet = (result.get("data") or {}).get("droplet") or {}
    if not result.get("ok"):
        _audit("create_gpu_droplet_failed", {"ok": False, "session_id": session["session_id"], "project_id": project_id, "task_id": task_id, "result": result})
        return {"ok": False, "provider": PROVIDER_ID, "session": {**session, "status": "create_failed"}, "droplet": {}, "executed": False, "error": result.get("error"), "detail": result.get("data")}
    if not droplet.get("id"):
        _audit("create_gpu_droplet_missing_droplet_id", {"ok": False, "session_id": session["session_id"], "project_id": project_id, "task_id": task_id, "result": result})
        return {"ok": False, "provider": PROVIDER_ID, "session": {**session, "status": "create_failed"}, "droplet": _redact(droplet), "executed": False, "error": "digitalocean_create_returned_no_droplet_id"}
    session.update({"droplet_id": str(droplet.get("id") or ""), "status": "creating", "created_at": _now(), "last_seen_at": _now()})
    mongo_store.get_db()[SESSIONS_COLLECTION].update_one({"session_id": session["session_id"]}, {"$set": session}, upsert=True)
    _audit("create_gpu_droplet", {"ok": result.get("ok"), "session_id": session["session_id"], "droplet_id": session.get("droplet_id"), "project_id": project_id, "task_id": task_id})
    return {"ok": bool(result.get("ok")), "provider": PROVIDER_ID, "session": session, "droplet": _redact(droplet), "executed": bool(result.get("ok"))}


def get_droplet(droplet_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{4,30}", str(droplet_id or "")):
        return {"ok": False, "error": "droplet_id_invalid"}
    result = _request("GET", f"/droplets/{droplet_id}")
    return _redact(result)


def destroy_droplet(droplet_id: str, approval_id: str = "", project_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{4,30}", str(droplet_id or "")):
        return {"ok": False, "error": "droplet_id_invalid"}
    guard = _mutation_allowed("destroy_droplet", approval_id, project_id)
    if dry_run or not guard.get("ok"):
        return {"ok": bool(guard.get("ok")) or dry_run, "dry_run": True, "provider": PROVIDER_ID, "droplet_id": droplet_id, "guard": guard, "executed": False}
    result = _request("DELETE", f"/droplets/{droplet_id}")
    mongo_store.get_db()[SESSIONS_COLLECTION].update_many({"droplet_id": str(droplet_id)}, {"$set": {"status": "destroyed", "destroyed_at": _now()}})
    _audit("destroy_droplet", {"ok": result.get("ok"), "droplet_id": droplet_id, "project_id": project_id})
    return {"ok": bool(result.get("ok")), "provider": PROVIDER_ID, "droplet_id": droplet_id, "executed": bool(result.get("ok"))}


def cost_session_status(session_id: str = "", project_id: str = "", task_id: str = "") -> dict[str, Any]:
    filt: dict[str, Any] = {}
    if session_id:
        filt["session_id"] = session_id
    if project_id:
        filt["project_id"] = project_id
    if task_id:
        filt["task_id"] = task_id
    rows = list(mongo_store.get_db()[SESSIONS_COLLECTION].find(filt, {"_id": 0}).sort("updated_at", -1).limit(20))
    now = time.time()
    for row in rows:
        started = row.get("started_epoch") or now
        hourly = float(row.get("hourly_rate_usd") or 0)
        elapsed_hours = max(0, now - float(started)) / 3600
        is_billable_session = bool(row.get("droplet_id")) and str(row.get("status") or "") in ACTIVE_SESSION_STATUSES
        row["estimated_spend_usd"] = round(elapsed_hours * hourly, 4) if is_billable_session else 0.0
        row["destroy_is_required_to_stop_billing"] = is_billable_session
    return {"ok": True, "provider": PROVIDER_ID, "count": len(rows), "sessions": rows, "billing_policy": "Power-off is not treated as stop billing; destroy closes the session."}


def cleanup_failed_sessions(max_age_seconds: int = 3600, dry_run: bool = True) -> dict[str, Any]:
    cutoff = datetime.fromtimestamp(time.time() - max(60, int(max_age_seconds or 3600)), tz=timezone.utc).isoformat()
    query = {
        "provider": PROVIDER_ID,
        "status": {"$in": ["planned", "creating"]},
        "droplet_id": {"$in": ["", None]},
        "updated_at": {"$lt": cutoff},
    }
    col = mongo_store.get_db()[SESSIONS_COLLECTION]
    rows = list(col.find(query, {"_id": 0}).limit(100))
    if dry_run:
        return {"ok": True, "dry_run": True, "matched": len(rows), "sessions": rows}
    result = col.update_many(query, {"$set": {"status": "create_failed", "cleanup_reason": "missing_droplet_id_after_create_window", "updated_at": _now()}})
    return {"ok": True, "dry_run": False, "matched": len(rows), "modified": int(getattr(result, "modified_count", 0))}


def _session_doc(**kwargs: Any) -> dict[str, Any]:
    session_id = f"cloudburst_{int(time.time())}_{os.getpid()}"
    now = _now()
    return {
        "session_id": session_id,
        "provider": PROVIDER_ID,
        "model_provider": MODEL_PROVIDER_ID,
        "created_at": now,
        "updated_at": now,
        "started_epoch": time.time(),
        **kwargs,
    }


def _cloud_init_stub() -> str:
    return """#cloud-config
package_update: true
packages:
  - python3
  - python3-venv
write_files:
  - path: /opt/inneros/README.txt
    permissions: '0644'
    content: |
      InnerOS AMD cloud burst node. Provisioning is intentionally minimal until
      an approved ROCm/vLLM image or reviewed cloud-init is selected.
runcmd:
  - [ bash, -lc, "mkdir -p /opt/inneros && echo provisioned > /opt/inneros/status" ]
"""
