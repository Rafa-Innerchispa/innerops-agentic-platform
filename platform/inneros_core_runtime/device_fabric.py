"""Universal Physical Device Fabric.

Fresh standalone implementation for InnerOS physical-device discovery. The
fabric exposes one small MCP-facing contract while providers/adapters remain
plugin-like and truthful about readiness. Live operations are read-only.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

FABRIC_VERSION = "2026.09.28"
AGENT_ID = "AG-60"

SUPPORT_READY = "ready"
SUPPORT_PARTIAL = "partial"
SUPPORT_AUTH_REQUIRED = "auth_required"
SUPPORT_UNSUPPORTED = "unsupported"
SUPPORT_TRANSPORT_UNAVAILABLE = "transport_unavailable"
SUPPORT_NOT_VALIDATED = "not_validated"

MUTATION_POLICY = {
    "mode": "read_only",
    "allowed": [
        "tcp_connect",
        "http_get_safe_root",
        "rtsp_options",
        "home_assistant_registry_read",
        "unifi_inventory_read_when_authorized",
        "dmx_status_read",
    ],
    "forbidden": [
        "brute_force",
        "credential_printing",
        "dhcp_change",
        "vlan_change",
        "firewall_change",
        "firmware_update",
        "device_reboot",
        "camera_or_recorder_write",
        "pbx_write",
        "alarm_action",
        "dmx_raw_channel_write",
    ],
}


@dataclass(frozen=True)
class Provider:
    provider_id: str
    label: str
    support_state: str
    families: tuple[str, ...]
    protocols: tuple[str, ...]
    capabilities: tuple[str, ...]
    delegated_to: tuple[str, ...] = ()
    auth: str = "not_required_for_discovery"
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "support_state": self.support_state,
            "families": list(self.families),
            "protocols": list(self.protocols),
            "capabilities": list(self.capabilities),
            "delegated_to": list(self.delegated_to),
            "auth": self.auth,
            "notes": list(self.notes),
        }


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "generic_network",
        "Generic network discovery",
        SUPPORT_READY,
        ("unknown", "router", "switch", "pc", "iot"),
        ("tcp", "http", "https", "dns"),
        ("discover", "probe", "inventory", "health"),
    ),
    Provider(
        "generic_onvif",
        "Generic ONVIF",
        SUPPORT_PARTIAL,
        ("camera", "nvr", "dvr", "video_intercom"),
        ("onvif", "ws-discovery"),
        ("identify", "profiles", "stream_uri", "capabilities"),
        ("inneros-physical-guardian",),
        "required_for_authenticated_profile_details",
    ),
    Provider(
        "generic_rtsp",
        "Generic RTSP",
        SUPPORT_READY,
        ("camera", "nvr", "dvr", "video_stream"),
        ("rtsp",),
        ("probe", "inventory", "stream_presence"),
        ("inneros-physical-guardian",),
    ),
    Provider(
        "upnp_ssdp_mdns",
        "UPnP / SSDP / mDNS",
        SUPPORT_PARTIAL,
        ("iot", "printer", "speaker", "camera", "network"),
        ("ssdp", "mdns", "upnp"),
        ("discover", "correlate"),
        (),
        "not_required_for_discovery",
        ("Passive broadcast discovery is exposed as provider metadata; active UDP discovery is only used when authorized.",),
    ),
    Provider(
        "home_assistant_registry",
        "Home Assistant registry",
        SUPPORT_READY,
        ("iot", "camera", "alarm", "light", "voice_assistant", "network"),
        ("home_assistant_ws", "home_assistant_rest"),
        ("inventory", "dedupe", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
        "homeassistant_token_required",
    ),
    Provider(
        "hikvision",
        "Hikvision",
        SUPPORT_PARTIAL,
        ("camera", "ip_camera", "nvr", "dvr", "video_intercom", "access_control", "biometric_device", "network_device"),
        ("rtsp", "onvif", "isapi", "hikvision_sdk"),
        ("discover", "probe", "identity", "capabilities", "inventory"),
        ("inneros-physical-guardian",),
        "required_for_isapi_model_serial_firmware",
    ),
    Provider(
        "dahua",
        "Dahua",
        SUPPORT_PARTIAL,
        ("camera", "ip_camera", "nvr", "dvr", "xvr", "analog_channel"),
        ("rtsp", "onvif", "cgi", "eventManager", "dahua_private"),
        ("discover", "probe", "identity", "analog_child_channels", "inventory"),
        ("inneros-physical-guardian",),
        "required_for_authenticated_cgi_details",
    ),
    Provider(
        "tp_link_tapo",
        "TP-Link / Tapo",
        SUPPORT_PARTIAL,
        ("camera", "plug", "iot"),
        ("rtsp", "onvif", "home_assistant", "vendor_lan"),
        ("discover", "probe", "inventory"),
        ("Home Assistant", "inneros-physical-guardian"),
        "auth_required_for_cloud_or_account_only_models",
    ),
    Provider(
        "imou",
        "Imou",
        SUPPORT_AUTH_REQUIRED,
        ("camera", "nvr"),
        ("rtsp", "onvif", "official_api"),
        ("onboarding", "probe", "inventory"),
        ("inneros-physical-guardian", "VigiLOS"),
        "owner_account_or_local_onvif_required",
    ),
    Provider(
        "ezviz",
        "EZVIZ",
        SUPPORT_PARTIAL,
        ("camera", "doorbell", "alarm"),
        ("home_assistant", "rtsp", "vendor_api"),
        ("inventory", "probe", "health"),
        ("inneros-physical-guardian", "Home Assistant"),
        "auth_required_for_cloud_details",
    ),
    Provider(
        "zkteco",
        "ZKTeco ADMS/iClock",
        SUPPORT_PARTIAL,
        ("attendance", "access_control", "biometric_terminal"),
        ("adms", "iclock"),
        ("identity", "health", "capabilities"),
        ("innerspark-workforce-ai",),
        "managed_by_workforce_secret_store",
    ),
    Provider(
        "grandstream_ucm",
        "Grandstream UCM",
        SUPPORT_PARTIAL,
        ("pbx", "voice_gateway", "telephony"),
        ("sip", "ami", "cgi", "http"),
        ("probe", "identity", "health", "pbx_capabilities"),
        ("inneros-voiceops",),
        "required_for_authenticated_pbx_details",
    ),
    Provider(
        "grandstream_gwn",
        "Grandstream GWN/GCC",
        SUPPORT_PARTIAL,
        ("router", "switch", "access_point", "controller"),
        ("http", "https", "snmp_optional"),
        ("probe", "identity", "network_capabilities"),
        (),
        "required_for_authenticated_network_details",
        ("UCM support is intentionally separate from GWN/GCC management.",),
    ),
    Provider(
        "intelbras",
        "Intelbras",
        SUPPORT_PARTIAL,
        ("alarm", "camera", "nvr", "router"),
        ("home_assistant", "guardian", "tcp_probe"),
        ("inventory", "alarm_read_only", "health"),
        ("Home Assistant", "AG-32", "inneros-physical-guardian", "intelbras_guardian"),
        "guardian_or_homeassistant_token_required_for_state",
    ),
    Provider(
        "unifi",
        "UniFi / Ubiquiti",
        SUPPORT_PARTIAL,
        ("gateway", "switch", "access_point", "wlan", "client"),
        ("home_assistant", "unifi_controller"),
        ("inventory", "wifi_health", "client_correlation"),
        ("Home Assistant", "AG-32", "UniFi Controller"),
        "controller_or_homeassistant_token_required",
    ),
    Provider(
        "dmx",
        "DMX / Art-Net",
        SUPPORT_READY,
        ("lighting", "controller", "scene"),
        ("artnet", "local_dmx_engine"),
        ("status", "targets", "safe_scenes"),
        ("AG-59", "local_dmx_engine"),
        "not_required_for_status",
        ("Raw channel mutation remains hidden behind AG-59 allowlisted tools.",),
    ),
    Provider(
        "broadlink",
        "Broadlink",
        SUPPORT_PARTIAL,
        ("ir_remote", "rf_remote", "plug"),
        ("home_assistant", "broadlink_lan"),
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
        "homeassistant_token_required",
    ),
    Provider(
        "tuya",
        "Tuya",
        SUPPORT_PARTIAL,
        ("iot", "camera", "plug", "light", "sensor"),
        ("home_assistant", "tuya_cloud_or_local"),
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
        "tuya_or_homeassistant_credentials_required",
    ),
    Provider(
        "alexa_devices",
        "Alexa devices",
        SUPPORT_PARTIAL,
        ("voice_assistant", "speaker", "display", "iot_bridge"),
        ("home_assistant", "alexa_media", "voiceops"),
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "inneros-voiceops"),
        "integration_token_required",
    ),
)

PROVIDER_BY_ID = {provider.provider_id: provider for provider in PROVIDERS}

SITES: dict[str, dict[str, Any]] = {
    "bellini_i_ii": {
        "site_id": "bellini_i_ii",
        "tenant_id": "pcdoctor",
        "label": "Torres Bellini I-II",
        "scope": "Bellini I-II only",
        "transport": "tailscale_subnet",
        "transport_peer": "desktop-t2jle71",
        "peer_tailscale_ip": "100.103.151.40",
        "peer_lan_ip": "192.168.3.236",
        "authorized_cidr": "192.168.3.0/24",
        "gateway": "192.168.3.1",
        "exclude": ("Bellini III-IV",),
    },
    "home_pcdoctor_lab": {
        "site_id": "home_pcdoctor_lab",
        "tenant_id": "innerchispa",
        "label": "Casa / PC Doctor Lab",
        "scope": "Rafael local lab",
        "transport": "local_or_amd",
        "authorized_cidr": os.getenv("DEVICE_FABRIC_HOME_CIDR", "192.168.1.0/24"),
        "exclude": (),
    },
}

PROBE_PORTS = (22, 23, 53, 80, 81, 443, 554, 8000, 8080, 8081, 8088, 8089, 8443, 5060, 5061, 5357, 7547, 9009, 37777, 37778)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if re.search(r"(secret|token|password|passwd|credential|authorization|cookie|api[_-]?key|pin)", str(key), re.I):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and re.search(r"(Bearer\s+|Basic\s+|password=|token=|api[_-]?key=|sk-)", value, re.I):
        return "[REDACTED]"
    return value


def _hash_id(*parts: str) -> str:
    clean = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha1(clean.encode("utf-8")).hexdigest()[:12]


def _site(site_id: str) -> dict[str, Any]:
    return dict(SITES.get((site_id or "").strip().lower(), {}))


def _within_site(host: str, site_id: str) -> bool:
    site = _site(site_id)
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(site["authorized_cidr"], strict=False)
    except Exception:
        return False


def _protocol_for_port(port: int) -> str:
    return {
        22: "ssh",
        23: "telnet",
        53: "dns",
        80: "http",
        81: "http",
        443: "https",
        554: "rtsp",
        8000: "hikvision_sdk",
        8080: "http",
        8081: "http",
        8088: "asterisk_http",
        8089: "asterisk_https",
        8443: "https",
        5060: "sip",
        5061: "sips",
        5357: "ws_discovery",
        7547: "cwmp",
        9009: "intelbras_candidate",
        37777: "dahua_private",
        37778: "dahua_private",
    }.get(int(port), "tcp")


def _tcp_probe(host: str, port: int, timeout: float) -> dict[str, Any]:
    start = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        return {"port": int(port), "protocol": _protocol_for_port(port), "state": "open", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as exc:
        return {"port": int(port), "protocol": _protocol_for_port(port), "state": "closed_or_filtered", "error": type(exc).__name__}
    finally:
        sock.close()


def _http_probe(host: str, port: int, timeout: float = 0.9) -> dict[str, Any]:
    scheme = "https" if int(port) in {443, 8443} else "http"
    url = f"{scheme}://{host}:{int(port)}/"
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "InnerOS-DeviceFabric/2026.09 read-only"})
    context = ssl._create_unverified_context() if scheme == "https" else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            return {"ok": True, "url": url, "status": response.status, "headers": dict(response.headers.items()), "body_preview": body[:500]}
    except urllib.error.HTTPError as exc:
        return {"ok": True, "url": url, "status": exc.code, "headers": dict(exc.headers.items()) if exc.headers else {}, "body_preview": ""}
    except Exception as exc:
        return {"ok": False, "url": url, "error": type(exc).__name__, "detail": str(exc)[:160]}


def _rtsp_options(host: str, port: int = 554, timeout: float = 0.9) -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        sock.sendall((f"OPTIONS rtsp://{host}:{int(port)}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: InnerOS-DeviceFabric/2026.09 read-only\r\n\r\n").encode("ascii"))
        data = sock.recv(2048).decode("utf-8", errors="replace")
        return {"ok": bool(data), "port": int(port), "response_preview": data[:700]}
    except Exception as exc:
        return {"ok": False, "port": int(port), "error": type(exc).__name__, "detail": str(exc)[:160]}
    finally:
        sock.close()


def _fingerprint(host: str, open_ports: list[int], raw: dict[str, Any]) -> dict[str, Any]:
    observable_raw = {key: value for key, value in raw.items() if key != "tcp"}
    observable_raw["tcp_open"] = [row for row in raw.get("tcp", []) if row.get("state") == "open"]
    text = json.dumps(observable_raw, ensure_ascii=False).lower()
    providers: set[str] = {"generic_network"}
    manufacturer = ""
    model = ""
    device_type = "unknown"
    capabilities: set[str] = {"read_only_probe"}
    protocols = {_protocol_for_port(port) for port in open_ports}
    confidence = 0.25
    evidence: list[dict[str, Any]] = []

    def mark(provider: str, maker: str = "", dtype: str = "", conf: float = 0.6, detail: str = "") -> None:
        nonlocal manufacturer, device_type, confidence
        providers.add(provider)
        if maker:
            manufacturer = maker
        if dtype:
            device_type = dtype
        confidence = max(confidence, conf)
        if detail:
            evidence.append({"source": "fingerprint", "detail": detail, "confidence": conf})

    if 554 in open_ports:
        mark("generic_rtsp", dtype="video_stream", conf=0.52, detail="RTSP port 554 open")
        capabilities.add("video_stream_presence")
    if 8000 in open_ports:
        mark("hikvision", "Hikvision", "camera_or_recorder", 0.7, "Hikvision SDK port 8000 open")
        capabilities.update({"video", "vendor_probe"})
    if "realm=\\\"ds-" in text or "realm=\"ds-" in text or "ds-k1t" in text or "hikvision" in text:
        mark("hikvision", "Hikvision", "camera_or_video_intercom", 0.84, "Hikvision/DS intercom fingerprint observed")
        capabilities.update({"video_intercom_candidate", "rtsp"})
    if 37777 in open_ports or 37778 in open_ports or "dahua" in text:
        mark("dahua", "Dahua", "camera_or_dvr_nvr", 0.82, "Dahua private/control fingerprint observed")
        capabilities.update({"video", "recorder_or_camera", "analog_child_channels_possible"})
    if any(port in open_ports for port in (5060, 5061)) or {8088, 8089}.issubset(set(open_ports)) or "asterisk" in text or "ucm" in text:
        mark("grandstream_ucm", "Grandstream", "pbx_or_voice_gateway", 0.68, "SIP/Asterisk/UCM ports observed")
        capabilities.add("pbx_read_only_candidate")
    if "grandstream" in text or "gwn" in text or "gcc" in text:
        mark("grandstream_gwn", "Grandstream", "router_switch_ap_or_controller", 0.72, "Grandstream network fingerprint observed")
    if "tapo" in text or "tp-link" in text or "tplink" in text:
        mark("tp_link_tapo", "TP-Link/Tapo", "camera_or_iot", 0.72, "TP-Link/Tapo fingerprint observed")
    if "imou" in text:
        mark("imou", "Imou", "camera", 0.7, "Imou fingerprint observed")
    if "ezviz" in text:
        mark("ezviz", "EZVIZ", "camera_or_alarm", 0.72, "EZVIZ fingerprint observed")
    if "onvif" in text or 5357 in open_ports:
        providers.add("generic_onvif")
        capabilities.add("onvif_or_ws_discovery_candidate")
    if "microsoft-httpapi" in text:
        mark("generic_network", "Microsoft", "windows_pc_or_service_host", 0.58, "Microsoft HTTPAPI observed")
    if host == SITES["bellini_i_ii"]["gateway"]:
        mark("grandstream_gwn", "Grandstream", "router_gateway", 0.76, "Bellini documented gateway")
    if host == SITES["bellini_i_ii"]["peer_lan_ip"]:
        mark("generic_network", "Microsoft", "windows_peer", 0.86, "Bellini peer LAN address")

    providers.discard("generic_network") if len(providers) > 1 and "generic_network" in providers and device_type != "unknown" else None
    return {
        "manufacturer": manufacturer or "unknown",
        "model": model,
        "device_type": device_type,
        "provider_ids": sorted(providers),
        "protocols": sorted(protocols),
        "capabilities": sorted(capabilities),
        "confidence": round(confidence, 3),
        "evidence": evidence,
    }


def _record_from_probe(host: str, site_id: str, tcp: list[dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    site = _site(site_id)
    open_ports = [int(row["port"]) for row in tcp if row.get("state") == "open"]
    fp = _fingerprint(host, open_ports, raw)
    providers = fp["provider_ids"]
    name = f"{site_id}-{host}"
    return canonical_device_record(
        site_id=site_id,
        tenant_id=site.get("tenant_id", ""),
        name=name,
        ip=host,
        mac="",
        hostname="",
        manufacturer=fp["manufacturer"],
        model=fp["model"],
        firmware="",
        serial="",
        device_type=fp["device_type"],
        protocols=fp["protocols"],
        provider_ids=providers,
        capabilities=fp["capabilities"],
        credential_ref_present=False,
        transport=site.get("transport", "network"),
        evidence=fp["evidence"] + [{"source": "tcp_probe", "detail": f"{len(open_ports)} open ports observed", "open_ports": open_ports, "confidence": 0.55}],
        confidence=fp["confidence"],
        health={"reachable": bool(open_ports), "open_ports": open_ports},
        control_route={"read": providers[0] if providers else "generic_network", "write": "disabled_read_only_task"},
        raw_probe=raw,
    )


def canonical_device_record(
    *,
    site_id: str,
    tenant_id: str,
    name: str = "",
    ip: str = "",
    host: str = "",
    mac: str = "",
    hostname: str = "",
    manufacturer: str = "",
    model: str = "",
    firmware: str = "",
    serial: str = "",
    device_type: str = "unknown",
    protocols: list[str] | tuple[str, ...] = (),
    provider_ids: list[str] | tuple[str, ...] = (),
    capabilities: list[str] | tuple[str, ...] = (),
    credential_ref_present: bool = False,
    transport: str = "",
    evidence: list[dict[str, Any]] | None = None,
    confidence: float = 0.0,
    health: dict[str, Any] | None = None,
    control_route: dict[str, Any] | None = None,
    raw_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_list = sorted(set(str(p) for p in provider_ids if p))
    normalized_mac = str(mac or "").strip().lower()
    stable = normalized_mac or ip or host or hostname or name or json.dumps(provider_list)
    device_id = f"{site_id}:{provider_list[0] if provider_list else 'unknown'}:{_hash_id(site_id, stable)}"
    return _redact(
        {
            "device_id": device_id,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "name": name or hostname or ip or host or device_id,
            "ip": ip,
            "host": host or ip,
            "mac": normalized_mac,
            "hostname": hostname,
            "manufacturer": manufacturer or "unknown",
            "model": model or "",
            "firmware": firmware or "",
            "serial": serial or "",
            "device_type": device_type or "unknown",
            "protocols": sorted(set(protocols)),
            "provider_ids": provider_list or ["generic_network"],
            "capabilities": sorted(set(capabilities)),
            "credential_ref_present": bool(credential_ref_present),
            "transport": transport,
            "evidence": evidence or [],
            "provenance": evidence or [],
            "confidence": round(float(confidence or 0.0), 3),
            "last_seen": _now(),
            "health": health or {"reachable": None},
            "control_route": control_route or {"read": provider_list[0] if provider_list else "generic_network", "write": "disabled_read_only_task"},
            "mutation_policy": MUTATION_POLICY,
            "raw_probe": raw_probe or {},
        }
    )


def _probe_host(host: str, site_id: str, timeout: float) -> dict[str, Any]:
    tcp = [_tcp_probe(host, port, timeout) for port in PROBE_PORTS]
    open_ports = [row["port"] for row in tcp if row.get("state") == "open"]
    raw: dict[str, Any] = {"tcp": tcp}
    for port in [p for p in open_ports if p in {80, 81, 443, 8080, 8081, 8088, 8089, 8443}][:4]:
        raw[f"http_{port}"] = _http_probe(host, int(port))
    if 554 in open_ports:
        raw["rtsp_554"] = _rtsp_options(host)
    return _record_from_probe(host, site_id, tcp, raw)


def _scan_site_subnet(site_id: str, limit_hosts: int, timeout: float) -> list[dict[str, Any]]:
    site = _site(site_id)
    network = ipaddress.ip_network(site["authorized_cidr"], strict=False)
    hosts = [str(ip) for ip in network.hosts()][: max(1, min(int(limit_hosts), network.num_addresses))]
    out: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=96) as executor:
        futures = [executor.submit(_probe_host, host, site_id, timeout) for host in hosts]
        for future in concurrent.futures.as_completed(futures):
            try:
                record = future.result()
            except Exception:
                continue
            if (record.get("health") or {}).get("open_ports"):
                out.append(record)
    return sorted(out, key=lambda row: tuple(int(part) for part in str(row.get("ip", "0.0.0.0")).split(".") if part.isdigit()))


def _ha_provider_ids(device: dict[str, Any], device_entities: list[dict[str, Any]]) -> list[str]:
    text = json.dumps([device, device_entities], ensure_ascii=False).lower()
    pairs = [
        ("ubiquiti", "unifi"), ("unifi", "unifi"), ("intelbras", "intelbras"), ("interbras", "intelbras"),
        ("broadlink", "broadlink"), ("tuya", "tuya"), ("amazon", "alexa_devices"), ("alexa", "alexa_devices"),
        ("ezviz", "ezviz"), ("tapo", "tp_link_tapo"), ("tp-link", "tp_link_tapo"), ("tplink", "tp_link_tapo"),
        ("imou", "imou"), ("dahua", "dahua"), ("hikvision", "hikvision"), ("ucm", "grandstream_ucm"),
        ("grandstream", "grandstream_gwn"), ("dmx", "dmx"),
    ]
    found = [provider for needle, provider in pairs if needle in text]
    found.append("home_assistant_registry")
    return sorted(set(found))


def _type_from_ha(provider_ids: list[str], device: dict[str, Any]) -> str:
    model = str(device.get("model") or "").lower()
    if "intelbras" in provider_ids:
        return "alarm_or_security_device"
    if "broadlink" in provider_ids:
        return "ir_rf_bridge"
    if "tuya" in provider_ids:
        return "tuya_iot"
    if "alexa_devices" in provider_ids:
        return "voice_assistant"
    if "grandstream_ucm" in provider_ids:
        return "pbx_or_voice_gateway"
    if "unifi" in provider_ids:
        if "wlan" in model:
            return "wlan"
        if "gateway" in model or "udr" in model:
            return "gateway"
        return "network_device"
    if any(p in provider_ids for p in ("hikvision", "dahua", "ezviz", "imou", "tp_link_tapo")):
        return "camera_or_iot"
    return "iot_or_unknown"


def _home_assistant_inventory() -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    delegated: dict[str, Any] = {}
    try:
        from raphiia_openai import homeassistant_client as ha
    except Exception as exc:
        return [], {}, [{"provider_id": "home_assistant_registry", "support_state": SUPPORT_TRANSPORT_UNAVAILABLE, "error": str(exc)[:160]}]

    raw_devices = ha.list_devices(limit=2000)
    raw_entities = ha.list_entity_registry(limit=2000)
    devices = raw_devices.get("devices") or [] if raw_devices.get("ok") else []
    entities = raw_entities.get("entities") or [] if raw_entities.get("ok") else []
    if not raw_devices.get("ok"):
        blockers.append({"provider_id": "home_assistant_registry", "error": raw_devices.get("error"), "support_state": SUPPORT_AUTH_REQUIRED})
    if not raw_entities.get("ok"):
        blockers.append({"provider_id": "home_assistant_registry", "error": raw_entities.get("error"), "support_state": SUPPORT_AUTH_REQUIRED})

    entities_by_device: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        if entity.get("device_id"):
            entities_by_device.setdefault(str(entity["device_id"]), []).append(entity)

    inventory: list[dict[str, Any]] = []
    for device in devices:
        dev_entities = entities_by_device.get(str(device.get("id")), [])
        provider_ids = _ha_provider_ids(device, dev_entities)
        mac = ""
        for item in device.get("connections") or []:
            if isinstance(item, list) and item and item[0] == "mac":
                mac = str(item[1])
                break
        inventory.append(
            canonical_device_record(
                tenant_id=SITES["home_pcdoctor_lab"]["tenant_id"],
                site_id="home_pcdoctor_lab",
                name=device.get("name_by_user") or device.get("name") or "",
                mac=mac,
                manufacturer=device.get("manufacturer") or "",
                model=device.get("model") or "",
                firmware=device.get("sw_version") or "",
                device_type=_type_from_ha(provider_ids, device),
                protocols=["home_assistant"],
                provider_ids=provider_ids,
                capabilities=["home_assistant_inventory", "read_only_identity"],
                credential_ref_present=False,
                transport="home_assistant_registry",
                confidence=0.76,
                health={"reachable": None, "source": "home_assistant_registry"},
                evidence=[{"source": "home_assistant_registry", "detail": "Device observed in HA device registry", "device_id": device.get("id"), "entity_count": len(dev_entities), "confidence": 0.76}],
                control_route={"read": "home_assistant_registry", "write": "disabled_read_only_task"},
            )
        )

    try:
        delegated["unifi"] = _redact(ha.unifi_network_ops("status read-only"))
    except Exception as exc:
        blockers.append({"provider_id": "unifi", "error": str(exc)[:160], "support_state": SUPPORT_AUTH_REQUIRED})
    try:
        delegated["intelbras"] = _redact(ha.alarm_intelbras_ops("status read-only"))
    except Exception as exc:
        blockers.append({"provider_id": "intelbras", "error": str(exc)[:160], "support_state": SUPPORT_AUTH_REQUIRED})
    try:
        from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59
        delegated["dmx"] = _redact(ag59.dmx_status())
    except Exception as exc:
        blockers.append({"provider_id": "dmx", "error": str(exc)[:160], "support_state": SUPPORT_TRANSPORT_UNAVAILABLE})

    return dedupe_devices(inventory), delegated, blockers


def dedupe_devices(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        key = record.get("mac") or record.get("ip") or record.get("host") or record.get("device_id")
        key = f"{record.get('site_id')}:{str(key).lower()}"
        if key not in merged:
            merged[key] = dict(record)
            continue
        existing = merged[key]
        existing["provider_ids"] = sorted(set(existing.get("provider_ids", [])) | set(record.get("provider_ids", [])))
        existing["protocols"] = sorted(set(existing.get("protocols", [])) | set(record.get("protocols", [])))
        existing["capabilities"] = sorted(set(existing.get("capabilities", [])) | set(record.get("capabilities", [])))
        existing["evidence"] = list(existing.get("evidence", [])) + list(record.get("evidence", []))
        existing["provenance"] = existing["evidence"]
        existing["confidence"] = max(float(existing.get("confidence") or 0), float(record.get("confidence") or 0))
    return list(merged.values())


def provider_blockers_for_inventory(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    present = {pid for record in records for pid in record.get("provider_ids", [])}
    blockers = []
    for pid in ("tp_link_tapo", "imou", "zkteco"):
        if pid not in present:
            blockers.append({"provider_id": pid, "support_state": PROVIDER_BY_ID[pid].support_state, "reason": "not_observable_in_current_read_only_sources_or_auth_required"})
    return blockers


def device_fabric_providers() -> dict[str, Any]:
    return {"ok": True, "fabric_version": FABRIC_VERSION, "agent_id": AGENT_ID, "provider_count": len(PROVIDERS), "providers": [p.as_dict() for p in PROVIDERS], "mutation_policy": MUTATION_POLICY}


def device_fabric_discover(site_id: str = "bellini_i_ii", cidr: str = "", limit_hosts: int = 254, live: bool = True, timeout_seconds: float = 0.35) -> dict[str, Any]:
    site_id = (site_id or "bellini_i_ii").strip().lower()
    site = _site(site_id)
    if not site:
        return {"ok": False, "error": "unknown_site", "available_sites": sorted(SITES)}
    if cidr and cidr != site.get("authorized_cidr"):
        return {"ok": False, "error": "cidr_not_authorized_for_site", "requested_cidr": cidr, "authorized_cidr": site.get("authorized_cidr"), "mutation_policy": MUTATION_POLICY}
    if site_id == "home_pcdoctor_lab":
        inventory, delegated, blockers = _home_assistant_inventory()
        blockers.extend(provider_blockers_for_inventory(inventory))
        return {"ok": True, "site": site, "site_id": site_id, "count": len(inventory), "inventory": inventory, "delegated": delegated, "blockers": blockers, "mutation_policy": MUTATION_POLICY, "mutations_attempted": [], "generated_at": _now()}
    inventory = _scan_site_subnet(site_id, limit_hosts=limit_hosts, timeout=float(timeout_seconds)) if live else []
    blockers = provider_blockers_for_inventory(inventory)
    return {"ok": True, "site": site, "site_id": site_id, "count": len(inventory), "inventory": inventory, "blockers": blockers, "transport": {"peer": site.get("transport_peer"), "peer_tailscale_ip": site.get("peer_tailscale_ip"), "authorized_cidr": site.get("authorized_cidr")}, "mutation_policy": MUTATION_POLICY, "mutations_attempted": [], "generated_at": _now()}


def device_fabric_probe(target: str, provider_id: str = "", site_id: str = "bellini_i_ii") -> dict[str, Any]:
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "target_required"}
    if provider_id and provider_id not in PROVIDER_BY_ID:
        return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
    try:
        ipaddress.ip_address(target)
    except ValueError:
        return {"ok": False, "error": "ip_target_required_for_read_only_probe"}
    if site_id in SITES and not _within_site(target, site_id):
        return {"ok": False, "error": "target_outside_authorized_site_cidr", "target": target, "site_id": site_id}
    return {"ok": True, "target": target, "provider_id_requested": provider_id or None, "probe": _probe_host(target, site_id, 0.45), "mutation_policy": MUTATION_POLICY, "mutations_attempted": [], "generated_at": _now()}


def device_fabric_bind(device_ref: str, provider_id: str, credential_ref: str = "", site_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    if provider_id not in PROVIDER_BY_ID:
        return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
    if not dry_run:
        return {"ok": False, "error": "live_bind_disabled_in_read_only_task", "mutation_policy": MUTATION_POLICY, "mutations_attempted": []}
    return {"ok": True, "dry_run": True, "device_ref": device_ref, "provider": PROVIDER_BY_ID[provider_id].as_dict(), "site_id": site_id or None, "credential_ref_present": bool(credential_ref), "would_register": {"device_ref": device_ref, "provider_id": provider_id, "credential_ref": "[REDACTED]" if credential_ref else "", "site_id": site_id}, "mutation_policy": MUTATION_POLICY, "mutations_attempted": []}


def device_fabric_inventory(site_id: str = "", live: bool = False) -> dict[str, Any]:
    if site_id:
        return device_fabric_discover(site_id=site_id, live=live)
    bellini = device_fabric_discover("bellini_i_ii", live=live)
    home = device_fabric_discover("home_pcdoctor_lab", live=True)
    return {"ok": bool(bellini.get("ok")) and bool(home.get("ok")), "sites": {"bellini_i_ii": bellini, "home_pcdoctor_lab": home}, "mutation_policy": MUTATION_POLICY, "mutations_attempted": [], "generated_at": _now()}


def device_fabric_capabilities(device_ref: str = "", provider_id: str = "") -> dict[str, Any]:
    if provider_id:
        provider = PROVIDER_BY_ID.get(provider_id)
        if not provider:
            return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
        providers = [provider.as_dict()]
    else:
        providers = [p.as_dict() for p in PROVIDERS]
    return {"ok": True, "device_ref": device_ref or None, "providers": providers, "schema_fields": list(canonical_device_record(site_id="x", tenant_id="x", name="x").keys()), "mutation_policy": MUTATION_POLICY}


def device_fabric_health(site_id: str = "") -> dict[str, Any]:
    provider_rows = [p.as_dict() | {"healthy_for_read_only": p.support_state in {SUPPORT_READY, SUPPORT_PARTIAL, SUPPORT_AUTH_REQUIRED}} for p in PROVIDERS]
    blockers = [row for row in provider_rows if row["support_state"] in {SUPPORT_AUTH_REQUIRED, SUPPORT_TRANSPORT_UNAVAILABLE, SUPPORT_NOT_VALIDATED}]
    return {"ok": True, "fabric_version": FABRIC_VERSION, "agent_id": AGENT_ID, "site_filter": site_id or None, "provider_count": len(provider_rows), "providers": provider_rows, "blockers": blockers, "mutation_policy": MUTATION_POLICY, "mutations_attempted": [], "generated_at": _now()}


def device_fabric_get(device_ref: str) -> dict[str, Any]:
    ref = (device_ref or "").strip()
    if not ref:
        return {"ok": True, "fabric_version": FABRIC_VERSION, "agent_id": AGENT_ID, "sites": SITES, "providers": [p.as_dict() for p in PROVIDERS], "mutation_policy": MUTATION_POLICY}
    if ref in PROVIDER_BY_ID:
        return {"ok": True, "kind": "provider", "provider": PROVIDER_BY_ID[ref].as_dict()}
    if ref in SITES:
        return {"ok": True, "kind": "site", "site": SITES[ref]}
    return {"ok": False, "error": "unknown_reference", "device_ref": ref}


def run_device_fabric_agent(message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    text = (message or "").lower()
    if "bellini" in text:
        return {"agent_id": AGENT_ID, "action": "bellini_discover", **device_fabric_discover("bellini_i_ii", live=not dry_run)}
    if any(term in text for term in ("home", "casa", "pc doctor", "lab")):
        return {"agent_id": AGENT_ID, "action": "home_inventory", **device_fabric_discover("home_pcdoctor_lab", live=True)}
    if any(term in text for term in ("provider", "proveedor", "matrix", "matriz")):
        return {"agent_id": AGENT_ID, "action": "providers", **device_fabric_providers()}
    return {"agent_id": AGENT_ID, "action": "health", **device_fabric_health()}
