"""Universal Network Audit — read-only capabilities over Device Fabric + GWN Cloud.

ChatGPT invokes via capability_invoke; no per-site Cursor operator loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from inneros_core_runtime.capability_gateway import register_capability


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_manifest(
    capability_id: str,
    title: str,
    description: str,
    keywords: list[str],
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "version": "1.0.0",
        "title": title,
        "domain": "network",
        "risk_class": "low",
        "mode": "read_only",
        "description": description,
        "keywords": keywords,
        "parameters_schema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "e.g. bellini, econbay, iconbay"},
                "site_id": {"type": "string", "description": "e.g. bellini-i-ii"},
                "device_ref": {"type": "string", "description": "Optional IP/MAC/serial for device-scoped audit"},
                "live": {"type": "boolean", "description": "Prefer live provider reads when supported"},
            },
            "required": ["tenant_id", "site_id"],
        },
        "required_scopes": ["ralfia:read"],
    }


def _resolve_gwn(tenant_id: str, site_id: str) -> dict[str, Any]:
    from inneros_core_runtime import device_fabric
    from inneros_core_runtime import grandstream_gwn_client as gwn

    creds, err = gwn.load_gwn_credentials()
    tenant_rows = device_fabric._get_mongo_tenants(client_id=tenant_id)  # noqa: SLF001
    tenant_row = tenant_rows[0] if tenant_rows else None
    nid = gwn.resolve_network_id(client_id=tenant_id, site_id=site_id, tenant_row=tenant_row)
    return {
        "creds": creds,
        "credentials_error": err,
        "network_id": nid,
        "tenant_row": tenant_row,
    }


def _envelope(
    capability_id: str,
    *,
    tenant_id: str,
    site_id: str,
    provider_used: str,
    data: dict[str, Any],
    gaps: list[str] | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    return {
        "ok": True,
        "capability_id": capability_id,
        "tenant_id": tenant_id,
        "site_id": site_id,
        "mode": "read_only",
        "mutation_policy": "read_only",
        "provider_used": provider_used,
        "partial": partial or bool(gaps),
        "gaps": gaps or [],
        "data": data,
        "provenance": {
            "started_at": _now(),
            "source": "universal_network_audit",
            "stack": ["capability_gateway", "device_fabric", "grandstream_gwn"],
        },
    }


def network_device_ports_handler(parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from inneros_core_runtime import device_fabric
    from inneros_core_runtime import grandstream_gwn_client as gwn

    tenant_id = str(parameters.get("tenant_id") or "bellini").strip().lower()
    site_id = str(parameters.get("site_id") or "bellini-i-ii").strip().lower()
    device_ref = str(parameters.get("device_ref") or "").strip()
    gaps: list[str] = []
    ctx = _resolve_gwn(tenant_id, site_id)
    ports: list[dict[str, Any]] = []
    provider = "device_fabric"

    if device_ref:
        got = device_fabric.device_fabric_get(device_ref=device_ref)
        provider = str(got.get("device", {}).get("provider") or provider)
        ports.append(
            {
                "device_ref": device_ref,
                "source": "device_fabric_get",
                "device": got.get("device"),
                "port_detail": got.get("device", {}).get("ports") or got.get("ports"),
            }
        )

    if ctx["creds"] and ctx["network_id"]:
        provider = "grandstream_gwn_cloud_api"
        sw = gwn.list_switches(ctx["creds"], int(ctx["network_id"]))
        switches = (sw.get("data") or sw.get("items") or []) if sw.get("ok") else []
        if not switches:
            gaps.append("gwn_switch_list_empty_or_failed")
        batch = gwn.fetch_device_details_batch(
            ctx["creds"],
            int(ctx["network_id"]),
            switches if isinstance(switches, list) else [],
            limit=8,
        )
        for row in batch.get("devices") or []:
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            ports.append(
                {
                    "mac": row.get("mac"),
                    "name": row.get("name"),
                    "source": "gwn_device_info",
                    "ports": detail.get("ports") or detail.get("port") or detail.get("switchPorts"),
                    "poe": detail.get("poe") or detail.get("poeStatus"),
                    "speed_duplex": detail.get("speed") or detail.get("linkSpeed"),
                }
            )
    else:
        gaps.append("gwn_credentials_or_network_id_unavailable")

    if not ports:
        inv = device_fabric.device_fabric_inventory(client_id=tenant_id, site_id=site_id, live=False)
        for item in inv.get("inventory") or []:
            if not isinstance(item, dict):
                continue
            ports.append(
                {
                    "device_ref": item.get("ip") or item.get("ip_address"),
                    "source": "fabric_inventory_fallback",
                    "vendor": item.get("vendor"),
                    "model": item.get("model"),
                    "status": item.get("status"),
                    "provenance": item.get("provenance"),
                }
            )
        gaps.append("per_port_fields_require_gwn_device_info_or_switch_adapter")

    return _envelope(
        "network.device.ports.v1",
        tenant_id=tenant_id,
        site_id=site_id,
        provider_used=provider,
        data={"port_records": ports, "count": len(ports)},
        gaps=gaps,
        partial=True,
    )


def network_l2_topology_handler(parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from inneros_core_runtime import device_fabric
    from inneros_core_runtime import grandstream_gwn_client as gwn

    tenant_id = str(parameters.get("tenant_id") or "bellini").strip().lower()
    site_id = str(parameters.get("site_id") or "bellini-i-ii").strip().lower()
    live = bool(parameters.get("live"))
    gaps: list[str] = []
    ctx = _resolve_gwn(tenant_id, site_id)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    discover = device_fabric.device_fabric_discover(site_id=site_id, live=live)
    for item in discover.get("inventory") or []:
        if isinstance(item, dict):
            nodes.append(
                {
                    "id": item.get("ip") or item.get("mac"),
                    "kind": item.get("model") or "device",
                    "vendor": item.get("vendor"),
                    "source": "device_fabric_discover",
                }
            )

    if ctx["creds"] and ctx["network_id"]:
        nid = int(ctx["network_id"])
        for label, fn in (
            ("switch", gwn.list_switches),
            ("ap", gwn.list_access_points),
            ("router", gwn.list_routers),
        ):
            res = fn(ctx["creds"], nid)
            rows = (res.get("data") or res.get("items") or []) if res.get("ok") else []
            for row in rows if isinstance(rows, list) else []:
                mac = str(row.get("mac") or "")
                nodes.append({"id": mac or row.get("name"), "kind": label, "name": row.get("name"), "source": "gwn_cloud"})
                parent = row.get("parentMac") or row.get("uplinkMac")
                if parent:
                    edges.append({"from": mac, "to": str(parent), "source": "gwn_uplink_field"})
        clients = gwn.list_clients(ctx["creds"], nid)
        for row in (clients.get("data") or clients.get("items") or []) if clients.get("ok") else []:
            if isinstance(row, dict):
                nodes.append(
                    {
                        "id": row.get("mac") or row.get("ip"),
                        "kind": "client",
                        "ssid": row.get("ssid"),
                        "source": "gwn_clients",
                    }
                )
    else:
        gaps.append("gwn_topology_enrichment_unavailable")

    gaps.append("lldp_cdp_graph_requires_switch_port_adapter")

    return _envelope(
        "network.l2.topology.v1",
        tenant_id=tenant_id,
        site_id=site_id,
        provider_used="grandstream_gwn+device_fabric",
        data={"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)},
        gaps=gaps,
        partial=True,
    )


def network_segmentation_audit_handler(parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from inneros_core_runtime import device_fabric
    from inneros_core_runtime import grandstream_gwn_client as gwn

    tenant_id = str(parameters.get("tenant_id") or "bellini").strip().lower()
    site_id = str(parameters.get("site_id") or "bellini-i-ii").strip().lower()
    gaps: list[str] = []
    ctx = _resolve_gwn(tenant_id, site_id)
    site = device_fabric._site(site_id)  # noqa: SLF001
    authorized_cidr = (site or {}).get("authorized_cidr")
    ssids: list[dict[str, Any]] = []
    vlans: set[str] = set()

    if ctx["creds"] and ctx["network_id"]:
        ssid_res = gwn.list_ssids(ctx["creds"], int(ctx["network_id"]))
        rows = (ssid_res.get("data") or ssid_res.get("items") or []) if ssid_res.get("ok") else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            vlan = row.get("vlanId") or row.get("vlan") or row.get("vlan_id")
            ssids.append(
                {
                    "ssid": row.get("ssid") or row.get("name"),
                    "vlan": vlan,
                    "source": "gwn_ssid",
                }
            )
            if vlan is not None:
                vlans.add(str(vlan))
        wan = gwn.list_wan(ctx["creds"], int(ctx["network_id"]))
    else:
        wan = {"ok": False}
        gaps.append("gwn_ssid_vlan_map_unavailable")

    findings: list[dict[str, Any]] = []
    if len(vlans) <= 1:
        findings.append(
            {
                "severity": "info",
                "code": "single_vlan_or_unknown",
                "detail": "SSID/VLAN map shows one or zero VLANs; verify segmentation manually.",
            }
        )
    if authorized_cidr:
        findings.append(
            {
                "severity": "info",
                "code": "authorized_site_cidr",
                "detail": f"Site authorized CIDR: {authorized_cidr}",
            }
        )
    gaps.extend(["inter_vlan_acl_audit_not_wired", "pvid_native_vlan_requires_switch_port_adapter"])

    return _envelope(
        "network.segmentation.audit.v1",
        tenant_id=tenant_id,
        site_id=site_id,
        provider_used="grandstream_gwn+device_fabric",
        data={
            "authorized_cidr": authorized_cidr,
            "ssids": ssids,
            "vlan_ids": sorted(vlans),
            "wan": wan if isinstance(wan, dict) else {"ok": False},
            "findings": findings,
        },
        gaps=gaps,
        partial=True,
    )


def network_dhcp_arp_handler(parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from inneros_core_runtime import device_fabric
    from inneros_core_runtime import grandstream_gwn_client as gwn

    tenant_id = str(parameters.get("tenant_id") or "bellini").strip().lower()
    site_id = str(parameters.get("site_id") or "bellini-i-ii").strip().lower()
    live = bool(parameters.get("live", True))
    gaps: list[str] = []
    ctx = _resolve_gwn(tenant_id, site_id)
    clients: list[dict[str, Any]] = []
    arp_like: list[dict[str, Any]] = []

    if ctx["creds"] and ctx["network_id"]:
        res = gwn.list_clients(ctx["creds"], int(ctx["network_id"]))
        rows = (res.get("data") or res.get("items") or []) if res.get("ok") else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            clients.append(
                {
                    "ip": row.get("ip") or row.get("ipAddress"),
                    "mac": row.get("mac"),
                    "hostname": row.get("hostname") or row.get("name"),
                    "ssid": row.get("ssid"),
                    "vlan": row.get("vlanId") or row.get("vlan"),
                    "source": "gwn_client_list",
                }
            )
            arp_like.append(
                {
                    "ip": row.get("ip") or row.get("ipAddress"),
                    "mac": row.get("mac"),
                    "source": "gwn_client_list_as_arp_proxy",
                }
            )
    else:
        gaps.append("gwn_dhcp_client_table_unavailable")

    discover = device_fabric.device_fabric_discover(site_id=site_id, cidr="", live=live)
    for item in discover.get("inventory") or []:
        if isinstance(item, dict) and item.get("ip"):
            arp_like.append(
                {
                    "ip": item.get("ip"),
                    "mac": item.get("mac"),
                    "vendor": item.get("vendor"),
                    "source": "device_fabric_inventory",
                }
            )

    gaps.append("gcc_dhcp_lease_table_not_exposed_in_this_capability_yet")
    gaps.append("switch_fdb_mac_table_requires_port_adapter")

    return _envelope(
        "network.dhcp.arp.v1",
        tenant_id=tenant_id,
        site_id=site_id,
        provider_used="grandstream_gwn+device_fabric",
        data={
            "dhcp_clients": clients,
            "arp_entries": arp_like,
            "client_count": len(clients),
            "arp_count": len(arp_like),
        },
        gaps=gaps,
        partial=True,
    )


def register_universal_network_audit_capabilities() -> None:
    specs: list[tuple[dict[str, Any], Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]]] = [
        (
            _base_manifest(
                "network.device.ports.v1",
                "Network device port audit (read-only)",
                "Port-level access/trunk/PoE/speed where provider exposes it; honest gaps otherwise.",
                ["network", "audit", "ports", "switch", "poe", "trunk", "access", "pvid", "vlan", "sfp", "duplex"],
            ),
            network_device_ports_handler,
        ),
        (
            _base_manifest(
                "network.l2.topology.v1",
                "L2 topology map (read-only)",
                "Nodes/edges from Device Fabric inventory and GWN cloud uplinks/clients.",
                ["network", "audit", "topology", "lldp", "cdp", "uplink", "map", "l2"],
            ),
            network_l2_topology_handler,
        ),
        (
            _base_manifest(
                "network.segmentation.audit.v1",
                "VLAN / SSID segmentation audit (read-only)",
                "SSID→VLAN mapping and coarse flat-network signals; ACL audit flagged as gap.",
                ["network", "audit", "segmentation", "vlan", "ssid", "acl", "flat", "inter-vlan"],
            ),
            network_segmentation_audit_handler,
        ),
        (
            _base_manifest(
                "network.dhcp.arp.v1",
                "DHCP clients and ARP-like table (read-only)",
                "GWN client list plus fabric inventory; GCC DHCP/FDB adapters noted in gaps.",
                ["network", "audit", "dhcp", "arp", "leases", "mac", "fdb", "clients"],
            ),
            network_dhcp_arp_handler,
        ),
    ]
    for manifest, handler in specs:
        register_capability(manifest, handler)
