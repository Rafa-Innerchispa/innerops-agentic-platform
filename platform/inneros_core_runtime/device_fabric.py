"""Universal Physical Device Fabric.

Small read-only surface for discovering and identifying physical devices across
customer sites and the PC Doctor lab. The fabric coordinates existing adapters
instead of replacing them: AG-32/Home Assistant/UniFi/Intelbras, AG-59 DMX,
Workforce ADMS/iClock, Physical Guardian and vendor protocol probes.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

AGENT_ID = "AG-60"
FABRIC_VERSION = "0.1.0"

READ_ONLY_POLICY = {
    "mode": "read_only",
    "allowed_live_operations": [
        "tcp_connect_probe",
        "http_get_root_or_known_status_path",
        "rtsp_options",
        "home_assistant_registry_read",
        "dmx_status_read",
    ],
    "forbidden_live_operations": [
        "credential_bruteforce",
        "configuration_write",
        "dhcp_change",
        "vlan_change",
        "firewall_change",
        "firmware_update",
        "device_reboot",
        "ptz_move",
        "alarm_arm_disarm",
        "camera_or_nvr_user_change",
    ],
}


@dataclass(frozen=True)
class Provider:
    provider_id: str
    label: str
    families: tuple[str, ...]
    status: str
    integration: str
    capabilities: tuple[str, ...]
    reused_from: tuple[str, ...] = ()
    auth: str = "not_required_for_discovery"
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "families": list(self.families),
            "status": self.status,
            "integration": self.integration,
            "capabilities": list(self.capabilities),
            "reused_from": list(self.reused_from),
            "auth": self.auth,
            "notes": list(self.notes),
        }


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "hikvision",
        "Hikvision",
        ("camera", "nvr", "dvr", "video_intercom", "access_control"),
        "ready_read_only_probe",
        "native_probe_plus_physical_guardian",
        ("discover", "probe", "inventory", "capabilities", "rtsp", "onvif_hint"),
        ("inneros-physical-guardian",),
        "required_for_authenticated_model_details",
        ("ISAPI and SDK writes are intentionally not exposed here.",),
    ),
    Provider(
        "dahua",
        "Dahua",
        ("camera", "nvr", "dvr", "xvr", "analog_channel"),
        "ready_read_only_probe",
        "native_probe_plus_physical_guardian",
        ("discover", "probe", "inventory", "rtsp", "analog_channel_mapping"),
        ("inneros-physical-guardian",),
        "required_for_authenticated_model_details",
        ("Analog cameras behind DVR/NVR are represented as child channels.",),
    ),
    Provider(
        "tplink_tapo",
        "TP-Link / Tapo",
        ("camera", "plug", "iot"),
        "ready_read_only_probe",
        "generic_network_probe",
        ("discover", "probe", "inventory"),
        ("Home Assistant",),
        "required_for_cloud_or_local_binding",
    ),
    Provider(
        "imou",
        "Imou",
        ("camera", "nvr"),
        "ready_read_only_probe",
        "generic_network_probe",
        ("discover", "probe", "inventory", "rtsp"),
        ("inneros-physical-guardian",),
        "required_for_authenticated_model_details",
    ),
    Provider(
        "ezviz",
        "EZVIZ",
        ("camera", "doorbell"),
        "ready_read_only_probe",
        "generic_network_probe",
        ("discover", "probe", "inventory", "rtsp"),
        ("Home Assistant", "inneros-physical-guardian"),
        "required_for_cloud_or_local_binding",
    ),
    Provider(
        "zkteco_adms_iclock",
        "ZKTeco ADMS/iClock",
        ("attendance", "access_control", "biometric_terminal"),
        "delegated",
        "workforce_adms_iclock",
        ("inventory", "capabilities", "health"),
        ("innerspark-workforce-ai",),
        "managed_by_workforce_secret_store",
    ),
    Provider(
        "grandstream_ucm",
        "Grandstream UCM",
        ("pbx", "voice_gateway"),
        "ready_read_only_probe",
        "voiceops_plus_network_probe",
        ("discover", "probe", "inventory", "sip_http_fingerprint"),
        ("inneros-voiceops",),
        "required_for_authenticated_pbx_details",
    ),
    Provider(
        "grandstream_gwn",
        "Grandstream GWN/GCC",
        ("router", "switch", "access_point", "controller"),
        "ready_read_only_probe",
        "network_probe",
        ("discover", "probe", "inventory", "http_fingerprint"),
        ("inneros-voiceops",),
        "required_for_authenticated_network_details",
    ),
    Provider(
        "intelbras",
        "Intelbras",
        ("alarm", "camera", "nvr", "router"),
        "delegated",
        "homeassistant_intelbras_guardian",
        ("inventory", "capabilities", "health", "alarm_read_only"),
        ("Home Assistant", "AG-32"),
        "guardian_or_homeassistant_token_required_for_state",
    ),
    Provider(
        "unifi_ubiquiti",
        "UniFi / Ubiquiti",
        ("gateway", "switch", "access_point", "wlan", "client"),
        "delegated",
        "homeassistant_unifi",
        ("inventory", "capabilities", "health", "wifi_read_only"),
        ("Home Assistant", "AG-32"),
        "homeassistant_or_controller_token_required",
    ),
    Provider(
        "dmx_ag59",
        "DMX / Art-Net",
        ("lighting", "stage_controller"),
        "delegated",
        "ag59_dmx_artnet_orchestrator",
        ("inventory", "capabilities", "health"),
        ("AG-59 DMX",),
        "not_required_for_status",
    ),
    Provider(
        "broadlink",
        "Broadlink",
        ("ir_remote", "rf_remote", "plug"),
        "delegated",
        "homeassistant_broadlink",
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
        "homeassistant_token_required",
    ),
    Provider(
        "tuya",
        "Tuya",
        ("iot", "camera", "plug", "light"),
        "delegated",
        "homeassistant_tuya",
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "AG-32"),
        "homeassistant_or_tuya_credentials_required",
    ),
    Provider(
        "alexa",
        "Alexa devices",
        ("voice_assistant", "speaker", "display", "iot_bridge"),
        "delegated",
        "homeassistant_alexa_media_or_voiceops",
        ("inventory", "capabilities", "health"),
        ("Home Assistant", "inneros-voiceops"),
        "integration_token_required",
    ),
    Provider(
        "onvif",
        "ONVIF",
        ("camera", "nvr", "video_intercom"),
        "ready_read_only_probe",
        "generic_onvif_probe",
        ("discover", "probe", "inventory", "capabilities"),
        ("inneros-physical-guardian",),
        "required_for_authenticated_profile_details",
    ),
    Provider(
        "rtsp",
        "RTSP",
        ("video_stream", "camera", "nvr", "dvr"),
        "ready_read_only_probe",
        "generic_rtsp_options",
        ("discover", "probe", "inventory"),
        ("inneros-physical-guardian",),
        "not_required_for_options_probe",
    ),
    Provider(
        "generic_network",
        "Generic network discovery",
        ("unknown", "router", "switch", "pc", "iot"),
        "ready_read_only_probe",
        "tcp_http_probe",
        ("discover", "probe", "inventory", "health"),
        (),
        "not_required_for_discovery",
    ),
)

PROVIDER_BY_ID = {p.provider_id: p for p in PROVIDERS}

SITES: dict[str, dict[str, Any]] = {
    "bellini_i_ii": {
        "label": "Torres Bellini I-II",
        "scope": "Bellini I-II only",
        "transport_peer": "desktop-t2jle71",
        "peer_tailscale_ip": "100.103.151.40",
        "authorized_cidr": "192.168.3.0/24",
        "peer_lan_ip": "192.168.3.236",
        "gateway": "192.168.3.1",
        "allow_external_scope": False,
    },
    "home_pcdoctor_lab": {
        "label": "Casa / PC Doctor Lab",
        "scope": "Rafael local lab",
        "transport_peer": "local_or_amd",
        "authorized_cidr": os.getenv("DEVICE_FABRIC_HOME_CIDR", "192.168.1.0/24"),
        "allow_external_scope": False,
    },
}

DEFAULT_PROBE_PORTS = (
    22,
    23,
    53,
    80,
    81,
    443,
    554,
    8000,
    8080,
    8081,
    8443,
    5060,
    5061,
    7547,
    8088,
    8089,
    9009,
    37777,
    37778,
    5357,
    2020,
    5000,
)


@dataclass
class Evidence:
    source: str
    detail: str
    confidence: float = 0.5
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "detail": self.detail,
            "confidence": round(float(self.confidence), 3),
            "raw": _redact(self.raw),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_s = str(key)
            if re.search(r"(token|secret|password|passwd|credential|authorization|cookie|api[_-]?key)", key_s, re.I):
                out[key_s] = "[REDACTED]"
            else:
                out[key_s] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and re.search(r"(Bearer\s+|Basic\s+|sk-|api[_-]?key=|password=)", value, re.I):
        return "[REDACTED]"
    return value


def _safe_limit(limit: int, default: int = 256, maximum: int = 512) -> int:
    try:
        return max(1, min(int(limit), maximum))
    except Exception:
        return default


def _site(site_id: str) -> dict[str, Any]:
    return SITES.get((site_id or "").strip().lower(), {})


def _ip_in_site(host: str, site_id: str) -> bool:
    site = _site(site_id)
    cidr = site.get("authorized_cidr")
    if not cidr:
        return False
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _tcp_probe(host: str, port: int, timeout: float = 0.45) -> dict[str, Any]:
    started = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        return {
            "port": int(port),
            "state": "open",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except (OSError, ValueError) as exc:
        return {"port": int(port), "state": "closed_or_filtered", "error": type(exc).__name__}
    finally:
        sock.close()


def _http_probe(host: str, port: int, timeout: float = 1.0) -> dict[str, Any]:
    scheme = "https" if int(port) in {443, 8443} else "http"
    url = f"{scheme}://{host}:{int(port)}/"
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "InnerOS-DeviceFabric/0.1 read-only"})
    context = ssl._create_unverified_context() if scheme == "https" else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            return {
                "ok": True,
                "url": url,
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body_preview": body[:500],
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": True,
            "url": url,
            "status": exc.code,
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body_preview": "",
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": type(exc).__name__, "detail": str(exc)[:160]}


def _rtsp_options(host: str, port: int = 554, timeout: float = 1.0) -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        payload = (
            f"OPTIONS rtsp://{host}:{int(port)}/ RTSP/1.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: InnerOS-DeviceFabric/0.1 read-only\r\n\r\n"
        ).encode("ascii")
        sock.sendall(payload)
        data = sock.recv(2048).decode("utf-8", errors="replace")
        return {"ok": bool(data), "port": int(port), "response_preview": data[:700]}
    except Exception as exc:
        return {"ok": False, "port": int(port), "error": type(exc).__name__, "detail": str(exc)[:160]}
    finally:
        sock.close()


def _classify(host: str, open_ports: list[int], probes: dict[str, Any]) -> dict[str, Any]:
    evidence: list[Evidence] = []
    providers: set[str] = set()
    device_type = "unknown"
    vendor = "unknown"
    model = ""
    confidence = 0.25
    haystack = json.dumps(probes, ensure_ascii=False).lower()

    if 554 in open_ports:
        providers.add("rtsp")
        device_type = "video_stream"
        evidence.append(Evidence("tcp", "RTSP port 554 open", 0.55, {"host": host}))
    if 8000 in open_ports:
        providers.add("hikvision")
        vendor = "Hikvision"
        device_type = "camera_or_recorder"
        confidence = max(confidence, 0.62)
        evidence.append(Evidence("tcp", "Hikvision SDK port 8000 open", 0.7))
    if "realm=\\\"ds-" in haystack or "realm=\"ds-" in haystack or "ds-k1t" in haystack or "hikvision" in haystack:
        providers.add("hikvision")
        vendor = "Hikvision"
        device_type = "camera_or_video_intercom"
        confidence = max(confidence, 0.82)
        evidence.append(Evidence("rtsp/http", "Hikvision fingerprint observed", 0.82))
    if any(port in open_ports for port in (37777, 37778)) or "dahua" in haystack:
        providers.add("dahua")
        vendor = "Dahua"
        device_type = "camera_or_dvr_nvr"
        confidence = max(confidence, 0.75)
        evidence.append(Evidence("tcp/http", "Dahua service fingerprint observed", 0.75))
    if any(port in open_ports for port in (5060, 5061, 8088, 8089)) or "asterisk" in haystack:
        providers.add("grandstream_ucm")
        vendor = "Grandstream"
        device_type = "pbx_or_voice_gateway"
        confidence = max(confidence, 0.68)
        evidence.append(Evidence("tcp/http", "SIP/Asterisk/Grandstream voice ports observed", 0.68))
    if any(term in haystack for term in ("grandstream", "gcc", "gwn")):
        providers.add("grandstream_gwn")
        vendor = "Grandstream"
        device_type = "router_switch_ap_or_controller"
        confidence = max(confidence, 0.72)
        evidence.append(Evidence("http", "Grandstream network fingerprint observed", 0.72))
    if any(term in haystack for term in ("ruijie", "reyee", "rg-est", "est310")):
        vendor = "Ruijie"
        device_type = "wireless_bridge"
        confidence = max(confidence, 0.78)
        evidence.append(Evidence("http", "Ruijie/Reyee fingerprint observed", 0.78))
    if "microsoft-httpapi" in haystack or 5357 in open_ports:
        vendor = "Microsoft"
        device_type = "windows_pc_or_service_host"
        confidence = max(confidence, 0.58)
        evidence.append(Evidence("tcp/http", "Microsoft HTTPAPI/WS-Discovery service observed", 0.58))
    if any(term in haystack for term in ("tapo", "tp-link", "tplink")):
        providers.add("tplink_tapo")
        vendor = "TP-Link/Tapo"
        device_type = "iot_or_camera"
        confidence = max(confidence, 0.74)
    if any(term in haystack for term in ("imou",)):
        providers.add("imou")
        vendor = "Imou"
        device_type = "camera"
        confidence = max(confidence, 0.72)
    if any(term in haystack for term in ("ezviz",)):
        providers.add("ezviz")
        vendor = "EZVIZ"
        device_type = "camera_or_doorbell"
        confidence = max(confidence, 0.72)
    if any(term in haystack for term in ("onvif",)):
        providers.add("onvif")
        confidence = max(confidence, 0.66)
    if any(port in open_ports for port in (37777, 37778)):
        providers.add("dahua")
        vendor = "Dahua"
        device_type = "camera_or_dvr_nvr"
        confidence = max(confidence, 0.82)
        evidence.append(Evidence("tcp", "Dahua private media/control port observed", 0.82))
    if not providers:
        providers.add("generic_network")

    if host == SITES["bellini_i_ii"]["gateway"]:
        device_type = "router_gateway"
        providers.add("grandstream_gwn")
        vendor = "Grandstream" if vendor == "unknown" else vendor
        confidence = max(confidence, 0.74)
    if host == SITES["bellini_i_ii"]["peer_lan_ip"]:
        device_type = "windows_peer"
        vendor = "Microsoft" if vendor == "unknown" else vendor
        confidence = max(confidence, 0.85)

    return {
        "vendor": vendor,
        "model": model,
        "device_type": device_type,
        "provider_ids": sorted(providers),
        "confidence": round(confidence, 3),
        "evidence": [item.as_dict() for item in evidence],
    }


def _device_id(site_id: str, host: str, provider_ids: list[str]) -> str:
    main_provider = provider_ids[0] if provider_ids else "generic_network"
    return f"{site_id}:{main_provider}:{host}".replace("/", "_")


def _probe_host(host: str, *, ports: tuple[int, ...] = DEFAULT_PROBE_PORTS, site_id: str = "", timeout: float = 0.45) -> dict[str, Any]:
    tcp_results = [_tcp_probe(host, port, timeout=timeout) for port in ports]
    open_ports = [int(row["port"]) for row in tcp_results if row.get("state") == "open"]
    probes: dict[str, Any] = {"tcp": tcp_results}
    for port in [p for p in open_ports if p in {80, 81, 443, 8080, 8081, 8443}][:4]:
        probes[f"http_{port}"] = _http_probe(host, port)
    if 554 in open_ports:
        probes["rtsp_554"] = _rtsp_options(host, 554)
    classification = _classify(host, open_ports, probes)
    return {
        "device_id": _device_id(site_id or "adhoc", host, classification["provider_ids"]),
        "site_id": site_id or "adhoc",
        "ip": host,
        "mac": "",
        "hostname": "",
        "manufacturer": classification["vendor"],
        "model": classification["model"],
        "device_type": classification["device_type"],
        "provider_ids": classification["provider_ids"],
        "services": [{"port": port, "protocol": _port_protocol(port), "state": "open"} for port in open_ports],
        "evidence": classification["evidence"] + [Evidence("tcp_scan", f"{len(open_ports)} open port(s) observed", 0.55, {"open_ports": open_ports}).as_dict()],
        "confidence": classification["confidence"],
        "read_only": True,
        "mutations_attempted": [],
        "raw_probe": _redact(probes),
    }


def _port_protocol(port: int) -> str:
    return {
        22: "ssh",
        23: "telnet",
        53: "dns",
        80: "http",
        81: "http-alt",
        443: "https",
        554: "rtsp",
        8000: "hikvision-sdk",
        8080: "http-alt",
        8081: "http-alt",
        8443: "https-alt",
        5060: "sip",
        5061: "sips",
        7547: "cwmp",
        8088: "asterisk-http",
        8089: "asterisk-https",
        9009: "intelbras-candidate",
        37777: "dahua-private",
        37778: "dahua-private",
        5357: "ws-discovery",
        2020: "iot-candidate",
        5000: "upnp/http",
    }.get(int(port), "tcp")


def _scan_cidr(site_id: str, *, limit_hosts: int = 254, timeout: float = 0.35, max_workers: int = 96) -> list[dict[str, Any]]:
    site = _site(site_id)
    if not site:
        return []
    network = ipaddress.ip_network(site["authorized_cidr"], strict=False)
    hosts = [str(ip) for ip in network.hosts()]
    limit = _safe_limit(limit_hosts, default=len(hosts), maximum=len(hosts))
    hosts = hosts[:limit]

    found: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(max_workers, 128))) as executor:
        future_map = {
            executor.submit(_probe_host, host, ports=DEFAULT_PROBE_PORTS, site_id=site_id, timeout=timeout): host
            for host in hosts
        }
        for future in concurrent.futures.as_completed(future_map):
            try:
                item = future.result()
            except Exception as exc:
                item = {"ip": future_map[future], "error": type(exc).__name__, "read_only": True, "mutations_attempted": []}
            if item.get("services"):
                found.append(item)
    return sorted(found, key=lambda row: tuple(int(part) for part in str(row.get("ip", "0.0.0.0")).split(".") if part.isdigit()))


def _homeassistant_devices() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    try:
        from raphiia_openai import homeassistant_client as ha
    except Exception as exc:
        return [], [], [], [{"provider": "home_assistant", "error": "import_failed", "detail": str(exc)[:160]}]

    raw_devices = ha.list_devices(limit=2000)
    raw_entities = ha.list_entity_registry(limit=2000)
    raw_states = ha.list_states(limit=2000)
    if raw_devices.get("ok"):
        devices = list(raw_devices.get("devices") or [])
    else:
        blockers.append({"provider": "home_assistant_devices", "error": raw_devices.get("error"), "detail": raw_devices.get("detail")})
    if raw_entities.get("ok"):
        entities = list(raw_entities.get("entities") or [])
    else:
        blockers.append({"provider": "home_assistant_entities", "error": raw_entities.get("error"), "detail": raw_entities.get("detail")})
    if raw_states.get("ok"):
        states = list(raw_states.get("entities") or [])
    else:
        blockers.append({"provider": "home_assistant_states", "error": raw_states.get("error"), "detail": raw_states.get("detail")})
    return devices, entities, states, blockers


def _providers_for_ha_device(device: dict[str, Any], entities: list[dict[str, Any]]) -> list[str]:
    haystack = json.dumps([device, [e for e in entities if e.get("device_id") == device.get("id")]], ensure_ascii=False).lower()
    mapping = [
        ("ucm", "grandstream_ucm"),
        ("central ip", "grandstream_ucm"),
        ("ubiquiti", "unifi_ubiquiti"),
        ("unifi", "unifi_ubiquiti"),
        ("intelbras", "intelbras"),
        ("broadlink", "broadlink"),
        ("tuya", "tuya"),
        ("alexa", "alexa"),
        ("amazon", "alexa"),
        ("ezviz", "ezviz"),
        ("tapo", "tplink_tapo"),
        ("tp-link", "tplink_tapo"),
        ("tplink", "tplink_tapo"),
        ("imou", "imou"),
        ("dahua", "dahua"),
        ("hikvision", "hikvision"),
        ("gwn", "grandstream_gwn"),
        ("gcc", "grandstream_gwn"),
        ("grandstream", "grandstream_gwn"),
    ]
    found = [provider for needle, provider in mapping if needle in haystack]
    return sorted(set(found or ["generic_network"]))


def _inventory_home_pcdoctor_lab() -> dict[str, Any]:
    devices, entities, states, blockers = _homeassistant_devices()
    inventory: list[dict[str, Any]] = []
    entities_by_device: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        if entity.get("device_id"):
            entities_by_device.setdefault(str(entity["device_id"]), []).append(entity)
    for device in devices:
        provider_ids = _providers_for_ha_device(device, entities)
        connections = device.get("connections") or []
        mac = next((row[1] for row in connections if isinstance(row, list) and row and row[0] == "mac"), "")
        inventory.append(
            {
                "device_id": f"home_pcdoctor_lab:{provider_ids[0]}:{device.get('id')}",
                "site_id": "home_pcdoctor_lab",
                "ip": "",
                "mac": mac,
                "hostname": device.get("name_by_user") or device.get("name") or "",
                "manufacturer": device.get("manufacturer") or "",
                "model": device.get("model") or "",
                "device_type": _ha_device_type(provider_ids, device),
                "provider_ids": provider_ids,
                "services": [],
                "evidence": [
                    Evidence(
                        "home_assistant_device_registry",
                        "Device observed through Home Assistant registry",
                        0.76,
                        {"device_id": device.get("id"), "entity_count": len(entities_by_device.get(str(device.get("id")), []))},
                    ).as_dict()
                ],
                "confidence": 0.76,
                "read_only": True,
                "mutations_attempted": [],
            }
        )

    delegated: dict[str, Any] = {}
    try:
        from raphiia_openai import homeassistant_client as ha

        delegated["unifi"] = _redact(ha.unifi_network_ops("status read-only"))
        delegated["intelbras"] = _redact(ha.alarm_intelbras_ops("status read-only"))
    except Exception as exc:
        blockers.append({"provider": "ag32_homeassistant", "error": "delegated_call_failed", "detail": str(exc)[:160]})
    try:
        from raphiia_openai.agents import ag59_dmx_artnet_orchestrator as ag59

        delegated["dmx"] = _redact(ag59.dmx_status())
    except Exception as exc:
        blockers.append({"provider": "ag59_dmx", "error": "delegated_call_failed", "detail": str(exc)[:160]})

    return {
        "ok": True,
        "site_id": "home_pcdoctor_lab",
        "site": SITES["home_pcdoctor_lab"],
        "count": len(inventory),
        "inventory": inventory,
        "delegated": delegated,
        "blockers": blockers,
        "read_only": True,
        "mutations_attempted": [],
    }


def _ha_device_type(provider_ids: list[str], device: dict[str, Any]) -> str:
    model = str(device.get("model") or "").lower()
    if "intelbras" in provider_ids:
        return "alarm_or_security_device"
    if "dmx_ag59" in provider_ids:
        return "lighting_controller"
    if "broadlink" in provider_ids:
        return "ir_rf_bridge"
    if "tuya" in provider_ids:
        return "tuya_iot"
    if "alexa" in provider_ids:
        return "voice_assistant"
    if any(pid in provider_ids for pid in ("hikvision", "dahua", "ezviz", "imou", "tplink_tapo")):
        return "camera_or_iot"
    if "grandstream_ucm" in provider_ids:
        return "pbx_or_voice_gateway"
    if "grandstream_gwn" in provider_ids:
        return "router_switch_ap_or_controller"
    if "unifi" in provider_ids[0] or "unifi_ubiquiti" in provider_ids:
        if "wlan" in model:
            return "wlan"
        if "gateway" in model:
            return "gateway"
        return "access_point_or_network_device"
    return "iot_or_unknown"


def device_fabric_providers() -> dict[str, Any]:
    return {
        "ok": True,
        "fabric_version": FABRIC_VERSION,
        "agent_id": AGENT_ID,
        "provider_count": len(PROVIDERS),
        "providers": [p.as_dict() for p in PROVIDERS],
        "read_only_policy": READ_ONLY_POLICY,
    }


def device_fabric_discover(
    site_id: str = "bellini_i_ii",
    cidr: str = "",
    limit_hosts: int = 254,
    live: bool = True,
    timeout_seconds: float = 0.35,
) -> dict[str, Any]:
    site_id = (site_id or "bellini_i_ii").strip().lower()
    site = dict(_site(site_id))
    if not site:
        return {"ok": False, "error": "unknown_site", "available_sites": sorted(SITES)}
    if cidr and cidr != site.get("authorized_cidr"):
        return {
            "ok": False,
            "error": "cidr_not_authorized_for_site",
            "requested_cidr": cidr,
            "authorized_cidr": site.get("authorized_cidr"),
            "read_only": True,
        }
    if site_id == "home_pcdoctor_lab":
        return _inventory_home_pcdoctor_lab()
    if not live:
        return {
            "ok": True,
            "site_id": site_id,
            "site": site,
            "count": 0,
            "inventory": [],
            "live": False,
            "read_only": True,
            "mutations_attempted": [],
        }
    inventory = _scan_cidr(site_id, limit_hosts=limit_hosts, timeout=float(timeout_seconds))
    return {
        "ok": True,
        "site_id": site_id,
        "site": site,
        "count": len(inventory),
        "inventory": inventory,
        "transport": {
            "peer": site.get("transport_peer"),
            "peer_tailscale_ip": site.get("peer_tailscale_ip"),
            "authorized_cidr": site.get("authorized_cidr"),
            "note": "Read-only probes are scoped to the configured CIDR; no device auth or writes are attempted.",
        },
        "live": True,
        "read_only": True,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_probe(target: str, provider_id: str = "", site_id: str = "bellini_i_ii") -> dict[str, Any]:
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "target_required"}
    if provider_id and provider_id not in PROVIDER_BY_ID:
        return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
    try:
        ipaddress.ip_address(target)
    except ValueError:
        return {"ok": False, "error": "ip_target_required_for_read_only_probe", "target": target}
    if site_id and site_id in SITES and not _ip_in_site(target, site_id):
        return {"ok": False, "error": "target_outside_authorized_site_cidr", "target": target, "site_id": site_id}
    item = _probe_host(target, site_id=site_id)
    return {
        "ok": True,
        "target": target,
        "provider_id_requested": provider_id or None,
        "probe": item,
        "read_only": True,
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
    if provider_id not in PROVIDER_BY_ID:
        return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
    if not dry_run:
        return {
            "ok": False,
            "error": "live_bind_disabled_in_read_only_fabric",
            "reason": "This task is discovery-only. Store credentials through the owner vault/provider-specific flow before enabling binds.",
            "read_only": True,
            "mutations_attempted": [],
        }
    return {
        "ok": True,
        "dry_run": True,
        "device_ref": device_ref,
        "provider": PROVIDER_BY_ID[provider_id].as_dict(),
        "credential_ref_present": bool(credential_ref),
        "site_id": site_id or None,
        "would_register": {
            "device_ref": device_ref,
            "provider_id": provider_id,
            "credential_ref": "[REDACTED]" if credential_ref else "",
            "read_only": True,
        },
        "read_only": True,
        "mutations_attempted": [],
    }


def device_fabric_inventory(site_id: str = "", live: bool = False) -> dict[str, Any]:
    if site_id:
        return device_fabric_discover(site_id=site_id, live=live)
    sites = {}
    for sid in ("bellini_i_ii", "home_pcdoctor_lab"):
        sites[sid] = device_fabric_discover(site_id=sid, live=live if sid == "bellini_i_ii" else True)
    return {
        "ok": all(bool(site.get("ok")) for site in sites.values()),
        "sites": sites,
        "read_only": True,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_capabilities(device_ref: str = "", provider_id: str = "") -> dict[str, Any]:
    if provider_id:
        provider = PROVIDER_BY_ID.get(provider_id)
        if not provider:
            return {"ok": False, "error": "unknown_provider", "available": sorted(PROVIDER_BY_ID)}
        providers = [provider]
    else:
        providers = list(PROVIDERS)
    return {
        "ok": True,
        "device_ref": device_ref or None,
        "providers": [p.as_dict() for p in providers],
        "read_only_policy": READ_ONLY_POLICY,
        "capability_contract": {
            "discover": "Find reachable devices inside an authorized site CIDR.",
            "identify": "Infer vendor/type from passive service fingerprints.",
            "probe": "Read-only service reachability and protocol banner checks.",
            "bind": "Dry-run registration only until credential flow is explicitly configured.",
            "inventory": "Normalize live observations from probes and delegated adapters.",
            "health": "Surface provider readiness and blockers without changing devices.",
            "get": "Return provider/site/device fabric metadata.",
        },
    }


def device_fabric_health(site_id: str = "") -> dict[str, Any]:
    provider_rows = []
    blockers = []
    for provider in PROVIDERS:
        row = provider.as_dict()
        row["healthy_for_discovery"] = provider.status in {"ready_read_only_probe", "delegated"}
        if "required" in provider.auth and provider.status not in {"ready_read_only_probe", "delegated"}:
            blockers.append({"provider_id": provider.provider_id, "auth": provider.auth})
        provider_rows.append(row)
    home = {}
    if not site_id or site_id == "home_pcdoctor_lab":
        home = _inventory_home_pcdoctor_lab()
    return {
        "ok": True,
        "fabric_version": FABRIC_VERSION,
        "agent_id": AGENT_ID,
        "site_filter": site_id or None,
        "provider_count": len(provider_rows),
        "providers": provider_rows,
        "home_adapter_status": {
            "ok": bool(home.get("ok", True)),
            "blockers": home.get("blockers", []),
            "delegated_keys": sorted((home.get("delegated") or {}).keys()),
        },
        "read_only_policy": READ_ONLY_POLICY,
        "blockers": blockers,
        "mutations_attempted": [],
        "generated_at": _now(),
    }


def device_fabric_get(device_ref: str) -> dict[str, Any]:
    ref = (device_ref or "").strip()
    if not ref:
        return {
            "ok": True,
            "fabric_version": FABRIC_VERSION,
            "agent_id": AGENT_ID,
            "sites": SITES,
            "providers": [p.as_dict() for p in PROVIDERS],
            "read_only_policy": READ_ONLY_POLICY,
        }
    if ref in PROVIDER_BY_ID:
        return {"ok": True, "kind": "provider", "provider": PROVIDER_BY_ID[ref].as_dict()}
    if ref in SITES:
        return {"ok": True, "kind": "site", "site_id": ref, "site": SITES[ref]}
    return {"ok": False, "error": "unknown_device_or_provider_or_site", "device_ref": ref}


def run_device_fabric_agent(message: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    text = (message or "").strip().lower()
    if "bellini" in text:
        return {"ok": True, "agent_id": AGENT_ID, "action": "bellini_inventory", **device_fabric_discover("bellini_i_ii", live=not dry_run)}
    if any(word in text for word in ("casa", "home", "pc doctor", "lab")):
        return {"ok": True, "agent_id": AGENT_ID, "action": "home_inventory", **device_fabric_discover("home_pcdoctor_lab")}
    if any(word in text for word in ("provider", "proveedor", "matrix", "matriz")):
        return {"ok": True, "agent_id": AGENT_ID, "action": "providers", **device_fabric_providers()}
    return {"ok": True, "agent_id": AGENT_ID, "action": "health", **device_fabric_health()}
