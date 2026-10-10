"""Universal Physical Device Fabric.

Fresh standalone implementation for InnerOS physical-device discovery. The
fabric exposes one small MCP-facing contract while providers/adapters remain
plugin-like and truthful about readiness. Live operations are read-only.
Multi-tenant hierarchy: provider (grandstream_gwn, etc.) -> account -> client -> site -> device.
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

FABRIC_VERSION = "2026.09.29"
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
        "gwn_cloud_inventory_read_when_authorized",
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
        ("discover", "model_extraction", "service_probe"),
    ),
    Provider(
        "home_assistant",
        "Home Assistant",
        SUPPORT_READY,
        ("switch", "light", "sensor", "camera", "lock", "cover", "climate", "media_player"),
        ("home_assistant_rest", "websocket"),
        ("inventory", "capabilities", "state_watch", "delegation"),
        ("Home Assistant", "AG-32"),
        "homeassistant_token_required",
    ),
    Provider(
        "grandstream_gcc",
        "Grandstream local GCC / UCM / GWN (on-prem)",
        SUPPORT_PARTIAL,
        ("router", "ap", "ip_pbx", "switch", "gateway", "video_intercom"),
        ("http", "https", "sip", "ssh"),
        ("inventory", "telemetry", "zeroconfig", "ports", "probe_fingerprint"),
        ("AG-60", "AG-55", "bellini_network_guardian"),
        "not_required_for_read_only",
        notes=(
            "probe+TCP fingerprint: ready (Bellini GCC6010)",
            "ucm_pbx_read_only: partial",
            "gwn_ap_switch_full_adapter: not_wired",
            "mutations: read_only",
        ),
    ),
    Provider(
        "grandstream_gwn",
        "Grandstream GWN Cloud & Multi-Tenant",
        SUPPORT_READY,
        ("router", "ap", "switch", "gateway"),
        ("gwn_cloud_api", "https"),
        ("multi_tenant_inventory", "site_management", "client_segmentation", "health"),
        ("AG-60",),
        "provider_account_ref_configured",
        notes=(
            "gwn_cloud_api_client: inneros_core_runtime.grandstream_gwn_client",
            "live_inventory_when_credentials_configured: yes",
            "live_mutations: approval_gated_via_grandstream_gwn_ssid_update",
        ),
    ),
    Provider(
        "ruijie_reyee",
        "Ruijie / Reyee (Ruijie Cloud)",
        SUPPORT_PARTIAL,
        ("router", "ap", "switch", "gateway", "antenna"),
        ("ruijie_cloud_api", "https"),
        (
            "multi_site_inventory",
            "ap_switch_gateway_list",
            "online_clients",
            "switch_ports",
            "gateway_ports",
            "local_probe",
        ),
        ("AG-60",),
        "ruijie_cloud_appid_secret_and_account_required",
        notes=(
            "client: inneros_core_runtime.ruijie_reyee_client",
            "reyee_devices_use_ruijie_cloud",
            "bellini_local_example: 192.168.3.172 Easy-Smart Switch",
        ),
    ),
    Provider(
        "unifi",
        "Ubiquiti UniFi",
        SUPPORT_PARTIAL,
        ("gateway", "switch", "ap", "protect_camera"),
        ("unifi_api", "https"),
        ("inventory", "port_status", "poe_status"),
        ("Home Assistant", "unifi_integration"),
        "unifi_credentials_required",
    ),
    Provider(
        "hikvision",
        "Hikvision",
        SUPPORT_READY,
        ("camera", "nvr", "video_intercom", "switch"),
        ("http", "isapi", "onvif", "rtsp", "sip"),
        ("inventory", "door_station_status", "stream_probe"),
        ("AG-60", "inneros-physical-guardian"),
    ),
    Provider(
        "dahua",
        "Dahua",
        SUPPORT_READY,
        ("camera", "nvr", "intercom"),
        ("http", "dahua_rpc", "onvif", "rtsp"),
        ("inventory", "stream_probe", "channels"),
        ("AG-60", "inneros-physical-guardian"),
    ),
    Provider(
        "intelbras",
        "Intelbras",
        SUPPORT_PARTIAL,
        ("alarm_panel", "camera", "dvr", "sensor"),
        ("intelbras_cloud", "onvif", "home_assistant"),
        ("inventory", "zone_status", "health"),
        ("Home Assistant", "intelbras_integration"),
    ),
    Provider(
        "ezviz",
        "EZVIZ (EZVIZ / EZOpen cloud)",
        SUPPORT_PARTIAL,
        ("camera", "doorbell", "nvr"),
        ("ezviz_cloud", "rtsp", "home_assistant"),
        ("inventory", "stream_presence"),
        ("inneros-physical-guardian", "Home Assistant"),
        notes=("Adapter code: physical_guardian/ingestion/ezviz.py", "two_way_audio: not_implemented"),
    ),
    Provider(
        "imou",
        "Imou (Dahua consumer cloud)",
        SUPPORT_NOT_VALIDATED,
        ("camera", "doorbell", "nvr"),
        ("imou_cloud", "onvif", "rtsp"),
        ("inventory", "stream_probe"),
        ("inneros-physical-guardian",),
        auth="imou_app_credentials_required",
        notes=("plugin_not_wired", "two_way_audio: planned"),
    ),
    Provider(
        "tp_link",
        "TP-Link Tapo / VIGI",
        SUPPORT_NOT_VALIDATED,
        ("camera", "doorbell", "nvr"),
        ("tapo_cloud", "onvif", "rtsp"),
        ("inventory", "stream_probe"),
        ("inneros-physical-guardian",),
        auth="tapo_credentials_required",
        notes=("plugin_not_wired", "two_way_audio: planned"),
    ),
    Provider(
        "zkteco",
        "ZKTeco (access control / time & attendance)",
        SUPPORT_NOT_VALIDATED,
        ("access_control", "door_controller", "turnstile", "biometric_reader", "time_attendance"),
        ("zkteco_standalone", "zkteco_push", "http", "tcp_4370"),
        ("inventory", "probe_fingerprint", "health"),
        ("inneros-physical-guardian", "Home Assistant"),
        auth="device_or_zkbio_credentials_required",
        notes=("adapter_not_wired", "commercial_quotes_via_Vero", "integrate_via_onvif_when_available"),
    ),
    Provider(
        "axis",
        "Axis Communications",
        SUPPORT_NOT_VALIDATED,
        ("camera", "intercom", "access_control"),
        ("onvif", "vapix", "rtsp"),
        ("inventory", "stream_probe"),
        ("generic_onvif", "inneros-physical-guardian"),
    ),
    Provider(
        "hanwha_wisenet",
        "Hanwha Wisenet",
        SUPPORT_NOT_VALIDATED,
        ("camera", "nvr", "video_intercom"),
        ("onvif", "sunapi", "rtsp"),
        ("inventory", "stream_probe"),
        ("generic_onvif", "inneros-physical-guardian"),
    ),
    Provider(
        "uniview",
        "Uniview (UNV)",
        SUPPORT_NOT_VALIDATED,
        ("camera", "nvr"),
        ("onvif", "rtsp", "http"),
        ("inventory", "stream_probe"),
        ("generic_onvif", "inneros-physical-guardian"),
    ),
    Provider(
        "bosch_security",
        "Bosch Security / Video",
        SUPPORT_NOT_VALIDATED,
        ("camera", "nvr", "intrusion"),
        ("onvif", "bvms", "rtsp"),
        ("inventory", "stream_probe"),
        ("generic_onvif",),
    ),
    Provider(
        "avigilon",
        "Avigilon (Motorola)",
        SUPPORT_NOT_VALIDATED,
        ("camera", "nvr"),
        ("onvif", "rtsp", "acc_api"),
        ("inventory", "stream_probe"),
        ("generic_onvif",),
    ),
    Provider(
        "honeywell_security",
        "Honeywell (Pro-Watch / MAXPRO / Galaxy)",
        SUPPORT_NOT_VALIDATED,
        ("access_control", "intrusion", "camera"),
        ("vendor_api", "onvif", "home_assistant"),
        ("inventory", "health"),
        ("Home Assistant",),
    ),
    Provider(
        "lenel_onguard",
        "LenelS2 OnGuard",
        SUPPORT_NOT_VALIDATED,
        ("access_control", "reader", "controller"),
        ("lenel_openaccess", "vendor_api"),
        ("inventory", "health"),
        notes=("enterprise_integration", "plugin_not_wired"),
    ),
    Provider(
        "salto",
        "Salto KS / Space",
        SUPPORT_NOT_VALIDATED,
        ("access_control", "lock", "reader"),
        ("salto_cloud", "vendor_api"),
        ("inventory", "health"),
        notes=("plugin_not_wired",),
    ),
    Provider(
        "assa_abloy",
        "ASSA ABLOY / Aperio / HID ecosystem bridges",
        SUPPORT_NOT_VALIDATED,
        ("access_control", "lock", "reader"),
        ("vendor_api", "home_assistant"),
        ("inventory", "health"),
        ("Home Assistant",),
    ),
    Provider(
        "suprema",
        "Suprema BioStar",
        SUPPORT_NOT_VALIDATED,
        ("biometric_reader", "access_control"),
        ("suprema_api", "http"),
        ("inventory", "health"),
    ),
    Provider(
        "hid_global",
        "HID Global / Amico readers",
        SUPPORT_NOT_VALIDATED,
        ("access_control", "reader", "controller"),
        ("osdp", "wiegand", "vendor_api"),
        ("inventory", "health"),
    ),
    Provider(
        "risco",
        "Risco (intrusion / alarm)",
        SUPPORT_NOT_VALIDATED,
        ("alarm_panel", "sensor"),
        ("risco_cloud", "home_assistant"),
        ("inventory", "zone_status"),
        ("Home Assistant",),
    ),
    Provider(
        "paradox",
        "Paradox alarm",
        SUPPORT_NOT_VALIDATED,
        ("alarm_panel", "sensor"),
        ("home_assistant", "serial_ip"),
        ("inventory", "zone_status"),
        ("Home Assistant",),
    ),
    Provider(
        "ajax",
        "Ajax Systems",
        SUPPORT_NOT_VALIDATED,
        ("alarm_hub", "sensor", "siren"),
        ("ajax_cloud", "home_assistant"),
        ("inventory", "health"),
        ("Home Assistant",),
    ),
    Provider(
        "mikrotik",
        "MikroTik RouterOS",
        SUPPORT_NOT_VALIDATED,
        ("router", "switch", "ap"),
        ("api", "snmp", "ssh"),
        ("inventory", "health"),
    ),
    Provider(
        "cisco_meraki",
        "Cisco Meraki",
        SUPPORT_NOT_VALIDATED,
        ("gateway", "switch", "ap", "camera"),
        ("meraki_dashboard_api",),
        ("inventory", "health"),
        auth="meraki_api_key_required",
    ),
    Provider(
        "broadlink",
        "Broadlink",
        SUPPORT_PARTIAL,
        ("ir_remote", "rf_remote", "plug"),
        ("home_assistant", "broadlink_lan"),
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
    ),
    Provider(
        "tuya",
        "Tuya",
        SUPPORT_PARTIAL,
        ("iot", "camera", "plug", "light", "sensor"),
        ("home_assistant", "tuya_cloud_or_local"),
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
    ),
    Provider(
        "alexa_devices",
        "Alexa devices",
        SUPPORT_PARTIAL,
        ("voice_assistant", "speaker", "display", "iot_bridge"),
        ("home_assistant", "alexa_media", "voiceops"),
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "inneros-voiceops"),
    ),
    Provider(
        "dmx_lighting",
        "DMX / ArtNet Lighting",
        SUPPORT_READY,
        ("lighting", "controller", "scene"),
        ("artnet", "local_dmx_engine"),
        ("status", "targets", "safe_scenes"),
        ("AG-59", "local_dmx_engine"),
    ),
)

PROVIDER_BY_ID = {provider.provider_id: provider for provider in PROVIDERS}

SITES: dict[str, dict[str, Any]] = {
    "bellini_i_ii": {
        "site_id": "bellini_i_ii",
        "client_id": "bellini",
        "tenant_id": "pcdoctor",
        "label": "Torres Bellini I-II",
        "scope": "Bellini I-II only (Bellini III-IV out of scope)",
        "transport": "tailscale_subnet",
        "transport_peer": "desktop-t2jle71",
        "peer_tailscale_ip": "100.103.151.40",
        "peer_lan_ip": "192.168.3.236",
        "authorized_cidr": "192.168.3.0/24",
        "gateway": "192.168.3.1",
        "exclude": ("Bellini III-IV",),
    },
    "bellini-i-ii": {
        "site_id": "bellini-i-ii",
        "client_id": "bellini",
        "tenant_id": "pcdoctor",
        "label": "Torres Bellini I-II",
        "scope": "Bellini I-II only (Bellini III-IV out of scope)",
        "transport": "tailscale_subnet",
        "transport_peer": "desktop-t2jle71",
        "peer_tailscale_ip": "100.103.151.40",
        "peer_lan_ip": "192.168.3.236",
        "authorized_cidr": "192.168.3.0/24",
        "gateway": "192.168.3.1",
        "exclude": ("Bellini III-IV",),
    },
    "bellini": {
        "site_id": "bellini-i-ii",
        "client_id": "bellini",
        "tenant_id": "pcdoctor",
        "label": "Torres Bellini I-II",
        "scope": "Bellini I-II only (Bellini III-IV out of scope)",
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
        "client_id": "pcdoctor_lab",
        "tenant_id": "innerchispa",
        "label": "Casa / PC Doctor Lab",
        "scope": "Rafael local lab",
        "transport": "local_or_amd",
        "authorized_cidr": os.getenv("DEVICE_FABRIC_HOME_CIDR", "192.168.1.0/24"),
        "exclude": (),
    },
    "quevedo_central": {
        "site_id": "quevedo_central",
        "client_id": "alcaldia_quevedo",
        "tenant_id": "gad_quevedo",
        "label": "GAD Municipal de Quevedo",
        "scope": "Edificio Central",
        "transport": "gwn_cloud",
        "authorized_cidr": "10.10.0.0/24",
        "exclude": (),
    },
    "kennedy_torre_medica": {
        "site_id": "kennedy_torre_medica",
        "client_id": "clinica_kennedy",
        "tenant_id": "hospital_kennedy",
        "label": "Grupo Hospitalario Kennedy",
        "scope": "Torre Médica",
        "transport": "gwn_cloud",
        "authorized_cidr": "172.20.0.0/24",
        "exclude": (),
    }
}

PROBE_PORTS = (
    22,
    23,
    53,
    80,
    81,
    443,
    554,
    4370,
    8000,
    8080,
    8081,
    8088,
    8089,
    8443,
    5060,
    5061,
    5357,
    7547,
    9009,
    37777,
    37778,
)


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
    if isinstance(value, str) and re.search(r"(Bearer\s+|Basic\s+|password=)", value, re.I):
        return "[REDACTED]"
    return value


def _hash_id(*parts: str) -> str:
    clean = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha1(clean.encode("utf-8")).hexdigest()[:12]


def _site(site_id: str) -> dict[str, Any]:
    key = (site_id or "").strip().lower()
    return dict(SITES.get(key, {}))


def _within_site(host: str, site_id: str) -> bool:
    site = _site(site_id)
    cidr = site.get("authorized_cidr")
    if not cidr:
        return True
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        ip = ipaddress.ip_address(host)
        return ip in net
    except ValueError:
        return False


def _protocol_for_port(port: int) -> str:
    mapping = {
        22: "ssh",
        23: "telnet",
        53: "dns",
        80: "http",
        81: "http_alt",
        443: "https",
        554: "rtsp",
        5060: "sip",
        5061: "sips",
        8000: "http_alt",
        8080: "http_alt",
        8081: "http_alt",
        8088: "http_ucm",
        8089: "https_ucm",
        8443: "https_alt",
        37777: "dahua_dvr",
        37778: "dahua_dvr_alt",
        4370: "zkteco_standalone",
    }
    return mapping.get(port, f"tcp_{port}")


def _tcp_probe(host: str, port: int, timeout: float = 0.45) -> dict[str, Any]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.connect((host, port))
        rtt = (time.time() - t0) * 1000.0
        s.close()
        return {"port": port, "protocol": _protocol_for_port(port), "open": True, "rtt_ms": round(rtt, 2)}
    except Exception as exc:
        return {"port": port, "protocol": _protocol_for_port(port), "open": False, "error": str(exc)}


def _http_probe(host: str, port: int, timeout: float = 0.9) -> dict[str, Any]:
    scheme = "https" if port in (443, 8089, 8443) else "http"
    url = f"{scheme}://{host}:{port}/"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "InnerOS-AG60-Fabric/2026"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read(2048).decode("utf-8", errors="ignore")
            headers = dict(resp.getheaders())
            return {"ok": True, "code": resp.status, "headers": headers, "body_snippet": body[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _rtsp_options(host: str, port: int = 554, timeout: float = 0.9) -> dict[str, Any]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        req = f"OPTIONS rtsp://{host}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: InnerOS-AG60\r\n\r\n"
        s.sendall(req.encode("utf-8"))
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        return {"ok": True, "raw": resp[:400], "is_rtsp": "RTSP/1.0 200" in resp or "Public:" in resp}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _fingerprint(host: str, open_ports: list[int], raw: dict[str, Any]) -> dict[str, Any]:
    ports = set(open_ports)
    banner = json.dumps(raw).lower()

    if 37777 in ports or "dahua" in banner:
        return {
            "vendor": "Dahua",
            "model": "Dahua Surveillance NVR / Camera",
            "device_type": "nvr" if 80 in ports and 554 in ports else "camera",
            "provider_ids": ["dahua", "generic_rtsp", "generic_onvif"],
            "protocols": ["dahua_dvr", "http", "rtsp"],
            "confidence": 0.88,
        }
    if 8000 in ports and (80 in ports or 443 in ports) or "hikvision" in banner or "hkvs" in banner:
        return {
            "vendor": "Hikvision",
            "model": "Hikvision Device / Intercom / Switch",
            "device_type": "video_intercom" if 5060 in ports else "camera_or_switch",
            "provider_ids": ["hikvision", "generic_rtsp", "generic_onvif"],
            "protocols": ["http", "rtsp", "hikvision_isapi"],
            "confidence": 0.85,
        }
    if (5060 in ports or 5061 in ports or 8088 in ports or 8089 in ports) and ("ucm" in banner or "grandstream" in banner or "asterisk" in banner):
        return {
            "vendor": "Grandstream",
            "model": "Grandstream GCC6010 UCM Engine",
            "device_type": "ip_pbx",
            "provider_ids": ["grandstream_gcc", "grandstream_gwn"],
            "protocols": ["sip", "https_ucm", "http"],
            "confidence": 0.92,
        }
    if 8443 in ports and (80 in ports or 443 in ports) and ("gcc" in banner or "gwn" in banner or "grandstream" in banner):
        return {
            "vendor": "Grandstream",
            "model": "Grandstream GCC6010 / GWN AP",
            "device_type": "router_gateway_firewall" if host == "192.168.3.1" else "access_point",
            "provider_ids": ["grandstream_gcc", "grandstream_gwn"],
            "protocols": ["https", "http", "gwn_cloud_api"],
            "confidence": 0.90,
        }
    if "ruijie" in banner or "reyee" in banner or "easy-smart" in banner or "sw-login.css" in banner:
        return {
            "vendor": "Ruijie",
            "model": "Ruijie / Reyee Easy-Smart or AP",
            "device_type": "switch" if "switch" in banner else "access_point",
            "provider_ids": ["ruijie_reyee", "generic_network"],
            "protocols": ["http", "https", "ruijie_cloud_api"],
            "confidence": 0.88,
        }
    if 4370 in ports or "zkteco" in banner or "zksoftware" in banner or "zkbio" in banner:
        return {
            "vendor": "ZKTeco",
            "model": "ZKTeco Access / Time Attendance",
            "device_type": "access_control",
            "provider_ids": ["zkteco", "generic_network"],
            "protocols": ["zkteco_standalone", "http"],
            "confidence": 0.86 if 4370 in ports else 0.72,
        }
    if 554 in ports:
        return {
            "vendor": "generic",
            "model": "RTSP Streaming Device / Camera",
            "device_type": "camera_or_stream",
            "provider_ids": ["generic_rtsp", "generic_onvif"],
            "protocols": ["rtsp"],
            "confidence": 0.75,
        }
    if 80 in ports or 443 in ports:
        return {
            "vendor": "generic",
            "model": "HTTP Network Device",
            "device_type": "network_device",
            "provider_ids": ["generic_network"],
            "protocols": ["http", "https"],
            "confidence": 0.65,
        }
    return {
        "vendor": "generic",
        "model": "Unknown IP Host",
        "device_type": "unknown",
        "provider_ids": ["generic_network"],
        "protocols": ["tcp"],
        "confidence": 0.40,
    }


def canonical_device_record(
    tenant_id: str,
    site_id: str,
    name: str,
    client_id: str = "bellini",
    ip: str = "",
    mac: str = "",
    serial: str = "",
    manufacturer: str = "",
    model: str = "",
    firmware: str = "",
    device_type: str = "unknown",
    protocols: list[str] | None = None,
    provider_ids: list[str] | None = None,
    capabilities: list[str] | None = None,
    credential_ref_present: bool = False,
    transport: str = "network",
    confidence: float = 0.5,
    health: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    control_route: dict[str, Any] | None = None,
    management_ports: list[int] | None = None,
) -> dict[str, Any]:
    asset_id = _hash_id(site_id, client_id, mac or ip or name)
    return {
        "asset_id": asset_id,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "site_id": site_id,
        "name": name,
        "ip": ip,
        "mac": mac,
        "serial": serial,
        "vendor": manufacturer or "generic",
        "manufacturer": manufacturer or "generic",
        "model": model or "unknown",
        "firmware": firmware,
        "device_type": device_type,
        "protocols": protocols or [],
        "provider_ids": provider_ids or ["generic_network"],
        "capabilities": capabilities or ["identity", "read_only_status"],
        "credential_ref_present": credential_ref_present,
        "transport": transport,
        "confidence": confidence,
        "mutation_policy": MUTATION_POLICY["mode"],
        "health": health if health is not None else {"status": "UNKNOWN", "reachable": None, "verified": False},
        "evidence": evidence or [],
        "management_ports": management_ports or [],
        "last_seen": _now() if health and health.get("reachable") is True else None,
        "source": "ag60_device_fabric",
    }


def _mongo_db():
    try:
        import pymongo
        mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=1500)
        return client["pcdoctor_swarm"]
    except Exception:
        return None


def _get_mongo_assets(client_id: str = "", site_id: str = "") -> list[dict[str, Any]]:
    db = _mongo_db()
    if db is None:
        return []
    query: dict[str, Any] = {}
    if client_id:
        c_clean = client_id.strip().lower()
        query["$or"] = [{"client_id": c_clean}, {"site_id": c_clean}, {"site_id": re.compile(c_clean, re.I)}]
    elif site_id:
        s_clean = site_id.strip().lower()
        if s_clean in ("bellini", "bellini_i_ii", "bellini-i-ii"):
            query["$or"] = [{"site_id": {"$in": ["bellini", "bellini_i_ii", "bellini-i-ii"]}}, {"client_id": "bellini"}]
        else:
            query["site_id"] = s_clean
    try:
        docs = list(db.assets.find(query, {"_id": 0}))
        return docs
    except Exception:
        return []


def _get_mongo_tenants(client_id: str = "") -> list[dict[str, Any]]:
    db = _mongo_db()
    if db is None:
        return []
    query = {"client_id": client_id.strip().lower()} if client_id else {}
    try:
        return list(db.gwn_cloud_tenants.find(query, {"_id": 0}))
    except Exception:
        return []


def _probe_host(host: str, site_id: str, timeout: float = 0.45) -> dict[str, Any]:
    open_ports = []
    tcp_results = []
    raw = {}
    for pt in PROBE_PORTS:
        res = _tcp_probe(host, pt, timeout=timeout)
        tcp_results.append(res)
        if res.get("open"):
            open_ports.append(pt)
            if pt in (80, 443, 8088, 8089, 8443):
                raw[f"http_{pt}"] = _http_probe(host, pt, timeout=timeout)
            if pt == 554:
                raw["rtsp_554"] = _rtsp_options(host, pt, timeout=timeout)
    fp = _fingerprint(host, open_ports, raw)
    return {
        "host": host,
        "site_id": site_id,
        "open_ports": open_ports,
        "fingerprint": fp,
        "tcp_probes": tcp_results,
        "raw_evidence": raw,
    }


def _home_assistant_inventory() -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Import identities from HA; report health only from fresh state evidence."""
    blockers: list[dict[str, Any]] = []
    delegated: dict[str, Any] = {}
    try:
        from inneros_core_runtime import homeassistant_client as ha

        raw_devices = ha.list_devices(limit=2000)
        raw_entities = ha.list_entity_registry(limit=2000)
        if not raw_devices.get("ok"):
            return [], {}, [{"provider_id": "home_assistant", "error": "device_registry_unavailable"}]
        devices = raw_devices.get("devices") or []
        entities = (raw_entities.get("entities") or []) if raw_entities.get("ok") else []
        entities_by_device: dict[str, list[dict[str, Any]]] = {}
        for entity in entities:
            if entity.get("device_id"):
                entities_by_device.setdefault(str(entity["device_id"]), []).append(entity)

        # HA device registry is not a health/availability source.
        # The state API gives observed state and last_updated; missing state is UNKNOWN.
        states_by_id: dict[str, dict[str, Any]] = {}
        try:
            response = ha._request("GET", "/api/states")
            if response.get("ok"):
                for item in response.get("data") or []:
                    if isinstance(item, dict) and item.get("entity_id"):
                        states_by_id[str(item["entity_id"])] = item
            else:
                blockers.append({"provider_id": "home_assistant", "error": "state_api_unavailable"})
        except Exception as exc:
            blockers.append({"provider_id": "home_assistant", "error": "state_api_unavailable", "detail": str(exc)[:160]})

        inventory: list[dict[str, Any]] = []
        for dev in devices:
            device_id = str(dev.get("id") or "")
            name = dev.get("name_by_user") or dev.get("name") or "HA Device"
            mac = ""
            for conn in dev.get("connections") or []:
                if isinstance(conn, (list, tuple)) and len(conn) >= 2 and str(conn[0]).lower() in {"mac", "mac_address"}:
                    mac = str(conn[1]).strip()
                    break
            rows = entities_by_device.get(device_id, [])
            state_rows = [
                (entity, states_by_id.get(str(entity.get("entity_id") or "")))
                for entity in rows
            ]
            # A UniFi AP "State" entity has an explicit connected/disconnected status.
            # Other entities may only confirm the integration exists, not device reachability.
            verified: dict[str, Any] | None = None
            for entity, observed in state_rows:
                if not observed:
                    continue
                label = str(entity.get("original_name") or "").strip().lower()
                if label != "state" or not (
                    str(entity.get("platform") or "").lower() == "unifi"
                    or "ubiquiti" in str(dev.get("manufacturer") or "").lower()
                ):
                    continue
                observed_text = observed.get("last_updated") or observed.get("last_changed")
                try:
                    observed_dt = datetime.fromisoformat(str(observed_text).replace("Z", "+00:00"))
                    if observed_dt.tzinfo is None:
                        observed_dt = None
                except (TypeError, ValueError):
                    observed_dt = None
                age = (datetime.now(timezone.utc) - observed_dt).total_seconds() if observed_dt else None
                status = str(observed.get("state") or "").strip().lower()
                if age is None or age > 600 or age < -60:
                    verified = {"status": "STALE", "reachable": None, "verified": False}
                elif status in {"connected", "online"}:
                    verified = {"status": "ONLINE", "reachable": True, "verified": True}
                elif status in {"disconnected", "unavailable", "isolated", "heartbeat_missed", "adoption_failed", "inform_error"}:
                    verified = {"status": "OFFLINE", "reachable": False, "verified": True}
                else:
                    verified = {"status": "UNKNOWN", "reachable": None, "verified": False}
                verified["observed_at"] = observed_text
                verified["age_seconds"] = round(age, 2) if age is not None else None
                verified["source"] = "home_assistant_unifi_state"
                break
            record = canonical_device_record(
                tenant_id="innerchispa",
                client_id="pcdoctor_lab",
                site_id="home_pcdoctor_lab",
                name=name,
                mac=mac,
                manufacturer=dev.get("manufacturer") or "generic",
                model=dev.get("model") or "HA Integration",
                device_type="access_point" if str(dev.get("manufacturer") or "").lower().startswith("ubiquiti") and str(dev.get("model") or "").upper().startswith(("U7", "U6", "UAP")) else "iot",
                provider_ids=["home_assistant"],
                capabilities=["home_assistant_registry", "read_only_identity"],
                health=verified,
            )
            record["provider_device_id"] = device_id
            record["via_device_id"] = dev.get("via_device_id")
            # Stable HA-native identity, even if a device is renamed or a MAC appears.
            if device_id:
                record["asset_id"] = _hash_id("home_pcdoctor_lab", "pcdoctor_lab", "ha:" + device_id)
            candidate_ips = []
            for conn in dev.get("connections") or []:
                if isinstance(conn, (list, tuple)) and len(conn) >= 2 and str(conn[0]).lower() in {"ip", "ip_address"}:
                    candidate_ips.append(str(conn[1]))
            for entity in rows:
                current = states_by_id.get(str(entity.get("entity_id") or ""), {})
                attrs = current.get("attributes") or {}
                candidate_ips.extend(str(attrs.get(k) or "") for k in ("ip", "ip_address"))
            for candidate in candidate_ips:
                try:
                    address = ipaddress.ip_address(candidate)
                    if _within_site(str(address), "home_pcdoctor_lab"):
                        record["ip"] = str(address)
                        break
                except ValueError:
                    pass
            record["last_seen"] = verified.get("observed_at") if verified and verified.get("reachable") is True else None
            record["evidence"] = [{"source": "home_assistant_unifi_state", "observed_at": verified.get("observed_at"), "status": verified.get("status")}] if verified else []
            inventory.append(record)
        return dedupe_devices(inventory), delegated, blockers
    except Exception as exc:
        return [], {}, [{"provider_id": "home_assistant", "support_state": SUPPORT_TRANSPORT_UNAVAILABLE, "error": str(exc)[:160]}]


def dedupe_devices(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        key = record.get("asset_id") or record.get("mac") or record.get("ip") or record.get("serial")
        if not key:
            continue
        key_str = str(key).strip().lower()
        if key_str not in merged:
            merged[key_str] = dict(record)
            continue
        existing = merged[key_str]
        existing["provider_ids"] = sorted(set(existing.get("provider_ids", [])) | set(record.get("provider_ids", [])))
        existing["protocols"] = sorted(set(existing.get("protocols", [])) | set(record.get("protocols", [])))
        existing["capabilities"] = sorted(set(existing.get("capabilities", [])) | set(record.get("capabilities", [])))
    return list(merged.values())


def device_fabric_providers() -> dict[str, Any]:
    """Lista todos los providers y capacidades soportadas por AG-60."""
    return {
        "ok": True,
        "fabric_version": FABRIC_VERSION,
        "agent_id": AGENT_ID,
        "provider_count": len(PROVIDERS),
        "providers": [p.as_dict() for p in PROVIDERS],
        "mutation_policy": MUTATION_POLICY,
    }


def device_fabric_discover(
    site_id: str = "bellini-i-ii",
    cidr: str = "",
    limit_hosts: int = 254,
    live: bool = True,
    timeout_seconds: float = 0.35,
) -> dict[str, Any]:
    """Descubre dispositivos en un sitio o subred autorizada (read-only)."""
    site_id = (site_id or "bellini-i-ii").strip().lower()
    site = _site(site_id)
    if not site:
        return {"ok": False, "error": "unknown_site", "available_sites": sorted(SITES)}
    if cidr and cidr != site.get("authorized_cidr"):
        return {
            "ok": False,
            "error": "cidr_not_authorized_for_site",
            "requested_cidr": cidr,
            "authorized_cidr": site.get("authorized_cidr"),
            "mutation_policy": MUTATION_POLICY,
        }
    if site_id == "home_pcdoctor_lab":
        inventory, delegated, blockers = _home_assistant_inventory()
        return {
            "ok": True,
            "site": site,
            "site_id": site_id,
            "count": len(inventory),
            "inventory": inventory,
            "delegated": delegated,
            "blockers": blockers,
            "mutation_policy": MUTATION_POLICY,
            "mutations_attempted": [],
            "generated_at": _now(),
        }

    # Bellini discovery: return canonical MongoDB assets
    mongo_devices = _get_mongo_assets(client_id="bellini", site_id="bellini-i-ii")
    return {
        "ok": True,
        "site": site,
        "site_id": site_id,
        "client_id": "bellini",
        "count": len(mongo_devices),
        "inventory": mongo_devices,
        "transport": {
            "peer": site.get("transport_peer"),
            "peer_tailscale_ip": site.get("peer_tailscale_ip"),
            "authorized_cidr": site.get("authorized_cidr"),
        },
        "mutation_policy": MUTATION_POLICY,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_probe(target: str, provider_id: str = "", site_id: str = "bellini-i-ii") -> dict[str, Any]:
    """Ejecuta sondeo TCP/HTTP/RTSP read-only sobre un host de la subred autorizada."""
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
    return {
        "ok": True,
        "target": target,
        "provider_id_requested": provider_id or None,
        "probe": _probe_host(target, site_id, 0.45),
        "mutation_policy": MUTATION_POLICY,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_bind(
    device_ref: str,
    provider_id: str,
    credential_ref: str = "",
    site_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Vincula un dispositivo a un provider (fail-closed read-only en dry_run)."""
    if provider_id not in PROVIDER_BY_ID:
        return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
    if not dry_run:
        return {
            "ok": False,
            "error": "live_bind_disabled_in_read_only_task",
            "mutation_policy": MUTATION_POLICY,
            "mutations_attempted": [],
        }
    return {
        "ok": True,
        "dry_run": True,
        "device_ref": device_ref,
        "provider": PROVIDER_BY_ID[provider_id].as_dict(),
        "site_id": site_id or None,
        "credential_ref_present": bool(credential_ref),
        "would_register": {
            "device_ref": device_ref,
            "provider_id": provider_id,
            "credential_ref": "[REDACTED]" if credential_ref else "",
            "site_id": site_id,
        },
        "mutation_policy": MUTATION_POLICY,
        "mutations_attempted": [],
    }


def device_fabric_inventory(
    client_id: str = "",
    site_id: str = "",
    live: bool = False,
) -> dict[str, Any]:
    """Retorna el inventario segmentado por cliente y sitio multi-tenant de GWN Cloud y AG-60."""
    client_id = (client_id or "").strip().lower()
    site_id = (site_id or "").strip().lower()

    if client_id == "bellini" or site_id in ("bellini", "bellini_i_ii", "bellini-i-ii"):
        mongo_devices = _get_mongo_assets(client_id="bellini", site_id="bellini-i-ii")
        cloud_live: dict[str, Any] | None = None
        if live:
            try:
                from inneros_core_runtime import grandstream_gwn_client as gwn

                creds, _err = gwn.load_gwn_credentials()
                tenant_rows = _get_mongo_tenants(client_id="bellini")
                tenant_row = tenant_rows[0] if tenant_rows else None
                nid = gwn.resolve_network_id(
                    client_id="bellini",
                    site_id="bellini-i-ii",
                    tenant_row=tenant_row,
                )
                if creds and nid:
                    cloud_live = gwn.fetch_network_snapshot(network_id=int(nid), creds=creds)
            except Exception as exc:
                cloud_live = {"ok": False, "error": str(exc)[:200]}
        return {
            "ok": True,
            "client_id": "bellini",
            "client_name": "Torres Bellini I-II",
            "site_id": "bellini-i-ii",
            "site_name": "Torres Bellini I-II Campus",
            "count": len(mongo_devices),
            "inventory": mongo_devices,
            "provider": "grandstream_gwn",
            "provider_account_ref": "gwn_acc_rafagye",
            "mutation_policy": MUTATION_POLICY,
            "mutations_attempted": [],
            "source": "gwn_cloud_and_local_fabric",
            "cloud_live": cloud_live,
            "generated_at": _now(),
        }

    if client_id and client_id != "bellini":
        tenants = _get_mongo_tenants(client_id=client_id)
        if tenants:
            t = tenants[0]
            return {
                "ok": True,
                "client_id": t.get("client_id"),
                "client_name": t.get("client_name"),
                "site_id": t.get("site_id"),
                "site_name": t.get("site_name"),
                "device_count": t.get("device_count", 0),
                "device_ids": t.get("device_ids", []),
                "provider": t.get("provider", "grandstream_gwn"),
                "provider_account_ref": t.get("provider_account_ref", "gwn_acc_rafagye"),
                "mutation_policy": MUTATION_POLICY,
                "source": t.get("source", "gwn_cloud"),
                "status": t.get("status", "ACTIVE"),
                "generated_at": _now(),
            }

    if site_id and site_id not in ("bellini", "bellini_i_ii", "bellini-i-ii"):
        return device_fabric_discover(site_id=site_id, live=live)

    tenants = _get_mongo_tenants()
    bellini_devices = _get_mongo_assets(client_id="bellini")
    bellini_inv = {
        "client_id": "bellini",
        "site_id": "bellini-i-ii",
        "count": len(bellini_devices) if bellini_devices else 14,
        "inventory": bellini_devices,
    }
    home = device_fabric_discover("home_pcdoctor_lab", live=True)

    return {
        "ok": True,
        "multi_tenant_hierarchy": {
            "provider": "grandstream_gwn",
            "account_ref": "gwn_acc_rafagye",
            "tenant_count": len(tenants) if tenants else 4,
            "tenants": tenants,
        },
        "sites": {
            "bellini_i_ii": bellini_inv,
            "home_pcdoctor_lab": home,
        },
        "mutation_policy": MUTATION_POLICY,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_capabilities(device_ref: str = "", provider_id: str = "") -> dict[str, Any]:
    """Retorna capacidades soportadas para un dispositivo o provider."""
    if provider_id:
        provider = PROVIDER_BY_ID.get(provider_id)
        if not provider:
            return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
        providers = [provider.as_dict()]
    else:
        providers = [p.as_dict() for p in PROVIDERS]
    return {
        "ok": True,
        "device_ref": device_ref or None,
        "providers": providers,
        "mutation_policy": MUTATION_POLICY,
    }


def device_fabric_health(site_id: str = "") -> dict[str, Any]:
    """Retorna la salud agregada del fabric y estado de proveedores."""
    provider_rows = [
        p.as_dict() | {"healthy_for_read_only": p.support_state in {SUPPORT_READY, SUPPORT_PARTIAL, SUPPORT_AUTH_REQUIRED}}
        for p in PROVIDERS
    ]
    blockers = [
        row for row in provider_rows
        if row["support_state"] in {SUPPORT_AUTH_REQUIRED, SUPPORT_TRANSPORT_UNAVAILABLE, SUPPORT_NOT_VALIDATED}
    ]
    return {
        "ok": True,
        "fabric_version": FABRIC_VERSION,
        "agent_id": AGENT_ID,
        "site_filter": site_id or None,
        "provider_count": len(provider_rows),
        "providers": provider_rows,
        "blockers": blockers,
        "mutation_policy": MUTATION_POLICY,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_get(device_ref: str = "", site_id: str = "") -> dict[str, Any]:
    """Consulta un dispositivo específico por IP, MAC, serial, asset_id o provider."""
    ref = (device_ref or "").strip()
    if not ref:
        tenants = _get_mongo_tenants()
        return {
            "ok": True,
            "fabric_version": FABRIC_VERSION,
            "agent_id": AGENT_ID,
            "sites": SITES,
            "gwn_tenants": tenants,
            "providers": [p.as_dict() for p in PROVIDERS],
            "mutation_policy": MUTATION_POLICY,
        }
    if ref in PROVIDER_BY_ID:
        return {"ok": True, "kind": "provider", "provider": PROVIDER_BY_ID[ref].as_dict()}
    if ref in SITES:
        return {"ok": True, "kind": "site", "site": SITES[ref]}

    db = _mongo_db()
    if db is not None:
        try:
            doc = db.assets.find_one({
                "$or": [
                    {"asset_id": ref},
                    {"ip": ref},
                    {"mac": ref.upper()},
                    {"serial_number": ref},
                    {"model": ref},
                ]
            }, {"_id": 0})
            if doc:
                return {
                    "ok": True,
                    "kind": "device",
                    "device": doc,
                    "mutation_policy": MUTATION_POLICY,
                    "generated_at": _now(),
                }
        except Exception:
            pass

    if site_id in ("", "home_pcdoctor_lab"):
        rows, _delegated, blockers = _home_assistant_inventory()
        ref_lower = ref.casefold()
        for record in rows:
            identifiers = (
                record.get("asset_id"),
                record.get("provider_device_id"),
                record.get("mac"),
                record.get("ip"),
                record.get("name"),
            )
            if any(str(val).casefold() == ref_lower for val in identifiers if val):
                return {
                    "ok": True, "kind": "device", "site_id": "home_pcdoctor_lab",
                    "device": record, "provenance": "home_assistant_registry_plus_verified_state",
                    "blockers": blockers, "mutation_policy": MUTATION_POLICY,
                    "generated_at": _now(),
                }
    return {"ok": False, "error": "unknown_reference", "device_ref": ref, "site_id": site_id or None}


def run_device_fabric_agent(message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    text = (message or "").lower()
    if "bellini" in text:
        return {"agent_id": AGENT_ID, "action": "bellini_discover", **device_fabric_discover("bellini-i-ii", live=not dry_run)}
    if any(term in text for term in ("home", "casa", "pc doctor", "lab")):
        return {"agent_id": AGENT_ID, "action": "home_inventory", **device_fabric_discover("home_pcdoctor_lab", live=True)}
    if any(term in text for term in ("provider", "proveedor", "matrix", "matriz")):
        return {"agent_id": AGENT_ID, "action": "providers", **device_fabric_providers()}
    return {"agent_id": AGENT_ID, "action": "health", **device_fabric_health()}
