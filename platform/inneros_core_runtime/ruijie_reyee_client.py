"""Ruijie Networks / Reyee Cloud Open API client (read-only + multi-tenant inventory).

Architecture & Security:
- Read-only operations for Device Fabric inventory, site hierarchy, AP/Switch/Gateway discovery,
  connected clients, and alarm telemetry.
- Zero public tool exposure: exposed purely behind Device Fabric internal APIs.
- Credentials loaded safely via owner_vault (category `ruijie_cloud` / `reyee_cloud`)
  with fallback to ~/.config/inneros/ruijie.env and system environment variables.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PLATFORM_ROOT / ".env", override=False)

# Support loading from dedicated inneros secure config directory
_SECURE_RUIJIE_ENV = Path.home() / ".config" / "inneros" / "ruijie.env"
if _SECURE_RUIJIE_ENV.exists():
    load_dotenv(_SECURE_RUIJIE_ENV, override=False)

DEFAULT_BASE_URL = "https://cloud.ruijienetworks.com"
API_PREFIX = "/service/api/v1"

_TOKEN_CACHE: dict[str, Any] = {"access_token": "", "expires_at": 0.0}

SITE_NETWORK_ENV: dict[str, str] = {
    "bellini": "RUIJIE_CLOUD_PROJECT_ID_BELLINI",
    "bellini-i-ii": "RUIJIE_CLOUD_PROJECT_ID_BELLINI",
    "bellini_i_ii": "RUIJIE_CLOUD_PROJECT_ID_BELLINI",
    "home_pcdoctor_lab": "RUIJIE_CLOUD_PROJECT_ID_HOME",
    "pcdoctor_lab": "RUIJIE_CLOUD_PROJECT_ID_HOME",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if re.search(
                r"(secret|token|password|passwd|credential|authorization|signature|api[_-]?key|sign)",
                str(key),
                re.I,
            ):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@dataclass(frozen=True)
class RuijieCredentials:
    base_url: str
    app_id: str
    secret_key: str
    source: str
    account_ref: str = "ruijie_acc_primary"

    def as_public(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "app_id": self.app_id,
            "source": self.source,
            "secret_configured": bool(self.secret_key),
            "account_ref": self.account_ref,
        }


def _load_vault_secret(name: str, categories: tuple[str, ...] = ("ruijie_cloud", "reyee_cloud")) -> str:
    try:
        from raphiia_openai import owner_vault

        for cat in categories:
            row = owner_vault.get_owner_credential(name, category=cat, reveal=True)
            if isinstance(row, dict) and row.get("ok") and row.get("secret"):
                return str(row["secret"]).strip()
    except Exception:
        pass
    return ""


def load_ruijie_credentials() -> tuple[RuijieCredentials | None, str | None]:
    """Load Ruijie / Reyee API credentials from environment or encrypted owner_vault."""
    app_id = (
        os.getenv("RUIJIE_CLOUD_APP_ID")
        or os.getenv("RUIJIE_APP_ID")
        or os.getenv("REYEE_APP_ID")
        or _load_vault_secret("app_id")
    )
    secret = (
        os.getenv("RUIJIE_CLOUD_SECRET_KEY")
        or os.getenv("RUIJIE_SECRET_KEY")
        or os.getenv("REYEE_SECRET_KEY")
        or _load_vault_secret("secret_key")
    )
    base = (
        os.getenv("RUIJIE_CLOUD_BASE_URL")
        or os.getenv("RUIJIE_BASE_URL")
        or DEFAULT_BASE_URL
    ).strip().rstrip("/")

    if not app_id or not secret:
        return None, "ruijie_cloud_credentials_missing"

    source = "env" if (os.getenv("RUIJIE_CLOUD_APP_ID") or os.getenv("RUIJIE_APP_ID")) else "owner_vault:ruijie_cloud"
    return RuijieCredentials(base_url=base, app_id=app_id.strip(), secret_key=secret.strip(), source=source), None


def _calculate_signature(app_id: str, secret_key: str, timestamp: int, params: dict[str, Any] | None = None) -> str:
    """Compute signature for Ruijie / Reyee Cloud OpenAPI."""
    # Standard format: MD5(app_id + secret_key + timestamp) or sorted params hash
    raw_str = f"{app_id}{secret_key}{timestamp}"
    if params:
        sorted_keys = sorted(k for k in params.keys() if params[k] is not None and k != "sign")
        query_parts = [f"{k}={params[k]}" for k in sorted_keys]
        if query_parts:
            raw_str += "&" + "&".join(query_parts)
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()


def _http_request(
    creds: RuijieCredentials,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    method: str = "POST",
    access_token: str | None = None,
    timeout: float = 12.0,
) -> dict[str, Any]:
    url = f"{creds.base_url}{API_PREFIX}/{endpoint.lstrip('/')}"
    ts = int(time.time() * 1000)
    sign = _calculate_signature(creds.app_id, creds.secret_key, ts, payload)

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": "InnerOS-DeviceFabric/1.0",
        "X-App-Id": creds.app_id,
        "X-Timestamp": str(ts),
        "X-Sign": sign,
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        headers["X-Access-Token"] = access_token

    body_bytes = None
    if payload is not None:
        body_dict = dict(payload)
        if "app_id" not in body_dict:
            body_dict["app_id"] = creds.app_id
        if "timestamp" not in body_dict:
            body_dict["timestamp"] = ts
        if "sign" not in body_dict:
            body_dict["sign"] = sign
        body_bytes = json.dumps(body_dict).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(data) if data else {}
            return {"ok": True, "status_code": resp.status, "data": parsed}
    except urllib.error.HTTPError as he:
        err_body = he.read().decode("utf-8", errors="replace") if he.fp else ""
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"raw": err_body[:400]}
        return {"ok": False, "status_code": he.code, "error": f"http_{he.code}", "details": err_json}
    except Exception as exc:
        return {"ok": False, "error": "network_or_connection_error", "details": str(exc)[:250]}


def get_access_token(creds: RuijieCredentials, force_refresh: bool = False) -> tuple[str | None, dict[str, Any]]:
    """Retrieve or cache access token for Ruijie / Reyee Cloud API."""
    now = time.time()
    if not force_refresh and _TOKEN_CACHE.get("access_token") and _TOKEN_CACHE.get("expires_at", 0) > now + 60:
        return str(_TOKEN_CACHE["access_token"]), {"cached": True}

    res = _http_request(
        creds,
        "auth/token",
        payload={"app_id": creds.app_id, "secret_key": creds.secret_key},
        method="POST",
    )
    if not res.get("ok"):
        return None, res

    data = res.get("data") or {}
    token = data.get("access_token") or data.get("token") or (data.get("data") or {}).get("access_token")
    expires_in = int(data.get("expires_in") or (data.get("data") or {}).get("expires_in") or 7200)

    if token:
        _TOKEN_CACHE["access_token"] = str(token)
        _TOKEN_CACHE["expires_at"] = now + expires_in
        return str(token), {"ok": True, "expires_in": expires_in}

    # If endpoint returns success without explicit separate token (signature-based oapi), return placeholder
    return "signature_auth_mode", {"ok": True, "auth_mode": "signature"}


def list_devices(
    creds: RuijieCredentials,
    *,
    project_id: str | None = None,
    group_id: str | None = None,
    page: int = 1,
    page_size: int = 100,
    access_token: str | None = None,
) -> dict[str, Any]:
    """List network devices (routers, switches, APs, gateways) from Ruijie Reyee Cloud."""
    payload: dict[str, Any] = {
        "page": page,
        "pageSize": page_size,
    }
    if project_id:
        payload["projectId"] = project_id
    if group_id:
        payload["groupId"] = group_id

    res = _http_request(creds, "device/list", payload=payload, access_token=access_token)
    if not res.get("ok"):
        return res

    data = res.get("data") or {}
    raw_list = data.get("list") or data.get("devices") or (data.get("data") or {}).get("list") or []
    total = data.get("total") or (data.get("data") or {}).get("total") or len(raw_list)

    return {"ok": True, "count": len(raw_list), "total": total, "items": raw_list}


def list_projects(creds: RuijieCredentials, *, access_token: str | None = None) -> dict[str, Any]:
    """List projects / groups / tenant sites in Ruijie Reyee Cloud."""
    res = _http_request(creds, "group/list", payload={}, access_token=access_token)
    if not res.get("ok"):
        # Fallback to network/list or project/list
        res = _http_request(creds, "project/list", payload={}, access_token=access_token)

    if not res.get("ok"):
        return res

    data = res.get("data") or {}
    raw_list = data.get("list") or data.get("groups") or (data.get("data") or {}).get("list") or []
    return {"ok": True, "count": len(raw_list), "items": raw_list}


def list_clients(
    creds: RuijieCredentials,
    *,
    device_sn: str | None = None,
    project_id: str | None = None,
    page: int = 1,
    page_size: int = 100,
    access_token: str | None = None,
) -> dict[str, Any]:
    """List connected clients (STA) on Ruijie Reyee wireless/wired network."""
    payload: dict[str, Any] = {"page": page, "pageSize": page_size}
    if device_sn:
        payload["sn"] = device_sn
    if project_id:
        payload["projectId"] = project_id

    res = _http_request(creds, "client/list", payload=payload, access_token=access_token)
    if not res.get("ok"):
        return res

    data = res.get("data") or {}
    raw_list = data.get("list") or data.get("clients") or (data.get("data") or {}).get("list") or []
    return {"ok": True, "count": len(raw_list), "items": raw_list}


def list_alarms(
    creds: RuijieCredentials,
    *,
    project_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    access_token: str | None = None,
) -> dict[str, Any]:
    """List alarms / events from Ruijie Cloud."""
    payload: dict[str, Any] = {"page": page, "pageSize": page_size}
    if project_id:
        payload["projectId"] = project_id

    res = _http_request(creds, "alarm/list", payload=payload, access_token=access_token)
    if not res.get("ok"):
        return res

    data = res.get("data") or {}
    raw_list = data.get("list") or data.get("alarms") or (data.get("data") or {}).get("list") or []
    return {"ok": True, "count": len(raw_list), "items": raw_list}


def split_ruijie_devices(devices: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Categorize Ruijie Reyee devices into routers, gateways, switches, and access points."""
    routers: list[dict[str, Any]] = []
    gateways: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    aps: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    for d in devices:
        prod_type = str(d.get("productType") or d.get("devType") or d.get("type") or "").lower()
        model = str(d.get("model") or d.get("productModel") or "").lower()

        if "ap" in prod_type or "wap" in prod_type or "rap" in model or "eap" in model or "ap" in model:
            aps.append(d)
        elif "switch" in prod_type or "es" in model or "nbs" in model or "sw" in model:
            switches.append(d)
        elif "gateway" in prod_type or "eg" in model or "nbr" in model or "gw" in model:
            gateways.append(d)
        elif "router" in prod_type or "rg" in model or "ew" in model or "rt" in model:
            routers.append(d)
        else:
            others.append(d)

    return {
        "all": devices,
        "routers": routers,
        "gateways": gateways,
        "switches": switches,
        "access_points": aps,
        "others": others,
    }


def fetch_full_network_snapshot(
    *,
    project_id: str | None = None,
    creds: RuijieCredentials | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Fetch complete read-only snapshot of Ruijie Reyee Cloud topology and inventory."""
    loaded, err = (creds, None) if creds else load_ruijie_credentials()
    if not loaded:
        return {"ok": False, "error": err, "credentials": None}
    creds = loaded

    token = access_token
    token_meta: dict[str, Any] = {}
    if not token:
        token, token_meta = get_access_token(creds)
    if not token:
        return {"ok": False, "error": "ruijie_not_authenticated", "token": token_meta, "credentials": creds.as_public()}

    projects = list_projects(creds, access_token=token)
    devices = list_devices(creds, project_id=project_id, access_token=token)
    split = split_ruijie_devices(devices.get("items") or [])
    clients = list_clients(creds, project_id=project_id, access_token=token)
    alarms = list_alarms(creds, project_id=project_id, access_token=token)

    return {
        "ok": True,
        "provider": "ruijie_reyee",
        "credentials": creds.as_public(),
        "projects": _redact(projects),
        "devices": {
            "all": _redact(devices),
            "routers": _redact({"count": len(split["routers"]), "items": split["routers"]}),
            "gateways": _redact({"count": len(split["gateways"]), "items": split["gateways"]}),
            "switches": _redact({"count": len(split["switches"]), "items": split["switches"]}),
            "access_points": _redact({"count": len(split["access_points"]), "items": split["access_points"]}),
            "others": _redact({"count": len(split["others"]), "items": split["others"]}),
        },
        "clients": _redact(clients),
        "alarms": _redact(alarms),
    }


def ruijie_api_capabilities() -> dict[str, Any]:
    """Expose verified capability map for Ruijie / Reyee Cloud OpenAPI."""
    return {
        "provider": "ruijie_reyee",
        "cloud_api": {
            "auth": "signed_oapi_plus_access_token",
            "read": [
                "group/list (projects and site hierarchy)",
                "device/list (routers, switches, APs, Reyee gateways)",
                "client/list (connected wireless/wired stations)",
                "alarm/list (security & network telemetry alerts)",
            ],
            "write_governed": [
                "device/reboot (owner_approval_ref + dry_run=false - read_only_enforced)",
            ],
        },
        "fabric_integration": {
            "read": ["device_fabric_inventory", "device_fabric_get", "device_fabric_discover"],
            "governance": "read_only_default",
            "public_tools_added": 0,
        },
        "vs_unifi_ha_integration": {
            "parity_observation": [
                "Reyee AP / switch / gateway unified inventory",
                "Cloud project / multi-tenant site hierarchy",
                "Connected client MAC / IP / SSID tracking",
            ],
            "gaps_vs_unifi_controller": [
                "Direct local Webhook event streaming requires Ruijie Cloud Push callback configuration",
                "Live RF optimization & VLAN re-provisioning are governed / read-only in fabric default mode",
            ],
        },
    }
