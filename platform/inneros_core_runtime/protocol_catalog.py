"""Protocol taxonomy for AG-60. A protocol hint is not a live health check."""
from __future__ import annotations
from typing import Any

PROTOCOL_FAMILIES = {
    "ethernet_ip": ("ipv4","ipv6","arp","icmp","tcp","udp","dhcp","dns","lldp","snmp","poe","vlan","ntp","mdns","ssdp"),
    "wifi": ("wifi_2_4","wifi_5","wifi_6","802_11k","802_11v","802_11r","wpa2","wpa3"),
    "overlay": ("tailscale","wireguard","vpn","subnet_router","exit_node"),
    "camera_intercom": ("onvif","rtsp","isapi","dahua_rpc","sip","rtp","webrtc"),
    "iot_mesh": ("zigbee","zigbee_green_power","z_wave","thread","matter","homekit","ble","esphome"),
    "radio": ("rf_315","rf_433","rf_868","rf_915","lora","lorawan","infrared","rfid","nfc"),
    "industrial": ("rs232","rs422","rs485","uart","modbus_rtu","modbus_tcp","can","canopen","bacnet_ip","bacnet_mstp","knx","dali","dmx512","rdm","artnet","sacn","osdp","wiegand"),
    "host_bus": ("usb_hid","usb_serial","gpio","i2c","spi","onewire"),
    "messaging": ("mqtt","coap","websocket","http","https","amqp","nats"),
    "energy": ("pi30_xmart","sunspec","nut_ups","vedirect","opc_ua","mbus"),
}
INTEGRATION_HINTS = {
    "unifi": ("ethernet_ip","wifi"),
    "zha": ("zigbee",),
    "zigbee2mqtt": ("zigbee","mqtt"),
    "deconz": ("zigbee",),
    "zwave_js": ("z_wave",),
    "matter": ("matter",),
    "thread": ("thread",),
    "bluetooth": ("ble",),
    "esphome": ("esphome",),
    "mqtt": ("mqtt",),
    "modbus": ("modbus_rtu_or_tcp_unknown",),
    "knx": ("knx",),
    "hue": ("zigbee_bridge",),
    "broadlink": ("rf_or_ir_bridge",),
    "hubitat": ("multi_protocol_bridge",),
    "homekit_controller": ("homekit",),
    "onvif": ("onvif",),
    "dahua": ("dahua_rpc",),
    "hikvision": ("isapi",),
    "tuya": ("tuya_transport_unknown",),
    "tasmota": ("mqtt_or_http",),
    "shelly": ("wifi_or_ethernet",),
    "alexa_media": ("alexa_cloud_or_local",),
}
BRAND_FAMILIES = {
    "camera_security": ("Dahua","Hikvision","Imou","EZVIZ","Reolink","Axis","Uniview","Hanwha","Bosch","Avigilon","Tapo","VIGI","Intelbras","Amcrest","Foscam"),
    "network": ("Ubiquiti","UniFi","Grandstream","MikroTik","TP-Link","Omada","Ruijie","Reyee","Netgear","Cisco","Aruba","Ruckus","Fortinet","Cambium"),
    "home_automation": ("Aqara","Sonoff","Shelly","Tuya","Smart Life","IKEA","Philips Hue","Broadlink","Hubitat","SmartThings","Lutron","Control4","ESPHome"),
    "voice_media": ("Amazon Echo","Alexa","Google Nest","Chromecast","Apple HomePod","Sonos","Denon","Yamaha"),
    "industrial_energy": ("Xmart","Victron","Growatt","Solis","SMA","Fronius","Deye","Schneider","Siemens","ABB","Eaton","APC"),
}
STATE_UNKNOWN = "UNKNOWN"


def integration_hints(entities: list[dict[str, Any]]) -> list[str]:
    hints: set[str] = set()
    for entry in entities:
        platform = str(entry.get("platform") or "").lower().strip()
        hints.update(INTEGRATION_HINTS.get(platform, ()))
    return sorted(hints)


def inventory_protocol_coverage(
    devices: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    provider_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Catalog vendor-independent protocols and gaps without inventing liveness."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in entities:
        if row.get("device_id"):
            grouped.setdefault(str(row["device_id"]), []).append(row)
    providers = {p.get("provider_id"): p.get("support_state") for p in provider_rows}
    items = []
    found_hints: set[str] = set()
    for dev in devices:
        native_id = str(dev.get("id") or "")
        hints = integration_hints(grouped.get(native_id, []))
        found_hints.update(hints)
        items.append({
            "device_id": native_id,
            "name": dev.get("name_by_user") or dev.get("name") or "unnamed",
            "manufacturer": dev.get("manufacturer"),
            "model": dev.get("model"),
            "via_device_id": dev.get("via_device_id"),
            "protocol_hints": hints,
            "connectivity_status": STATE_UNKNOWN,
            "reason": "registry_does_not_prove_reachability",
        })
    return {
        "ok": True,
        "registered_devices": len(items),
        "devices": items,
        "observed_integration_hints": sorted(found_hints),
        "declared_protocol_families": {k: list(v) for k, v in PROTOCOL_FAMILIES.items()},
        "brand_ecosystems": {k: list(v) for k, v in BRAND_FAMILIES.items()},
        "provider_support": providers,
        "live_telemetry_verified": False,
        "missing_collectors_must_report_unknown": True,
    }
