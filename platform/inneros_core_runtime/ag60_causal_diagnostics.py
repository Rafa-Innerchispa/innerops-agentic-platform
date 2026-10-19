"""Read-only AG-60 inventory enrichment and explainable outage correlation."""
from collections import defaultdict
from datetime import datetime, timezone


def report(guardian, inventory, topology=None, previous=None):
    """No network access: all results come from supplied observed data."""
    topology = topology or {}
    assets = {a["asset_id"]: a for a in inventory.get("inventory", []) if a.get("asset_id")}
    timestamp = guardian.get("timestamp")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()
    except (ValueError, TypeError, AttributeError):
        age = None
    incidents = []
    for obs in guardian.get("targets", []):
        if obs.get("online") is not False:
            continue
        ident = obs.get("asset_id", "unidentified")
        asset = assets.get(ident, {})
        upstream = topology.get(ident, {})
        hypotheses = [
            {"cause": "routing, firewall or inappropriate probe", "confidence": "low",
             "why": "failed ICMP and selected TCP ports alone cannot prove physical outage",
             "verify_read_only": "Check protocol-specific ports and fresh cloud heartbeat"},
            {"cause": "PoE, switch uplink or power", "confidence": "low",
             "why": "Device did not respond from observer point",
             "verify_read_only": "Read parent switch interface/PoE/UPS and uplink telemetry"}]
        incidents.append({
            "asset_id": ident, "ip": obs.get("ip") or asset.get("ip"),
            "name": asset.get("device_name") or obs.get("name") or "Equipo no identificado",
            "type": asset.get("device_type") or obs.get("device_type") or "tipo no identificado",
            "vendor": asset.get("vendor") or "no identificado",
            "model": asset.get("model") or "no identificado",
            "site": guardian.get("site_id") or asset.get("site_id"),
            "floor": upstream.get("floor") or "ubicación no identificada",
            "area": upstream.get("area") or "ubicación no identificada",
            "switch_port": upstream.get("switch_port") or "no identificado",
            "upstream": upstream.get("upstream_asset_id") or "no identificado",
            "power": upstream.get("power_source") or "no identificado",
            "vlan": upstream.get("vlan") or "no identificada",
            "sample_time": timestamp, "inventory_time": asset.get("updated_at"),
            "evidence": {"icmp": obs.get("icmp"), "tcp": obs.get("tcp")},
            "hypotheses": hypotheses,
            "next_action": "Read upstream device and type-specific heartbeat before repair"})
    groups = defaultdict(list)
    for incident in incidents:
        if incident["upstream"] != "no identificado":
            groups[incident["upstream"]].append(incident)
    common = {}
    for upstream, items in groups.items():
        if len(items) >= 2:
            common[upstream] = [item["asset_id"] for item in items]
            for item in items:
                item["hypotheses"].insert(0, {
                    "cause": "shared switch, uplink or power", "confidence": "medium",
                    "why": f"{len(items)} offline devices share documented upstream {upstream}",
                    "verify_read_only": "Read common switch ports, PoE and UPS logs"})
    old = {x["asset_id"] for x in (previous or {}).get("targets", [])
           if x.get("online") is False and x.get("asset_id")}
    new = {i["asset_id"] for i in incidents}
    return {"freshness": "CURRENT" if age is not None and -300 <= age <= 3600 else "STALE",
            "timestamp": timestamp, "source": guardian.get("source"),
            "incidents": incidents, "shared_upstreams": common,
            "new_offline_ids": sorted(new - old) if previous else [],
            "recovered_ids": sorted(old - new) if previous else [],
            "root_cause_verified": False, "mutations_performed": False}
