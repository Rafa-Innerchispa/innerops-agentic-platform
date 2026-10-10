"""Site-specific AG-60 monitoring policy. Plans are not active schedules."""
from __future__ import annotations

SITE_MONITORING_POLICIES = {
    "home_pcdoctor_lab": {
        "mode": "continuous",
        "scope": "owner_home",
        "telemetry_seconds": 90,
        "critical_hosts_seconds": 90,
        "bounded_discovery_seconds": 900,
        "historical_storage": "local_mongodb",
        "integrations": ("home_assistant", "unifi", "grandstream_local",
                         "hubitat_via_existing_events", "solar_pi01",
                         "dahua", "hikvision", "tailscale"),
        "credential_policy": "reuse_existing_vault_only",
        "mutations_allowed": False,
    },
    "bellini-i-ii": {
        "mode": "on_demand",
        "scope": "bellini_i_ii_only",
        "active_polling_enabled": False,
        "on_demand_evidence_sources": ("guardian_stored_state", "gwn_cloud",
                                       "grandstream_local", "ruijie_reyee",
                                       "hikvision", "dahua", "tailscale_subnet"),
        "historical_storage": "existing_guardian_records",
        "requires_existing_history_for_past_events": True,
        "credential_policy": "reuse_existing_vault_only",
        "mutations_allowed": False,
    },
}


def monitoring_policy(site_id: str) -> dict:
    if site_id not in SITE_MONITORING_POLICIES:
        return {"ok": False, "error": "unregistered_site"}
    return {"ok": True, "site_id": site_id, **SITE_MONITORING_POLICIES[site_id]}


def active_scan_allowed(site_id: str, *, triggered_by_owner: bool = False) -> bool:
    item = SITE_MONITORING_POLICIES.get(site_id)
    return bool(item and (item["mode"] == "continuous" or triggered_by_owner))
