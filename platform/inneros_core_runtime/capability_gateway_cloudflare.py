"""Safe, read-only AG-44 Cloudflare capabilities for MCP Small.

Owner Vault remains the sole credential source. The gateway deliberately
returns only allowlisted zone metadata, never API tokens, raw DNS records,
tunnel service endpoints, ruleset contents, or account identifiers.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from inneros_core_runtime.capability_gateway import register_capability


def _backend():
    from inneros_core_runtime.agents import ag44_cloud_deployer

    return ag44_cloud_deployer


def _failure(exc: Exception) -> dict[str, Any]:
    """Do not echo backend/HTTP exception bodies; they may contain private data."""
    detail = str(exc).lower()
    if "zone_not_allowlisted" in detail or "hostname_not_allowlisted" in detail:
        code = "ZONE_NOT_ALLOWLISTED"
    elif "cloudflare_credentials_missing" in detail or "credentials_missing" in detail:
        code = "CREDENTIALS_NOT_CONFIGURED"
    elif "zone_not_found" in detail:
        code = "ZONE_NOT_VISIBLE"
    elif any(token in detail for token in ("http_401", "http_403", "forbidden", "permission", "9109")):
        code = "CLOUDFLARE_PERMISSION_DENIED"
    else:
        code = "CLOUDFLARE_READ_UNAVAILABLE"
    return {"ok": False, "error": code, "read_only": True}


def _status(params: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    try:
        ag = _backend()
        name = ag._validate_zone(str(params.get("zone_name") or ag.CF_DEFAULT_ZONE))
        creds = ag._cloudflare_credentials(name)
        zone = ag._get_zone(name, creds=creds)
        dns_read = False
        count: int | None = None
        try:
            response = ag._cf_request(
                "GET", f"/zones/{zone['id']}/dns_records?per_page=1", creds=creds
            )
            info = response.get("result_info") or {}
            if "total_count" in info:
                count = int(info["total_count"])
            dns_read = True
        except Exception:
            # Lack of DNS:Read must not make Zone:Read look unavailable.
            pass
        return {
            "ok": True,
            "read_only": True,
            "zone": {"name": name, "status": str(zone.get("status") or "unknown")},
            "permissions": {"zone_read": True, "dns_read": dns_read},
            "dns_record_count": count,
        }
    except Exception as exc:
        return _failure(exc)


def _inventory(_params: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    """List all *allowlisted* zones visible to the existing account-scoped token.

    This does not claim to enumerate zones outside the AG-44 allowlist.
    Account ID and token come only from Owner Vault and are never returned.
    """
    try:
        ag = _backend()
        creds = ag._cloudflare_credentials(ag.CF_DEFAULT_ZONE)
        allowed = set(ag.CF_ZONE_VAULT_CATEGORIES)
        found: dict[str, dict[str, Any]] = {}
        truncated = False
        for page in range(1, 11):
            qs = urllib.parse.urlencode(
                {"account.id": creds["account_id"], "page": page, "per_page": 50}
            )
            response = ag._cf_request("GET", f"/zones?{qs}", creds=creds)
            rows = response.get("result") or []
            for z in rows:
                name = str(z.get("name") or "").strip().lower()
                if name in allowed:
                    found[name] = {
                        "name": name,
                        "status": str(z.get("status") or "unknown"),
                        "name_servers": [
                            str(ns)[:120] for ns in (z.get("name_servers") or [])[:4]
                        ],
                    }
            info = response.get("result_info") or {}
            total_pages = int(info.get("total_pages") or 0)
            if total_pages:
                if page >= total_pages:
                    break
            elif len(rows) < 50:
                break
            if page == 10:
                truncated = True
        return {
            "ok": True,
            "read_only": True,
            "scope": "ag44_allowlisted_zones_only",
            "complete_account_inventory": False,
            "allowlisted_count": len(allowed),
            "visible_count": len(found),
            "truncated": truncated,
            "zones": [found[k] for k in sorted(found)],
        }
    except Exception as exc:
        return _failure(exc)


def _tunnel(params: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    try:
        ag = _backend()
        host = str(params.get("hostname") or "").strip().lower().rstrip(".")
        if not host:
            return {"ok": False, "error": "HOSTNAME_REQUIRED", "read_only": True}
        zone = next(
            (z for z in sorted(ag.CF_ZONE_VAULT_CATEGORIES, key=len, reverse=True)
             if host == z or host.endswith("." + z)),
            None,
        )
        if zone is None:
            return {"ok": False, "error": "ZONE_NOT_ALLOWLISTED", "read_only": True}
        ag._validate_hostname(host, zone)
        # Never permit arbitrary config_path from callers.
        snapshot = ag.cloudflare_tunnel_ingress_status(hostname=host, config_path="")
        if not snapshot.get("ok"):
            return {"ok": False, "error": "CLOUDFLARE_READ_UNAVAILABLE", "read_only": True}
        count = int(snapshot.get("count") or 0)
        return {
            "ok": True,
            "read_only": True,
            "hostname": host,
            "configured": count > 0,
            "ingress_rule_count": count,
        }
    except Exception as exc:
        return _failure(exc)


def _manifest(cid: str, title: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability_id": cid,
        "version": "1.0.0",
        "domain": "cloudflare",
        "title": title,
        "description": description,
        "keywords": ["cloudflare", "ag-44", "zones", "status", "dns", "tunnel"],
        "risk_class": "low",
        "mode": "read_only",
        "required_scopes": ["ralfia:read"],
        "parameters_schema": {"type": "object", "properties": properties, "additionalProperties": False},
    }


def register_cloudflare_read_capabilities() -> int:
    specs = [
        (
            _manifest(
                "cloudflare.zone.status.read.v1",
                "Cloudflare zone status (AG-44, read-only)",
                "Sanitized status and DNS-read permission for one allowlisted zone.",
                {"zone_name": {"type": "string"}},
            ),
            _status,
        ),
        (
            _manifest(
                "cloudflare.zones.inventory.read.v1",
                "Cloudflare allowlisted zone inventory (AG-44, read-only)",
                "Account-scoped, paginated list of AG-44 allowlisted zones; no secrets or DNS values.",
                {},
            ),
            _inventory,
        ),
        (
            _manifest(
                "cloudflare.tunnel.status.read.v1",
                "Cloudflare tunnel ingress presence (AG-44, read-only)",
                "Only report whether an allowlisted hostname has ingress entries; no service URLs.",
                {"hostname": {"type": "string"}},
            ),
            _tunnel,
        ),
    ]
    for manifest, handler in specs:
        register_capability(manifest, handler)
    return len(specs)
