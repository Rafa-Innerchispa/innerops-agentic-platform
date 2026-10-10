"""Official UniFi local Network API adapter: GET-only and scoped to site LAN.

Requires a local UniFi Network API key (never logged). Exact endpoint versions
depend on installed Network release. See Network > Integrations API docs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import os
import re
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit, parse_qs
import httpx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _controller_host(host: str, site_id: str) -> str:
    from inneros_core_runtime.device_fabric import _site
    site = _site(site_id)
    if not site:
        raise ValueError("unknown_site")
    addr = ipaddress.ip_address(host)
    if not isinstance(addr, ipaddress.IPv4Address):
        raise ValueError("controller_ipv4_required")
    if addr not in ipaddress.ip_network(site["authorized_cidr"], strict=False):
        raise ValueError("controller_outside_authorized_site")
    return str(addr)


def _get_json(host: str, path: str, key: str, *,
              timeout: float = 4.0, ca_bundle: str | None = None) -> dict[str, Any]:
    parts = urlsplit(path)
    query = parse_qs(parts.query, keep_blank_values=True)
    if parts.scheme or parts.netloc or parts.fragment or not re.fullmatch(r"/v1/[a-zA-Z0-9/_-]+", parts.path):
        raise ValueError("read_only_api_path_denied")
    if any(k not in {"offset", "limit"} or len(v) != 1 or not v[0].isdigit() for k, v in query.items()):
        raise ValueError("read_only_api_query_denied")
    verify: bool | str = ca_bundle if ca_bundle else True
    url = "https://" + host + "/integration" + path
    with httpx.Client(timeout=timeout, verify=verify, follow_redirects=False) as client:
        response = client.get(url, headers={"X-API-Key": key, "Accept": "application/json"})
        response.raise_for_status()
        value = response.json()
    return value if isinstance(value, dict) else {"data": value}


def _paged(host: str, path: str, key: str, fetch: Callable[..., dict[str, Any]],
           *, page_size: int = 100, max_pages: int = 4) -> list[dict[str, Any]]:
    # URL construction allows GET and pagination only, never config writes.
    rows: list[dict[str, Any]] = []
    for page in range(max_pages):
        params = urlencode({"offset": page * page_size, "limit": page_size})
        payload = fetch(host, path + "?" + params, key)
        group = payload.get("data")
        if isinstance(group, list):
            rows.extend(x for x in group if isinstance(x, dict))
        elif isinstance(payload.get("items"), list):
            rows.extend(x for x in payload["items"] if isinstance(x, dict))
        elif isinstance(payload, list):
            rows.extend(x for x in payload if isinstance(x, dict))
        if isinstance(payload.get("totalCount"), int):
            if page * page_size + len(group or []) >= payload["totalCount"]:
                break
        elif not group or len(group) < page_size:
            break
    return rows[: page_size * max_pages]


def read_unifi_site(site_id: str = "home_pcdoctor_lab", controller: str = "192.168.1.1",
                    api_key: str | None = None, getter: Callable[..., dict[str, Any]] | None = None,
                    max_device_details: int = 16) -> dict[str, Any]:
    """Observe AP/gateway/switch clients and ports without sending any mutations."""
    try:
        host = _controller_host(controller, site_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    key = api_key or os.getenv("UNIFI_LOCAL_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "unifi_local_api_key_missing",
                "source": "unifi_official_local_api", "read_only": True}
    ca = os.getenv("UNIFI_LOCAL_CA_BUNDLE", "").strip() or None
    fetch = getter or (lambda hostname, path, api_token:
                       _get_json(hostname, path, api_token, ca_bundle=ca))
    at = _now()
    try:
        sites = _paged(host, "/v1/sites", key, fetch, max_pages=2)
        if not sites:
            return {"ok": False, "error": "unifi_sites_empty", "observed_at": at}
        if len(sites) != 1 and not os.getenv("UNIFI_SITE_ID"):
            return {"ok": False, "error": "unifi_site_id_required", "site_count": len(sites)}
        target_id = os.getenv("UNIFI_SITE_ID") or str(sites[0].get("id") or "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", target_id):
            return {"ok": False, "error": "invalid_site_identifier"}
        devices = _paged(host, f"/v1/sites/{target_id}/devices", key, fetch)
        clients = _paged(host, f"/v1/sites/{target_id}/clients", key, fetch)
        normalized_devices = []
        for item in devices:
            entry = {
                "id": item.get("id"), "name": item.get("name"),
                "model": item.get("model"), "type": item.get("type"),
                "mac": item.get("macAddress") or item.get("mac"),
                "ip": item.get("ipAddress"),
                "state": item.get("state"),
                "source": "unifi_official_local_api", "observed_at": at,
                "ports": [], "radios": [], "uplink_device_id": None,
            }
            if item.get("id") and len(normalized_devices) < max_device_details:
                identifier = str(item["id"])
                if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identifier):
                    try:
                        detail = fetch(host, f"/v1/sites/{target_id}/devices/{identifier}", key)
                        data = detail.get("data") if isinstance(detail.get("data"), dict) else detail
                        interfaces = data.get("interfaces") or {}
                        entry["ports"] = interfaces.get("ports") or []
                        entry["radios"] = interfaces.get("radios") or []
                        entry["uplink_device_id"] = (data.get("uplink") or {}).get("deviceId")
                        entry["ip"] = data.get("ipAddress") or entry["ip"]
                        entry["state"] = data.get("state") or entry["state"]
                    except (httpx.HTTPError, ValueError, TypeError, KeyError):
                        entry["details_incomplete"] = True
            normalized_devices.append(entry)
        normalized_clients = [
            {"id": x.get("id"), "name": x.get("name"),
             "mac": x.get("macAddress") or x.get("mac"),
             "ip": x.get("ipAddress"),
             "type": x.get("type"), "ssid": x.get("ssid"),
             "upstream_device_id": x.get("uplinkDeviceId") or x.get("accessPointId"),
             "source": "unifi_official_local_api", "observed_at": at}
            for x in clients
        ]
        return {"ok": True, "site_id": site_id, "controller": host,
                "unifi_site_id": target_id,
                "devices": normalized_devices, "clients": normalized_clients,
                "device_count": len(normalized_devices), "client_count": len(normalized_clients),
                "observed_at": at, "read_only": True,
                "radio_utilization_collected": False,
                "historical_events_collected": False}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": type(exc).__name__, "read_only": True,
                "source": "unifi_official_local_api", "observed_at": at}
