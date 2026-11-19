"""Read-only identity reconciliation: Bellini Guardian probes versus GWN Cloud.

Never assumes the same IP means the same physical device. No network access,
credentials, mutable operations or repair commands in this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_timestamp(value: Any):
    try:
        if isinstance(value, (int, float)):
            stamp = float(value) / (1000 if value > 10**11 else 1)
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def _mac(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    stripped = "".join(c.lower() for c in value if c.isalnum())
    return stripped if len(stripped) == 12 and all(c in "0123456789abcdef" for c in stripped) else ""


def reconcile(guardian: dict, inventory: dict, cloud: dict | None = None,
              now: datetime | None = None, max_age_seconds: int = 1800) -> dict:
    """Compare source identities and freshness; make NO physical-outage claims.

    A MAC link established by inventory is stronger than a same-IP coincidence.
    Cloud status is provider availability, not proof of physical connectivity.
    """
    now = now or datetime.now(timezone.utc)
    cloud = cloud or inventory.get("cloud_live") or {}
    devices = cloud.get("devices") or {}
    all_devices = devices.get("all") or {}
    rows = all_devices.get("items")
    # A successful outer call does not establish that the nested GWN API
    # succeeded. Never silently convert provider failure into an empty,
    # apparently healthy inventory.
    if (not cloud.get("ok") or not isinstance(all_devices, dict)
            or all_devices.get("ok") is False
            or not isinstance(rows, list) or not rows):
        return {"status": "UNAVAILABLE", "reason": "gwn_cloud_snapshot_not_available",
                "source": "gwn_cloud", "mutations_performed": False,
                "identity_verified_by_ip_only": False}
    cloud_ap_macs = {
        _mac(row.get("mac"))
        for row in (devices.get("access_points") or {}).get("items", [])
        if isinstance(row, dict) and _mac(row.get("mac"))
    }
    samples = [r for r in guardian.get("targets", []) if isinstance(r, dict)]
    by_asset = {s.get("asset_id"): s for s in samples if s.get("asset_id")}
    by_ip = {}
    for s in samples:
        if s.get("ip"):
            by_ip.setdefault(s["ip"], []).append(s)
    assets = [a for a in inventory.get("inventory", []) if isinstance(a, dict)]
    assets_by_mac = {_mac(a.get("mac")): a for a in assets if _mac(a.get("mac"))}
    gtime = _utc_timestamp(guardian.get("timestamp"))
    g_fresh = bool(gtime and -300 <= (now - gtime).total_seconds() <= max_age_seconds)
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mac = _mac(row.get("mac"))
        ip = row.get("ipv4")
        asset = assets_by_mac.get(mac) if mac else None
        matched = by_asset.get(asset.get("asset_id")) if asset else None
        match_method = "INVENTORY_MAC" if matched else None
        if not matched and ip and len(by_ip.get(ip, [])) == 1:
            matched = by_ip[ip][0]
            match_method = "IP_ONLY_UNVERIFIED"
        seen = _utc_timestamp(row.get("lastSeen"))
        cloud_fresh = bool(seen and -300 <= (now - seen).total_seconds() <= max_age_seconds)
        cloud_online = row.get("status") == 1
        # Prefer the provider's explicit AP family; GWN78xx and GWN77xx
        # are switches, while GWN7052F is a router, not an AP.
        is_ap = (mac in cloud_ap_macs if cloud_ap_macs
                 else str(row.get("apType") or "").startswith("GWN76"))
        if not cloud_fresh:
            classification = "CLOUD_SAMPLE_STALE"
        elif not matched:
            classification = "NOT_IN_GUARDIAN" if is_ap else "NO_VERIFIED_GUARDIAN_IDENTITY"
        elif not g_fresh:
            classification = "GUARDIAN_SAMPLE_STALE"
        elif match_method == "IP_ONLY_UNVERIFIED":
            classification = "POTENTIAL_IDENTITY_MATCH_VERIFY_MAC"
        elif ip != matched.get("ip"):
            classification = "IP_DIFFERENCE_VERIFY_INTERFACES_OR_DHCP"
        elif cloud_online and matched.get("online") is False:
            classification = "DIFFERENT_SOURCE_CONNECTIVITY_EVIDENCE"
        else:
            classification = "SOURCES_CONSISTENT_WITH_LIMITATIONS"
        results.append({
            "cloud_name": row.get("name") or "sin identificar",
            "cloud_type": row.get("apType") or "no identificado",
            "cloud_ip": ip, "cloud_mac": row.get("mac"),
            "cloud_status": "ONLINE" if cloud_online else "OFFLINE" if row.get("status") == 0 else "UNKNOWN",
            "cloud_seen_at": seen.isoformat() if seen else None,
            "cloud_fresh": cloud_fresh,
            "guardian_asset_id": matched.get("asset_id") if matched else None,
            "guardian_name": matched.get("name") if matched else None,
            "guardian_ip": matched.get("ip") if matched else None,
            "guardian_probe_responds": matched.get("online") if matched else None,
            "identity_match": match_method or "NOT_MATCHED",
            "classification": classification,
            "root_cause_verified": False,
        })
    missing = [r for r in results if r["classification"] == "NOT_IN_GUARDIAN"]
    stale_cloud_count = sum(not r["cloud_fresh"] for r in results)
    snapshot_status = (
        "GUARDIAN_STALE" if not g_fresh
        else "CLOUD_STALE" if stale_cloud_count == len(results)
        else "PARTIAL_CLOUD_STALE" if stale_cloud_count else "CURRENT"
    )
    return {
        "status": snapshot_status,
        "cloud_stale_devices": stale_cloud_count,
        "source": "gwn_cloud_and_guardian",
        "guardian_sample_at": guardian.get("timestamp"),
        "cloud_devices": len(results),
        "unmonitored_cloud_aps": len(missing),
        "cloud_accesspoints_not_monitored": [
            {"name": r["cloud_name"], "model": r["cloud_type"],
             "ip": r["cloud_ip"], "mac": r["cloud_mac"]}
            for r in missing
        ],
        "comparisons": results,
        "identity_verified_by_ip_only": False,
        "root_cause_verified": False,
        "mutations_performed": False,
        "recommended_read_only_checks": [
            "Compare inventory MAC with controller MAC and current DHCP leases",
            "Read switch FDB / LLDP / PoE status before inferring physical dependencies",
            "Check the router VLAN/interface assignments when the same MAC shows multiple IPs",
        ],
    }
