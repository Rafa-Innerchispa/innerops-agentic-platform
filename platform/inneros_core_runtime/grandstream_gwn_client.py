"""Grandstream GWN Cloud / GWN Manager Open API client (read + governed writes).

Authentication: OAuth2 client_credentials via GET /oauth/token.
Signed requests: SHA256 over sorted public params + body hash (GWN oapi v1.0.0).

Credentials (env or owner_vault category ``gwn_cloud``):
  GWN_CLOUD_BASE_URL (default https://www.gwn.cloud)
  GWN_CLOUD_APP_ID / GWN_CLOUD_SECRET_KEY
Optional per-site network id:
  GWN_CLOUD_NETWORK_ID, GWN_CLOUD_NETWORK_ID_BELLINI, GWN_CLOUD_NETWORK_ID_HOME
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PLATFORM_ROOT / ".env", override=False)
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "https://www.gwn.cloud"
API_PREFIX = "/oapi/v1.0.0"

_TOKEN_CACHE: dict[str, Any] = {"access_token": "", "expires_at": 0.0}

SITE_NETWORK_ENV: dict[str, str] = {
    "bellini": "GWN_CLOUD_NETWORK_ID_BELLINI",
    "bellini-i-ii": "GWN_CLOUD_NETWORK_ID_BELLINI",
    "bellini_i_ii": "GWN_CLOUD_NETWORK_ID_BELLINI",
    "home_pcdoctor_lab": "GWN_CLOUD_NETWORK_ID_HOME",
    "pcdoctor_lab": "GWN_CLOUD_NETWORK_ID_HOME",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if re.search(
                r"(secret|token|password|passwd|credential|authorization|signature|api[_-]?key)",
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
class GwnCredentials:
    base_url: str
    app_id: str
    secret_key: str
    source: str

    def as_public(self) -> dict[str, str]:
        return {
            "base_url": self.base_url,
            "app_id": self.app_id,
            "source": self.source,
            "secret_configured": bool(self.secret_key),
        }


def _load_vault_secret(name: str) -> str:
    try:
        from raphiia_openai import owner_vault

        row = owner_vault.get_owner_credential(name, category="gwn_cloud", reveal=True)
        if isinstance(row, dict) and row.get("ok") and row.get("secret"):
            return str(row["secret"]).strip()
    except Exception:
        pass
    return ""


def load_gwn_credentials() -> tuple[GwnCredentials | None, str | None]:
    app_id = (os.getenv("GWN_CLOUD_APP_ID") or _load_vault_secret("app_id")).strip()
    secret = (os.getenv("GWN_CLOUD_SECRET_KEY") or _load_vault_secret("secret_key")).strip()
    base = (os.getenv("GWN_CLOUD_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    if not app_id or not secret:
        return None, "gwn_cloud_credentials_missing"
    source = "env" if os.getenv("GWN_CLOUD_APP_ID") else "owner_vault:gwn_cloud"
    return GwnCredentials(base_url=base, app_id=app_id, secret_key=secret, source=source), None


def resolve_network_id(
    *,
    client_id: str = "",
    site_id: str = "",
    network_id: int | None = None,
    tenant_row: dict[str, Any] | None = None,
) -> int | None:
    if network_id and int(network_id) > 0:
        return int(network_id)
    if tenant_row:
        for key in ("gwn_network_id", "network_id", "gwn_cloud_network_id"):
            raw = tenant_row.get(key)
            if raw is not None and str(raw).strip().isdigit():
                return int(str(raw).strip())
    keys = []
    for token in (site_id, client_id):
        t = (token or "").strip().lower()
        if t and t in SITE_NETWORK_ENV:
            keys.append(SITE_NETWORK_ENV[t])
    keys.append("GWN_CLOUD_NETWORK_ID")
    for key in keys:
        raw = (os.getenv(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    return None


def _http_request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 35.0,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method.upper())
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), payload


def get_access_token(creds: GwnCredentials, *, force_refresh: bool = False) -> tuple[str | None, dict[str, Any]]:
    now = time.time()
    if (
        not force_refresh
        and _TOKEN_CACHE.get("access_token")
        and float(_TOKEN_CACHE.get("expires_at") or 0) > now + 30
        and _TOKEN_CACHE.get("base_url") == creds.base_url
        and _TOKEN_CACHE.get("app_id") == creds.app_id
    ):
        return str(_TOKEN_CACHE["access_token"]), {"ok": True, "cached": True}

    params = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": creds.app_id,
            "client_secret": creds.secret_key,
        }
    )
    url = f"{creds.base_url}/oauth/token?{params}"
    status, text = _http_request("GET", url, timeout=25.0)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, {"ok": False, "error": "gwn_token_invalid_json", "http_status": status, "body_snippet": text[:200]}
    if status >= 400 or not payload.get("access_token"):
        return None, {
            "ok": False,
            "error": "gwn_token_failed",
            "http_status": status,
            "detail": _redact(payload),
        }
    token = str(payload["access_token"])
    expires_in = int(payload.get("expires_in") or 3600)
    _TOKEN_CACHE.update(
        {
            "access_token": token,
            "expires_at": now + max(60, expires_in - 60),
            "base_url": creds.base_url,
            "app_id": creds.app_id,
        }
    )
    return token, {"ok": True, "cached": False, "expires_in": expires_in}


def _sign_request(
    access_token: str,
    app_id: str,
    secret_key: str,
    body_obj: dict[str, Any] | list[Any] | None,
) -> tuple[str, str, int]:
    timestamp = round(time.time() * 1000)
    public_params = {
        "access_token": access_token,
        "appID": app_id,
        "secretKey": secret_key,
        "timestamp": timestamp,
    }
    body = json.dumps(body_obj if body_obj is not None else {}, separators=(",", ":"))
    params = "&".join(f"{key}={public_params[key]}" for key in public_params)
    body_signature = hashlib.sha256(body.encode("utf-8")).hexdigest()
    signature = hashlib.sha256(f"&{params}&{body_signature}&".encode("utf-8")).hexdigest()
    query = (
        f"access_token={access_token}&appID={app_id}&timestamp={timestamp}&signature={signature}"
    )
    return query, body, timestamp


def gwn_api_call(
    creds: GwnCredentials,
    path: str,
    *,
    method: str = "POST",
    body: dict[str, Any] | list[Any] | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    token = access_token
    token_meta: dict[str, Any] = {"ok": True}
    if not token:
        token, token_meta = get_access_token(creds)
    if not token:
        return {"ok": False, "error": "gwn_not_authenticated", "token": token_meta}

    rel = path if path.startswith("/") else f"{API_PREFIX}/{path.lstrip('/')}"
    query, body_text, _ts = _sign_request(token, creds.app_id, creds.secret_key, body)
    url = f"{creds.base_url}{rel}?{query}"
    status, text = _http_request(
        method,
        url,
        body=body_text.encode("utf-8") if method.upper() != "GET" else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        payload = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw": text[:500]}
    ret_raw = payload.get("retCode", payload.get("code"))
    ret_str = str(ret_raw).strip() if ret_raw is not None else "0"
    ok = status < 400 and ret_str in {"0", "200", "success", "OK", ""}
    return {
        "ok": bool(ok),
        "http_status": status,
        "path": rel,
        "method": method.upper(),
        "data": payload.get("data", payload),
        "ret_code": payload.get("retCode", payload.get("code")),
        "message": payload.get("msg", payload.get("message")),
        "token_cached": token_meta.get("cached"),
    }


def _paginated_list(
    creds: GwnCredentials,
    path: str,
    body_base: dict[str, Any],
    *,
    page_size: int = 50,
    max_pages: int = 5,
    access_token: str | None = None,
) -> dict[str, Any]:
    rows: list[Any] = []
    last: dict[str, Any] = {}
    for page in range(1, max_pages + 1):
        body = dict(body_base)
        body.setdefault("pageNum", page)
        body.setdefault("pageSize", page_size)
        last = gwn_api_call(creds, path, body=body, access_token=access_token)
        if not last.get("ok"):
            return last
        chunk = last.get("data")
        if isinstance(chunk, dict):
            page_rows = chunk.get("result") or chunk.get("list") or chunk.get("records") or chunk.get("rows")
            if page_rows is None and isinstance(chunk.get("data"), list):
                page_rows = chunk.get("data")
            total = chunk.get("total") or chunk.get("totalCount")
        elif isinstance(chunk, list):
            page_rows = chunk
            total = None
        else:
            page_rows = None
            total = None
        if not page_rows:
            break
        if isinstance(page_rows, list):
            rows.extend(page_rows)
        else:
            rows.append(page_rows)
        if total is not None and len(rows) >= int(total):
            break
        if not isinstance(page_rows, list) or len(page_rows) < page_size:
            break
    return {"ok": True, "count": len(rows), "items": rows, "last_page": last}


def list_networks(creds: GwnCredentials, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "network/list",
        {"type": "asc", "order": "id", "search": ""},
        access_token=access_token,
    )


def network_detail(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return gwn_api_call(creds, "network/detail", body={"id": int(network_id)}, access_token=access_token)


def list_ssids(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "ssid/list",
        {"search": "", "order": "name", "networkId": int(network_id)},
        access_token=access_token,
    )


def list_network_devices(
    creds: GwnCredentials,
    network_id: int,
    *,
    access_token: str | None = None,
    max_pages: int = 10,
) -> dict[str, Any]:
    """GWN ``ap/list`` returns routers, switches, and APs for the network."""
    return _paginated_list(
        creds,
        "ap/list",
        {"search": "", "order": "name", "networkId": int(network_id)},
        page_size=50,
        max_pages=max_pages,
        access_token=access_token,
    )


def list_access_points(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return list_network_devices(creds, network_id, access_token=access_token)


def classify_network_device_row(row: dict[str, Any]) -> str:
    ap_type = str(row.get("apType") or row.get("model") or "").upper()
    name = str(row.get("name") or "").lower()
    if "GCC" in ap_type or "router" in name:
        return "router"
    if ap_type.startswith("GWN78") or "switch" in name:
        return "switch"
    return "ap"


def split_network_devices(devices: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"routers": [], "switches": [], "aps": [], "all": []}
    for row in devices:
        if not isinstance(row, dict):
            continue
        kind = classify_network_device_row(row)
        out["all"].append(row)
        if kind == "router":
            out["routers"].append(row)
        elif kind == "switch":
            out["switches"].append(row)
        else:
            out["aps"].append(row)
    return out


def list_switches(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    listed = list_network_devices(creds, network_id, access_token=access_token)
    if not listed.get("ok"):
        return listed
    switches = split_network_devices(listed.get("items") or [])["switches"]
    return {"ok": True, "count": len(switches), "items": switches, "source": "ap/list_filtered"}


def list_routers(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    listed = list_network_devices(creds, network_id, access_token=access_token)
    if not listed.get("ok"):
        return listed
    routers = split_network_devices(listed.get("items") or [])["routers"]
    return {"ok": True, "count": len(routers), "items": routers, "source": "ap/list_filtered"}


def list_inventory(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "inventory/list",
        {"networkId": int(network_id)},
        page_size=50,
        max_pages=10,
        access_token=access_token,
    )


def list_wan(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "wan/list",
        {"networkId": int(network_id)},
        access_token=access_token,
    )


def list_alerts(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "alert/list",
        {"networkId": int(network_id), "pageNum": 1, "pageSize": 50},
        access_token=access_token,
    )


def list_portals(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return gwn_api_call(creds, "portal/list", body={"networkId": int(network_id)}, access_token=access_token)


def list_vouchers(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "voucher/list",
        {"search": "", "order": "name", "networkId": int(network_id)},
        access_token=access_token,
    )


def list_schedules(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "schedule/list",
        {"networkId": int(network_id)},
        access_token=access_token,
    )


def list_radius(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "radius/list",
        {"networkId": int(network_id)},
        access_token=access_token,
    )


def list_bandwidth_rules(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    return _paginated_list(
        creds,
        "bandwidth/list",
        {"networkId": int(network_id)},
        access_token=access_token,
    )


def list_clients(creds: GwnCredentials, network_id: int, *, access_token: str | None = None) -> dict[str, Any]:
    primary = _paginated_list(
        creds,
        "client/list",
        {"search": "", "order": "mac", "networkId": int(network_id)},
        access_token=access_token,
    )
    if primary.get("ok") and primary.get("count", 0) > 0:
        return primary
    fallback = _paginated_list(
        creds,
        "sta/list",
        {"search": "", "networkId": int(network_id)},
        access_token=access_token,
    )
    if fallback.get("ok"):
        fallback.setdefault("endpoint_tried", ["client/list", "sta/list"])
        return fallback
    primary["endpoint_tried"] = ["client/list", "sta/list"]
    primary["fallback_error"] = _redact(fallback)
    return primary


def device_info(
    creds: GwnCredentials,
    network_id: int,
    mac: str,
    *,
    access_token: str | None = None,
) -> dict[str, Any]:
    return gwn_api_call(
        creds,
        "device/info",
        body={"mac": mac, "networkId": int(network_id)},
        access_token=access_token,
    )


def device_reboot(
    creds: GwnCredentials,
    network_id: int,
    mac: str,
    *,
    dry_run: bool = True,
    owner_approval_ref: str = "",
    access_token: str | None = None,
) -> dict[str, Any]:
    body = {"networkId": int(network_id), "mac": mac.strip().upper()}
    if dry_run or not owner_approval_ref.strip():
        return {
            "ok": True,
            "dry_run": True,
            "would_call": "ap/reboot",
            "mac": body["mac"],
            "owner_approval_required": True,
        }
    return gwn_api_call(creds, "ap/reboot", body=body, access_token=access_token)


def fetch_device_details_batch(
    creds: GwnCredentials,
    network_id: int,
    devices: list[dict[str, Any]],
    *,
    access_token: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for dev in devices[:limit]:
        mac = str(dev.get("mac") or "").strip()
        if not mac:
            continue
        detail = device_info(creds, network_id, mac, access_token=access_token)
        if detail.get("ok"):
            rows.append({"mac": mac, "name": dev.get("name"), "detail": _redact(detail.get("data"))})
        else:
            errors.append({"mac": mac, "error": detail.get("message") or detail.get("ret_code")})
    return {"ok": True, "count": len(rows), "devices": rows, "errors": errors}


def ssid_update(
    creds: GwnCredentials,
    payload: dict[str, Any],
    *,
    dry_run: bool = True,
    owner_approval_ref: str = "",
    access_token: str | None = None,
) -> dict[str, Any]:
    if dry_run or not owner_approval_ref.strip():
        return {
            "ok": True,
            "dry_run": True,
            "would_call": "ssid/update",
            "payload_keys": sorted(payload.keys()),
            "owner_approval_required": True,
            "owner_approval_ref": owner_approval_ref or None,
        }
    return gwn_api_call(creds, "ssid/update", body=payload, access_token=access_token)


def pick_network_id_from_cloud(
    creds: GwnCredentials,
    *,
    hint: str = "",
    access_token: str | None = None,
) -> tuple[int | None, dict[str, Any]]:
    listed = list_networks(creds, access_token=access_token)
    if not listed.get("ok"):
        return None, listed
    items = listed.get("items") or []
    hint_l = (hint or "").strip().lower()
    if not items:
        return None, {"ok": False, "error": "gwn_no_networks", "listed": listed}
    if len(items) == 1:
        nid = items[0].get("id") or items[0].get("networkId")
        return (int(nid) if nid is not None else None), {"ok": True, "match": "single", "networks": len(items)}
    for row in items:
        name = str(row.get("name") or row.get("networkName") or "").lower()
        if hint_l and hint_l in name:
            nid = row.get("id") or row.get("networkId")
            return (int(nid) if nid is not None else None), {"ok": True, "match": "name_hint", "name": name}
    first = items[0]
    nid = first.get("id") or first.get("networkId")
    return (
        int(nid) if nid is not None else None,
        {"ok": True, "match": "first_network_default", "warning": "multiple_networks_configure_GWN_CLOUD_NETWORK_ID"},
    )


def fetch_network_snapshot(
    *,
    network_id: int,
    creds: GwnCredentials | None = None,
    access_token: str | None = None,
    include_device_details: bool = False,
) -> dict[str, Any]:
    return fetch_full_network_snapshot(
        network_id=network_id,
        creds=creds,
        access_token=access_token,
        include_device_details=include_device_details,
    )


def fetch_full_network_snapshot(
    *,
    network_id: int,
    creds: GwnCredentials | None = None,
    access_token: str | None = None,
    include_device_details: bool = True,
    device_detail_limit: int = 40,
) -> dict[str, Any]:
    loaded, err = (creds, None) if creds else load_gwn_credentials()
    if not loaded:
        return {"ok": False, "error": err, "credentials": None}
    creds = loaded
    token = access_token
    token_meta: dict[str, Any] = {}
    if not token:
        token, token_meta = get_access_token(creds)
    if not token:
        return {"ok": False, "error": "gwn_not_authenticated", "token": token_meta, "credentials": creds.as_public()}

    detail = network_detail(creds, network_id, access_token=token)
    devices = list_network_devices(creds, network_id, access_token=token, max_pages=10)
    split = split_network_devices(devices.get("items") or [])
    ssids = list_ssids(creds, network_id, access_token=token)
    clients = _paginated_list(
        creds,
        "client/list",
        {"search": "", "order": "mac", "networkId": int(network_id)},
        page_size=100,
        max_pages=20,
        access_token=token,
    )
    inventory = list_inventory(creds, network_id, access_token=token)
    wan = list_wan(creds, network_id, access_token=token)
    alerts = list_alerts(creds, network_id, access_token=token)
    portals = list_portals(creds, network_id, access_token=token)
    vouchers = list_vouchers(creds, network_id, access_token=token)
    schedules = list_schedules(creds, network_id, access_token=token)
    radius = list_radius(creds, network_id, access_token=token)
    bandwidth = list_bandwidth_rules(creds, network_id, access_token=token)

    device_details = None
    if include_device_details:
        device_details = fetch_device_details_batch(
            creds,
            network_id,
            split.get("all") or [],
            access_token=token,
            limit=device_detail_limit,
        )

    return {
        "ok": True,
        "network_id": network_id,
        "credentials": creds.as_public(),
        "network_detail": _redact(detail),
        "devices": {
            "all": _redact(devices),
            "routers": _redact({"count": len(split["routers"]), "items": split["routers"]}),
            "switches": _redact({"count": len(split["switches"]), "items": split["switches"]}),
            "access_points": _redact({"count": len(split["aps"]), "items": split["aps"]}),
        },
        "ssids": _redact(ssids),
        "clients": _redact(clients),
        "inventory_pool": _redact(inventory),
        "wan": _redact(wan),
        "alerts": _redact(alerts),
        "portals": _redact(portals),
        "vouchers": _redact(vouchers),
        "schedules": _redact(schedules),
        "radius": _redact(radius),
        "bandwidth_rules": _redact(bandwidth),
        "device_details": _redact(device_details),
    }


def sync_gwn_tenant_network_ids(*, actor: str = "RAFAEL") -> dict[str, Any]:
    """Persist resolved GWN network ids into Mongo ``gwn_cloud_tenants``."""
    creds, err = load_gwn_credentials()
    if not creds:
        return {"ok": False, "error": err}
    token, _ = get_access_token(creds)
    if not token:
        return {"ok": False, "error": "gwn_not_authenticated"}
    listed = list_networks(creds, access_token=token)
    if not listed.get("ok"):
        return listed
    # Only persist explicit mappings (avoid wrong fuzzy match across 12+ networks).
    explicit: dict[str, int] = {"bellini": 180122}
    env_lab = (os.getenv("GWN_CLOUD_NETWORK_ID_HOME") or "").strip()
    if env_lab.isdigit():
        explicit["pcdoctor_lab"] = int(env_lab)
    updates: list[dict[str, Any]] = []
    for client_id, nid in explicit.items():
        if not nid:
            continue
        try:
            import pymongo

            db = pymongo.MongoClient(os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/"), serverSelectionTimeoutMS=2000)[
                "pcdoctor_swarm"
            ]
            db.gwn_cloud_tenants.update_many(
                {"client_id": client_id},
                {
                    "$set": {
                        "gwn_network_id": int(nid),
                        "gwn_cloud_network_id": int(nid),
                        "last_sync_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "source": "gwn_cloud_live",
                    }
                },
            )
            updates.append({"client_id": client_id, "gwn_network_id": int(nid)})
        except Exception as exc:
            updates.append({"client_id": client_id, "error": str(exc)[:160]})
    return {"ok": True, "updates": updates, "networks_visible": listed.get("count")}


def gwn_api_capabilities() -> dict[str, Any]:
    """Honest comparison vs UniFi-style controller surface exposed in InnerOS today."""
    return {
        "provider": "grandstream_gwn",
        "cloud_api": {
            "auth": "oauth_client_credentials_plus_signed_oapi",
            "read": [
                "network/list",
                "network/detail",
                "ap/list (routers+switches+APs)",
                "device/info (ports, PoE, RF)",
                "client/list",
                "inventory/list",
                "ssid/list",
                "wan/list",
                "alert/list",
                "portal/list",
                "voucher/list",
                "schedule/list",
                "radius/list",
                "bandwidth/list",
            ],
            "write_governed": [
                "ssid/update (owner_approval_ref + dry_run=false)",
                "ap/reboot (owner_approval_ref + dry_run=false)",
            ],
        },
        "local_gcc": {
            "read": ["device_fabric_probe", "mongo_assets", "bellini_network_guardian"],
            "write": "not_automated_without_local_api_adapter",
        },
        "vs_unifi_ha_integration": {
            "parity_observation": [
                "AP/switch/gateway inventory",
                "SSID list",
                "connected clients (cloud API)",
                "multi-site / multi-tenant via GWN Cloud networks",
            ],
            "gaps_vs_unifi_controller": [
                "No Home Assistant GWN integration in lab — cloud API is the primary read path.",
                "RF channel utilization / per-client RSSI may require device-level APIs or manager firmware features not uniformly exposed.",
                "PoE cycle, firmware, VLAN, firewall edits remain approval-gated and partially unimplemented.",
            ],
        },
    }
