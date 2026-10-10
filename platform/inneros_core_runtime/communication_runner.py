"""AG-60 periodic local-first monitor. Safe for systemd timer once approved."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import json
from typing import Any

from inneros_core_runtime.network_guardian import probe_host
from inneros_core_runtime.communication_history import write_history
from inneros_core_runtime.communication_observer import live_home_snapshot
from inneros_core_runtime.physical_bus_observer import host_observation
from inneros_core_runtime.unifi_readonly import read_unifi_site

# Explicit assets grounded in the local home's operator inventory.
CRITICAL_HOSTS = {
    "gateway": "192.168.1.1",
    "intel_primary": "192.168.1.4",
    "amd_secondary": "192.168.1.5",
    "pi01_solar_bridge": "192.168.1.97",
}


def collect_cycle(site_id: str = "home_pcdoctor_lab", *, save: bool = False,
                  critical_hosts: dict[str, str] | None = None) -> dict[str, Any]:
    if site_id != "home_pcdoctor_lab":
        return {"ok": False, "error": "unsupported_unmapped_site"}
    gaps: list[str] = []
    try:
        snapshot = live_home_snapshot(site_id)
    except Exception as exc:
        snapshot = {"site_id": site_id, "devices": [], "solar_edge_sources": []}
        gaps.append("ha_observer:" + type(exc).__name__)
    # HA failure must not prevent local port, serial, VPN and LAN diagnostics.
    if "collector_host" not in snapshot:
        snapshot["collector_host"] = host_observation()
    if "unifi_controller" not in snapshot:
        snapshot["unifi_controller"] = read_unifi_site(site_id=site_id)
    if not snapshot.get("ok"):
        gaps.append("ha_registry_unavailable")
    gaps.extend(snapshot.get("gaps") or [])
    targets = critical_hosts if critical_hosts is not None else CRITICAL_HOSTS
    checks = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {key: pool.submit(probe_host, ip, site_id) for key, ip in targets.items()}
        for label, future in futures.items():
            try:
                checks.append({"label": label, **future.result(timeout=8)})
            except Exception as exc:
                checks.append({"label": label, "health": "UNKNOWN",
                               "error": type(exc).__name__})
    snapshot["critical_hosts"] = checks
    snapshot["site_id"] = site_id
    snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["gaps"] = sorted(set(gaps))
    snapshot["read_only_devices"] = True
    result: dict[str, Any] = {
        "ok": True, "partial": bool(gaps) or not snapshot["unifi_controller"].get("ok"),
        "site_id": site_id, "observation": snapshot, "saved": False,
    }
    if save:
        saved = write_history(snapshot)
        result["persistence"] = saved
        result["saved"] = bool(saved.get("ok"))
        if not saved.get("ok"):
            result["partial"] = True
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="AG-60 home universal communications cycle")
    p.add_argument("--site", default="home_pcdoctor_lab")
    p.add_argument("--save", action="store_true")
    args = p.parse_args()
    result = collect_cycle(args.site, save=args.save)
    # Summary contains neither API credentials nor raw private client identities.
    observation = result.get("observation") or {}
    summary = {
        "ok": result.get("ok"), "partial": result.get("partial"),
        "site_id": result.get("site_id"),
        "ha_devices": len(observation.get("devices") or []),
        "critical_hosts": [
            {"label": row.get("label"), "health": row.get("health")}
            for row in observation.get("critical_hosts") or []
        ],
        "unifi_api_ok": bool((observation.get("unifi_controller") or {}).get("ok")),
        "gaps": observation.get("gaps") or [],
        "saved": result.get("saved"),
        "save_error": (result.get("persistence") or {}).get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
