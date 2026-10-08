"""AG-60 / AG-32 Grandstream GWN network operations (observe → diagnose → governed action)."""

from __future__ import annotations

import re
from typing import Any

from inneros_core_runtime import device_fabric, grandstream_gwn_client as gwn


_GRANDSTREAM_INTENT_KEYWORDS = (
    "grandstream",
    "gwn",
    "gcc6010",
    "gcc",
    "gdms",
    "bellini",
    "torre bellini",
    "gwn7052",
    "gwn7660",
    "gwn7801",
)
_WIFI_KEYWORDS = ("wifi", "wi-fi", "wlan", "ssid", "señal", "senal", "2.4", "5ghz", "5 ghz")
_REPAIR_KEYWORDS = (
    "arregla", "arreglar", "corrige", "corregir", "optimiza", "optimizar",
    "repara", "reparar", "cambia", "cambiar",
)
_UNIFI_MARKERS = ("unifi", "ubiquiti", "u7", "udm", "udr")


def is_grandstream_gwn_request(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    if any(m in text for m in _UNIFI_MARKERS):
        return False
    if any(k in text for k in _GRANDSTREAM_INTENT_KEYWORDS):
        return True
    if any(k in text for k in _WIFI_KEYWORDS) and any(
        s in text for s in ("bellini", "grandstream", "gwn", "gcc")
    ):
        return True
    return False


def _requested_repair(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(k in text for k in _REPAIR_KEYWORDS)


def _infer_site(message: str, client_id: str, site_id: str) -> tuple[str, str]:
    c = (client_id or "").strip().lower()
    s = (site_id or "").strip().lower()
    if c or s:
        if not c and s in ("bellini-i-ii", "bellini_i_ii", "bellini"):
            c = "bellini"
        if not s and c == "bellini":
            s = "bellini-i-ii"
        if not s and c == "pcdoctor_lab":
            s = "home_pcdoctor_lab"
        return c or "bellini", s or "bellini-i-ii"
    text = (message or "").lower()
    if "casa" in text or "lab" in text or "pcdoctor" in text:
        return "pcdoctor_lab", "home_pcdoctor_lab"
    return "bellini", "bellini-i-ii"


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _device_online(row: dict[str, Any]) -> bool:
    raw = row.get("status") if "status" in row else row.get("online")
    if raw in (1, True, "1", "online", "connected"):
        return True
    if raw in (0, False, "0", "offline", "disconnected", "down"):
        return False
    return str(raw or "").lower() not in {"offline", "disconnected", "down", "0", "false"}


def _normalize_ap(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("name") or row.get("deviceName") or row.get("hostname"),
        "mac": row.get("mac") or row.get("deviceMac"),
        "model": row.get("apType") or row.get("model") or row.get("deviceModel"),
        "status": row.get("status") if row.get("status") is not None else row.get("onlineStatus"),
        "online": _device_online(row),
        "ip": row.get("ip") or row.get("deviceIp"),
        "clients": _safe_int(row.get("clientNum") or row.get("clients")),
        "uptime": row.get("uptime") or row.get("upTime"),
        "firmware": row.get("versionFirmware") or row.get("firmware") or row.get("version"),
        "channel_2g4": row.get("channel"),
        "channel_5g": row.get("channel5g"),
    }


def _normalize_ssid(row: dict[str, Any]) -> dict[str, Any]:
    band = row.get("band") or row.get("radio") or row.get("wifiBand")
    name = row.get("name") or row.get("ssidName") or row.get("ssid")
    return {
        "name": name,
        "id": row.get("id") or row.get("ssidId"),
        "enabled": row.get("wifiEnabled") if "wifiEnabled" in row else row.get("enable", row.get("enabled")),
        "band": band,
        "security": row.get("securityMode") or row.get("security") or row.get("encryption"),
        "vlan": row.get("vlan") or row.get("vlanId"),
        "online_devices": row.get("onlineDevices"),
    }


def _normalize_switch(row: dict[str, Any]) -> dict[str, Any]:
    base = _normalize_ap(row)
    base["ports"] = row.get("portNum") or row.get("ports")
    return base


def _normalize_client(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "mac": row.get("clientId") or row.get("mac") or row.get("clientMac"),
        "hostname": row.get("name") or row.get("hostname") or row.get("clientName"),
        "ip": row.get("ipv4") or row.get("ip") or row.get("clientIp"),
        "ssid": row.get("ssid") or row.get("ssidName"),
        "ap_mac": row.get("apId") or row.get("apMac") or row.get("associatedAp"),
        "band": row.get("channelClassStr") or row.get("band") or row.get("radio"),
        "rssi": row.get("rssi") or row.get("signal"),
        "online": row.get("online"),
        "assoc_time": row.get("assoctime"),
    }


def _mongo_tenant(client_id: str) -> dict[str, Any] | None:
    try:
        rows = device_fabric._get_mongo_tenants(client_id=client_id)  # noqa: SLF001
        return rows[0] if rows else None
    except Exception:
        return None


def _local_gateway_probe(site_id: str, gateway_ip: str) -> dict[str, Any] | None:
    if not gateway_ip:
        return None
    try:
        return device_fabric.device_fabric_probe(target=gateway_ip, site_id=site_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def grandstream_gwn_network_ops(
    message: str = "",
    *,
    client_id: str = "",
    site_id: str = "",
    network_id: int = 0,
    apply_changes: bool = False,
    owner_approval_ref: str = "",
) -> dict[str, Any]:
    client_id, site_id = _infer_site(message, client_id, site_id)
    requested_repair = _requested_repair(message)
    tenant = _mongo_tenant(client_id)
    mongo_inv = device_fabric.device_fabric_inventory(client_id=client_id, site_id=site_id, live=False)

    creds, cred_err = gwn.load_gwn_credentials()
    resolved_nid = gwn.resolve_network_id(
        client_id=client_id,
        site_id=site_id,
        network_id=network_id or None,
        tenant_row=tenant,
    )

    findings: list[dict[str, Any]] = []
    likely_causes: list[str] = []
    limitations: list[str] = []
    actions_requiring_approval: list[str] = []
    safe_actions_applied: list[dict[str, Any]] = []

    gateway_ip = (tenant or {}).get("gateway_ip") or ""
    if not gateway_ip and client_id == "bellini":
        gateway_ip = "192.168.3.1"
    local_probe = _local_gateway_probe(site_id, gateway_ip) if gateway_ip else None

    cloud_snapshot: dict[str, Any] | None = None
    network_pick: dict[str, Any] | None = None

    if not creds:
        limitations.append(
            "GWN Cloud API Developer Mode credentials are not configured (GWN_CLOUD_APP_ID / GWN_CLOUD_SECRET_KEY or owner_vault gwn_cloud)."
        )
        limitations.append(
            "Enable API Developer Mode at https://www.gwn.cloud → API Developer, then store APP ID and Secret Key in owner_vault or environment."
        )
    else:
        token, token_meta = gwn.get_access_token(creds)
        if not token:
            findings.append({"severity": "high", "code": "gwn_auth_failed", "detail": token_meta})
        else:
            if not resolved_nid:
                hint = (tenant or {}).get("site_name") or client_id
                resolved_nid, network_pick = gwn.pick_network_id_from_cloud(creds, hint=str(hint), access_token=token)
            if resolved_nid:
                cloud_snapshot = gwn.fetch_full_network_snapshot(
                    network_id=int(resolved_nid),
                    creds=creds,
                    access_token=token,
                    include_device_details=True,
                )
            else:
                findings.append(
                    {
                        "severity": "medium",
                        "code": "gwn_network_id_unresolved",
                        "detail": network_pick or {"error": cred_err},
                    }
                )

    aps: list[dict[str, Any]] = []
    ssids: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    routers: list[dict[str, Any]] = []
    clients: list[dict[str, Any]] = []

    if cloud_snapshot and cloud_snapshot.get("ok"):
        dev_block = cloud_snapshot.get("devices") or {}
        ap_rows = (dev_block.get("access_points") or {}).get("items") or []
        sw_rows = (dev_block.get("switches") or {}).get("items") or []
        rt_rows = (dev_block.get("routers") or {}).get("items") or []
        ssid_rows = (cloud_snapshot.get("ssids") or {}).get("items") or []
        client_rows = (cloud_snapshot.get("clients") or {}).get("items") or []
        aps = [_normalize_ap(r) for r in ap_rows if isinstance(r, dict)]
        switches = [_normalize_switch(r) for r in sw_rows if isinstance(r, dict)]
        routers = [_normalize_ap(r) for r in rt_rows if isinstance(r, dict)]
        ssids = [_normalize_ssid(r) for r in ssid_rows if isinstance(r, dict)]
        clients = [_normalize_client(r) for r in client_rows if isinstance(r, dict)]

    offline_aps = [ap for ap in aps if not ap.get("online")]
    online_aps = [ap for ap in aps if ap.get("online")]
    offline_switches = [sw for sw in switches if not _device_online(sw)]
    offline_routers = [rt for rt in routers if not rt.get("online")]

    clients_24 = sum(1 for c in clients if "2.4" in str(c.get("band") or "").lower())
    clients_5 = sum(1 for c in clients if "5" in str(c.get("band") or "").lower() or "5g" in str(c.get("band") or "").lower())
    if not clients and ssids:
        for ss in ssids:
            low = str(ss.get("name") or "").lower()
            if "2.4" in low or "2_4" in low:
                clients_24 += 1
            if "5" in low:
                clients_5 += 1

    if offline_aps:
        findings.append(
            {
                "severity": "high",
                "code": "ap_offline",
                "detail": [ap.get("name") or ap.get("mac") for ap in offline_aps],
            }
        )
        likely_causes.append("One or more GWN access points report offline in GWN Cloud.")
    if offline_switches:
        findings.append(
            {
                "severity": "high",
                "code": "switch_offline",
                "detail": [sw.get("name") or sw.get("mac") for sw in offline_switches],
            }
        )
        likely_causes.append("One or more GWN switches are offline in GWN Cloud (PoE/uplink/core risk).")
    if offline_routers:
        findings.append(
            {
                "severity": "critical",
                "code": "router_offline",
                "detail": [rt.get("name") or rt.get("mac") for rt in offline_routers],
            }
        )
    if clients_24 >= 25 and clients_5 < clients_24:
        findings.append(
            {
                "severity": "high",
                "code": "24ghz_client_pressure",
                "detail": {"clients_24_estimate": clients_24, "clients_5_estimate": clients_5},
            }
        )
        likely_causes.append("Many clients appear on 2.4 GHz; IoT and cameras may compete for airtime.")

    before = {
        "online_aps": [ap.get("name") or ap.get("mac") for ap in online_aps],
        "offline_aps": [ap.get("name") or ap.get("mac") for ap in offline_aps],
        "routers": [rt.get("name") or rt.get("mac") for rt in routers],
        "offline_switches": [sw.get("name") or sw.get("mac") for sw in offline_switches],
        "ssid_count": len(ssids),
        "switch_count": len(switches),
        "client_count": len(clients),
        "network_id": resolved_nid,
    }

    if not cloud_snapshot or not cloud_snapshot.get("ok"):
        limitations.append("Live GWN Cloud snapshot unavailable; Mongo/static inventory and local probe still returned.")
    else:
        limitations.extend(
            [
                "Channel/power/firmware/router reboot changes remain approval-gated; SSID updates require owner_approval_ref.",
                "Remote fix: grandstream_gwn_device_reboot / grandstream_gwn_ssid_update with owner_approval_ref.",
            ]
        )

    actions_requiring_approval.extend(
        [
            "Confirm SSID/band steering targets before ssid/update.",
            "Collect per-AP RF metrics from GWN Manager or device detail before changing channels or TX power.",
        ]
    )
    if offline_aps:
        actions_requiring_approval.append(
            "Verify physical PoE/uplink for offline APs before cloud-side reboot or reprovision."
        )

    if requested_repair:
        actions_requiring_approval.append(
            "To apply SSID/Wi-Fi changes: use grandstream_gwn_ssid_update with a full SSID payload, "
            "apply_changes=true, and owner_approval_ref after explicit owner approval."
        )
    if apply_changes and not owner_approval_ref.strip():
        findings.append(
            {
                "severity": "medium",
                "code": "mutation_blocked",
                "detail": "owner_approval_ref required for any GWN cloud write",
            }
        )

    summary_parts = [
        f"Grandstream/GWN site {client_id}/{site_id}",
        f"{len(routers)} router(s)",
        f"{len(online_aps)}/{len(aps)} AP(s) online",
        f"{len(switches)} switch(es) ({len(offline_switches)} offline)",
        f"{len(ssids)} SSID(s)",
        f"{len(clients)} client(s) online en cloud",
    ]

    return {
        "ok": True,
        "mode": "grandstream_gwn_network_ops",
        "client_id": client_id,
        "site_id": site_id,
        "requested_repair": requested_repair,
        "summary": "; ".join(summary_parts) + ".",
        "findings": findings,
        "likely_causes": likely_causes,
        "evidence": {
            "mongo_inventory": mongo_inv,
            "local_gateway_probe": local_probe,
            "cloud_snapshot": cloud_snapshot,
            "network_resolution": network_pick,
            "routers": routers,
            "access_points": aps,
            "ssids": ssids,
            "switches": switches,
            "clients": clients[:200],
            "client_total": len(clients),
        },
        "safe_actions_applied": safe_actions_applied,
        "actions_requiring_approval": actions_requiring_approval,
        "verification": {
            "performed": bool(cloud_snapshot and cloud_snapshot.get("ok")) or bool(mongo_inv.get("ok")),
            "source": "gwn_cloud_api" if cloud_snapshot and cloud_snapshot.get("ok") else "mongo_and_local_probe",
            "read_only": not bool(safe_actions_applied),
            "network_id": resolved_nid,
            "credentials_source": creds.source if creds else None,
        },
        "before_after": {"before": before, "after": before, "changed": bool(safe_actions_applied)},
        "limitations": limitations,
        "api_capabilities": gwn.gwn_api_capabilities(),
    }
