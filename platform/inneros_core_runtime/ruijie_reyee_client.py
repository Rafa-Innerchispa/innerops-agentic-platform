"""Ruijie / Reyee Cloud REST client (Ruijie Cloud northbound API).

Credentials (env or owner_vault category ``ruijie_reyee``):
  RUIJIE_CLOUD_BASE_URL (default https://cloud.ruijienetworks.com)
  RUIJIE_CLOUD_APP_ID, RUIJIE_CLOUD_SECRET
  RUIJIE_CLOUD_ACCOUNT, RUIJIE_CLOUD_PASSWORD
Optional site network group (buildingId):
  RUIJIE_CLOUD_GROUP_ID, RUIJIE_CLOUD_GROUP_ID_BELLINI
"""

from __future__ import annotations

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

DEFAULT_BASE_URL = "https://cloud.ruijienetworks.com"

_SESSION: dict[str, Any] = {}

SITE_GROUP_ENV: dict[str, str] = {
    "bellini": "RUIJIE_CLOUD_GROUP_ID_BELLINI",
    "bellini-i-ii": "RUIJIE_CLOUD_GROUP_ID_BELLINI",
    "home_pcdoctor_lab": "RUIJIE_CLOUD_GROUP_ID_HOME",
    "pcdoctor_lab": "RUIJIE_CLOUD_GROUP_ID_HOME",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if re.search(r"(secret|token|password|passwd|credential|authorization)", str(k), re.I)
            else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(x) for x in value]
    return value


@dataclass(frozen=True)
class RuijieCredentials:
    base_url: str
    app_id: str
    secret: str
    account: str
    password: str
    source: str

    def as_public(self) -> dict[str, str]:
        return {
            "base_url": self.base_url,
            "app_id": self.app_id,
            "account": self.account,
            "source": self.source,
            "password_configured": bool(self.password),
        }


def _vault(key: str) -> str:
    try:
        from raphiia_openai import owner_vault

        row = owner_vault.get_owner_credential(key, category="ruijie_reyee", reveal=True)
        if isinstance(row, dict) and row.get("ok") and row.get("secret"):
            return str(row["secret"]).strip()
    except Exception:
        pass
    return ""


def load_ruijie_credentials() -> tuple[RuijieCredentials | None, str | None]:
    app_id = (os.getenv("RUIJIE_CLOUD_APP_ID") or _vault("app_id")).strip()
    secret = (os.getenv("RUIJIE_CLOUD_SECRET") or os.getenv("RUIJIE_CLOUD_SECRET_KEY") or _vault("secret_key")).strip()
    account = (os.getenv("RUIJIE_CLOUD_ACCOUNT") or _vault("account")).strip()
    password = (os.getenv("RUIJIE_CLOUD_PASSWORD") or _vault("password")).strip()
    base = (os.getenv("RUIJIE_CLOUD_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    if not all([app_id, secret, account, password]):
        return None, "ruijie_cloud_credentials_missing"
    src = "env" if os.getenv("RUIJIE_CLOUD_APP_ID") else "owner_vault:ruijie_reyee"
    return RuijieCredentials(base, app_id, secret, account, password, src), None


def resolve_group_id(*, client_id: str = "", site_id: str = "", group_id: int | None = None) -> int | None:
    if group_id and int(group_id) > 0:
        return int(group_id)
    for token in (site_id, client_id):
        t = (token or "").strip().lower()
        if t in SITE_GROUP_ENV:
            raw = (os.getenv(SITE_GROUP_ENV[t]) or "").strip()
            if raw.isdigit():
                return int(raw)
    raw = (os.getenv("RUIJIE_CLOUD_GROUP_ID") or "").strip()
    return int(raw) if raw.isdigit() else None


def _http(method: str, url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 45.0) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method.upper())
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), payload


def login(creds: RuijieCredentials, *, force: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cache_key = f"{creds.base_url}|{creds.app_id}|{creds.account}"
    cached = _SESSION.get(cache_key)
    if not force and cached and float(cached.get("expires_at") or 0) > time.time() + 20:
        return cached, {"ok": True, "cached": True}

    q = urllib.parse.urlencode(
        {
            "appid": creds.app_id,
            "secret": creds.secret,
            "account": creds.account,
            "password": creds.password,
        }
    )
    url = f"{creds.base_url}/service/api/login?{q}"
    status, text = _http("GET", url)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, {"ok": False, "error": "ruijie_login_invalid_json", "http_status": status}
    if status >= 400 or int(payload.get("code", -1)) != 0:
        return None, {"ok": False, "error": "ruijie_login_failed", "http_status": status, "detail": _redact(payload)}
    session = {
        "access_token": payload.get("access_token"),
        "group_id": payload.get("groupId"),
        "tenant_id": payload.get("tenantId"),
        "tenant_name": payload.get("tenantName"),
        "account_id": payload.get("accountId"),
        "expires_at": time.time() + 25 * 60,
    }
    _SESSION[cache_key] = session
    return session, {"ok": True, "cached": False, "tenant_name": session.get("tenant_name")}


def refresh_token(creds: RuijieCredentials, access_token: str) -> tuple[str | None, dict[str, Any]]:
    q = urllib.parse.urlencode({"appid": creds.app_id, "secret": creds.secret, "access_token": access_token})
    url = f"{creds.base_url}/service/api/token/refresh?{q}"
    status, text = _http("GET", url)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, {"ok": False, "error": "refresh_invalid_json"}
    if int(payload.get("code", -1)) != 0:
        return None, {"ok": False, "error": "refresh_failed", "detail": _redact(payload)}
    token = str(payload.get("access_token") or payload.get("accessToken") or "")
    return token or None, {"ok": True}


def _api(
    creds: RuijieCredentials,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sess, meta = session if session else login(creds)
    if not sess:
        return {"ok": False, "error": "ruijie_not_authenticated", "login": meta}
    token = str(sess.get("access_token") or "")
    q = dict(query or {})
    q["access_token"] = token
    qs = urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})
    url = f"{creds.base_url}{path}?{qs}" if qs else f"{creds.base_url}{path}"
    body_bytes = None
    headers: dict[str, str] = {}
    if json_body is not None:
        body_bytes = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, text = _http(method, url, body=body_bytes, headers=headers)

    def _parse() -> dict[str, Any]:
        try:
            return json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            return {"raw": text[:500]}

    payload = _parse()
    code = int(payload.get("code", 0) if payload.get("code") is not None else 0)
    if code == 4:
        new_token, ref = refresh_token(creds, token)
        if new_token:
            sess["access_token"] = new_token
            q["access_token"] = new_token
            qs = urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})
            url = f"{creds.base_url}{path}?{qs}"
            status, text = _http(method, url, body=body_bytes, headers=headers)
            payload = _parse()
            code = int(payload.get("code", 0) if payload.get("code") is not None else 0)
        else:
            return {"ok": False, "error": "token_expired", "refresh": ref}

    ok = status < 400 and code == 0
    return {
        "ok": ok,
        "http_status": status,
        "code": code,
        "msg": payload.get("msg"),
        "data": payload,
        "session": {"tenant_name": sess.get("tenant_name"), "root_group_id": sess.get("group_id")},
    }


def list_network_groups(creds: RuijieCredentials, *, root_group_id: int | None = None, page: int = 1, per_page: int = 50) -> dict[str, Any]:
    sess, _ = login(creds)
    if not sess:
        return {"ok": False, "error": "login_failed"}
    gid = int(root_group_id or sess.get("group_id") or 0)
    out = _api(
        creds,
        "POST",
        "/service/api/maint/network/list",
        query={"page": page, "per_page": per_page},
        json_body={"groupId": str(gid)},
        session=sess,
    )
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    rows = data.get("dataList") or data.get("list") or []
    return {"ok": True, "count": len(rows), "items": rows, "total_count": data.get("totalCount"), "root_group_id": gid}


def list_devices(
    creds: RuijieCredentials,
    group_id: int,
    common_type: str,
    *,
    page: int = 0,
    per_page: int = 100,
) -> dict[str, Any]:
    out = _api(
        creds,
        "GET",
        "/service/api/maint/devices",
        query={
            "group_id": int(group_id),
            "common_type": common_type,
            "page": page,
            "per_page": per_page,
        },
    )
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    devices = data.get("deviceList") or []
    return {"ok": True, "count": len(devices), "items": devices, "total_count": data.get("totalCount"), "common_type": common_type}


def list_all_devices_for_group(creds: RuijieCredentials, group_id: int) -> dict[str, Any]:
    merged: dict[str, list[dict[str, Any]]] = {"AP": [], "Switch": [], "Gateway": []}
    errors: dict[str, Any] = {}
    for ctype in ("AP", "Switch", "Gateway"):
        page = 0
        while page < 10:
            chunk = list_devices(creds, group_id, ctype, page=page, per_page=100)
            if not chunk.get("ok"):
                errors[ctype] = chunk
                break
            items = chunk.get("items") or []
            merged[ctype].extend(items)
            total = int(chunk.get("total_count") or 0)
            if len(items) < 100 or (total and len(merged[ctype]) >= total):
                break
            page += 1
    return {"ok": not errors or any(merged.values()), "group_id": group_id, "devices": merged, "errors": errors}


def list_online_clients(creds: RuijieCredentials, group_id: int, *, page: int = 1, per_page: int = 100) -> dict[str, Any]:
    out = _api(
        creds,
        "GET",
        "/logbizagent/logbiz/api/sta/current_users/vague",
        query={"groupId": int(group_id), "page": page, "per_page": per_page},
    )
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    return {"ok": True, "count": data.get("count") or len(data.get("list") or []), "items": data.get("list") or []}


def get_device_detail(creds: RuijieCredentials, serial_number: str) -> dict[str, Any]:
    sn = urllib.parse.quote(serial_number.strip())
    return _api(creds, "GET", f"/service/api/device/{sn}")


def list_switch_ports(creds: RuijieCredentials, serial_number: str, *, page_index: int = 0, page_size: int = 100) -> dict[str, Any]:
    sn = urllib.parse.quote(serial_number.strip())
    return _api(
        creds,
        "GET",
        f"/service/api/conf/switch/device/{sn}/ports",
        query={"page_index": page_index, "page_size": page_size},
    )


def list_gateway_ports(creds: RuijieCredentials, serial_number: str) -> dict[str, Any]:
    sn = urllib.parse.quote(serial_number.strip())
    return _api(creds, "GET", f"/service/api/gateway/intf/info/{sn}")


def pick_group_id_from_cloud(creds: RuijieCredentials, hint: str = "") -> tuple[int | None, dict[str, Any]]:
    listed = list_network_groups(creds)
    if not listed.get("ok"):
        return None, listed
    items = listed.get("items") or []
    hint_l = (hint or "").strip().lower()
    for row in items:
        name = str(row.get("name") or row.get("networkName") or "").lower()
        bid = row.get("buildingId") or row.get("groupId") or row.get("id")
        if hint_l and hint_l in name and bid is not None:
            return int(bid), {"ok": True, "match": "name_hint", "name": name}
    if len(items) == 1:
        bid = items[0].get("buildingId") or items[0].get("groupId")
        return (int(bid) if bid is not None else None), {"ok": True, "match": "single"}
    return None, {"ok": True, "match": "unresolved", "networks": [{"id": r.get("buildingId"), "name": r.get("name")} for r in items[:20]]}


def fetch_full_network_snapshot(
    *,
    group_id: int,
    creds: RuijieCredentials | None = None,
    include_switch_ports: bool = True,
    switch_port_limit: int = 15,
) -> dict[str, Any]:
    loaded, err = (creds, None) if creds else load_ruijie_credentials()
    if not loaded:
        return {"ok": False, "error": err}
    creds = loaded
    sess, login_meta = login(creds)
    if not sess:
        return {"ok": False, "error": "login_failed", "detail": login_meta}
    devices = list_all_devices_for_group(creds, int(group_id))
    clients = list_online_clients(creds, int(group_id), per_page=200)
    switch_ports: list[dict[str, Any]] = []
    if include_switch_ports:
        for sw in (devices.get("devices") or {}).get("Switch") or []:
            sn = str(sw.get("serialNumber") or "").strip()
            if not sn:
                continue
            ports = list_switch_ports(creds, sn)
            switch_ports.append(
                {
                    "serial_number": sn,
                    "alias": sw.get("aliasName") or sw.get("name"),
                    "online": sw.get("onlineStatus"),
                    "ports": _redact(ports.get("data") if ports.get("ok") else ports),
                }
            )
            if len(switch_ports) >= switch_port_limit:
                break
    gateways_ports: list[dict[str, Any]] = []
    for gw in (devices.get("devices") or {}).get("Gateway") or []:
        sn = str(gw.get("serialNumber") or "").strip()
        if not sn:
            continue
        gp = list_gateway_ports(creds, sn)
        gateways_ports.append({"serial_number": sn, "detail": _redact(gp.get("data") if gp.get("ok") else gp)})

    return {
        "ok": True,
        "group_id": int(group_id),
        "credentials": creds.as_public(),
        "login": _redact({"tenant_name": sess.get("tenant_name"), "root_group_id": sess.get("group_id")}),
        "devices": _redact(devices),
        "clients": _redact(clients),
        "switch_ports": switch_ports,
        "gateway_ports": gateways_ports,
    }


def reyee_api_capabilities() -> dict[str, Any]:
    return {
        "provider": "ruijie_reyee",
        "brand_note": "Reyee is Ruijie Cloud-managed; uses Ruijie Cloud REST (same as enterprise Ruijie).",
        "cloud_api": {
            "auth": "appid+secret+account+password → access_token (30 min)",
            "read": [
                "maint/network/list",
                "maint/devices (AP, Switch, Gateway)",
                "sta/current_users/vague",
                "device/{sn}",
                "conf/switch/device/{sn}/ports",
                "gateway/intf/info/{sn}",
            ],
            "write_governed": ["planned: SSID/account changes via samTransfer APIs with owner approval"],
        },
        "local_lan": {
            "read": ["device_fabric_probe (Ruijie Easy-Smart / Reyee web UI on LAN)"],
            "example_bellini_switch_ip": "192.168.3.172",
        },
        "credentials_required": [
            "Apply appid/secret via service_rj@ruijienetworks.com",
            "RUIJIE_CLOUD_ACCOUNT + RUIJIE_CLOUD_PASSWORD (cloud login)",
        ],
    }
