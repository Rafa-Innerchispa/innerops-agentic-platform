"""AG-60 read-only, evidence-grounded incident diagnostics.

This module never initiates network probes or device mutations. It only interprets
previously captured samples, inventory records and separately supplied topology.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def report(guardian: dict, inventory: dict, topology: dict | None = None,
           previous: dict | None = None, now: datetime | None = None) -> dict:
    """Build conservative, human-readable incident hypotheses from existing evidence.

    topology maps asset IDs to optional upstream, location, port, power, VLAN
    and relationship_verified fields. An unverified configured relationship
    is never treated as a confirmed physical dependency.
    """
    topology = topology or {}
    inventory = inventory or {}
    assets = {a["asset_id"]: a for a in inventory.get("inventory", [])
              if isinstance(a, dict) and a.get("asset_id")}
    sampled = _as_utc(guardian.get("timestamp"))
    now = now or datetime.now(timezone.utc)
    age = (now - sampled).total_seconds() if sampled else None
    fresh = age is not None and -300 <= age <= 3600
    incidents = []
    for obs in guardian.get("targets", []):
        if not isinstance(obs, dict) or obs.get("online") is not False:
            continue
        asset_id = obs.get("asset_id") or "unidentified"
        asset = assets.get(asset_id, {})
        topo = topology.get(asset_id, {})
        upstream = topo.get("upstream_asset_id") or "no identificado"
        trustworthy_topology = topo.get("relationship_verified") is True
        identity = asset.get("device_type") or obs.get("device_type") or "tipo no identificado"
        vendor = asset.get("vendor") or "no identificado"
        model = asset.get("model") or "no identificado"
        observed_ports = obs.get("tcp") or {}
        no_reply_ports = [str(k) for k, v in observed_ports.items()
                          if isinstance(v, dict) and v.get("open") is False]
        hypotheses = [
            {"cause": "routing/firewall or unsuitable probe", "confidence": "low",
             "evidence": "ICMP and tested TCP ports cannot establish device power status",
             "read_only_check": "Compare type-specific ports and a fresh cloud/device heartbeat"},
            {"cause": "device power, PoE, or upstream link", "confidence": "low",
             "evidence": "Device did not respond from the monitoring vantage point",
             "read_only_check": "Check upstream switch, PoE, uplink and UPS telemetry"},
        ]
        incidents.append({
            "asset_id": asset_id,
            "name": asset.get("device_name") or obs.get("name") or "Equipo no identificado",
            "type": identity, "device_type": identity, "vendor": vendor,
            "model": model, "ip": obs.get("ip") or asset.get("ip"),
            "site": guardian.get("site_id") or asset.get("site_id"),
            "floor": topo.get("floor") or "ubicación no identificada",
            "area": topo.get("area") or "ubicación no identificada",
            "rack": topo.get("rack") or "no identificado",
            "switch_port": topo.get("switch_port") or "no identificado",
            "upstream": upstream, "power": topo.get("power_source") or "no identificado",
            "vlan": topo.get("vlan") or "no identificada",
            "relationship_source": topo.get("relationship_source") or "no documentada",
            "relationship_verified": trustworthy_topology,
            "sample_time": guardian.get("timestamp"),
            "inventory_time": asset.get("updated_at"),
            "observations": {"icmp": obs.get("icmp") or {},
                             "tcp": observed_ports, "no_reply_tcp_ports": no_reply_ports},
            "hypotheses": hypotheses,
            "recommended_action": "Read type-specific heartbeat and upstream telemetry before proposing a physical intervention",
        })
    groups: dict[str, list] = defaultdict(list)
    for incident in incidents:
        if incident["upstream"] != "no identificado":
            groups[incident["upstream"]].append(incident)
    shared_upstreams = {}
    for upstream, members in groups.items():
        if len(members) < 2:
            continue
        shared_upstreams[upstream] = [m["asset_id"] for m in members]
        all_verified = all(m["relationship_verified"] for m in members)
        for member in members:
            member["hypotheses"].insert(0, {
                "cause": "shared switch/uplink/power",
                "confidence": "medium" if all_verified and fresh else "low",
                "evidence": f"{len(members)} nonresponsive devices share "
                            + ("verified" if all_verified else "configured, unverified")
                            + f" upstream {upstream}",
                "read_only_check": "Read shared switch interface errors, PoE and UPS state",
            })
    old = {o.get("asset_id") for o in (previous or {}).get("targets", [])
           if isinstance(o, dict) and o.get("asset_id") and o.get("online") is False}
    current = {o["asset_id"] for o in incidents}
    return {
        "status": "CURRENT" if fresh else "STALE",
        "freshness": "CURRENT" if fresh else "STALE",
        "timestamp": guardian.get("timestamp"),
        "sample_age_seconds": age, "source": guardian.get("source"),
        "site_id": guardian.get("site_id"),
        "incidents": incidents, "offline_count": len(incidents),
        "shared_upstreams": shared_upstreams,
        "new_offline_ids": sorted(current - old) if previous is not None else [],
        "recovered_ids": sorted(old - current) if previous is not None else [],
        "root_cause_verified": False, "mutations_performed": False,
        "notice": "Suspected causes only. ICMP/TCP failures are not proof of power failure.",
    }
