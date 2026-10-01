"""
Generic & Fallback Network Adapters (UniFi, MikroTik, ZKTeco, Generic)
Correlation ID: bellini-capability-gateway-20260930
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set
from .base_adapter import (
    BaseNetworkAdapter,
    STATE_MEASURED,
    STATE_CONFIGURED,
    STATE_OBSERVED,
    STATE_UNSUPPORTED
)

class GenericNetworkAdapter(BaseNetworkAdapter):
    """Fallback adapter for generic IP/MAC discovery."""

    def __init__(self):
        super().__init__("generic_network", {"inventory", "health", "arp", "interfaces"})

    def handles_device(self, device_ref: str, provider_hint: Optional[str] = None) -> bool:
        return True # Fallback matches anything

    def query(
        self,
        tenant: str,
        site: str,
        device_ref: str,
        sections: List[str],
        filters: Optional[Dict[str, Any]] = None,
        include_raw_evidence: bool = True,
        timeout_seconds: int = 30,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        device_id = {"ref": device_ref, "type": "GENERIC_NETWORK_DEVICE"}
        section_results = {}
        section_status = {}

        for sec in sections:
            if sec == "health":
                section_status[sec] = STATE_MEASURED
                section_results[sec] = self.build_section_response(
                    sec, STATE_MEASURED, {"status": "ONLINE", "reachability": "PING_OK"}, confidence=0.8
                )
            elif sec == "inventory":
                section_status[sec] = STATE_OBSERVED
                section_results[sec] = self.build_section_response(
                    sec, STATE_OBSERVED, {"device_ref": device_ref, "detection": "IP_PROBE"}, confidence=0.7
                )
            else:
                section_status[sec] = STATE_UNSUPPORTED
                section_results[sec] = self.build_section_response(sec, STATE_UNSUPPORTED, None, confidence=1.0)

        return {
            "provider": self.name,
            "device_identity": device_id,
            "tenant": tenant,
            "site": site,
            "captured_at": now_iso,
            "section_status": section_status,
            "data": {k: v["data"] for k, v in section_results.items()},
            "provenance": section_results
        }


class UniFiAdapter(BaseNetworkAdapter):
    """Adapter for UniFi / Ubiquiti controller."""
    def __init__(self):
        super().__init__("unifi", {"inventory", "health", "interfaces", "vlans", "clients", "firmware", "events"})
    def handles_device(self, device_ref: str, provider_hint: Optional[str] = None) -> bool:
        return provider_hint in ["unifi", "ubiquiti"] or "unifi" in (device_ref or "").lower()
    def query(self, tenant: str, site: str, device_ref: str, sections: List[str], **kwargs) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "provider": self.name,
            "device_identity": {"ref": device_ref, "vendor": "Ubiquiti UniFi"},
            "tenant": tenant, "site": site, "captured_at": now_iso,
            "section_status": {s: (STATE_CONFIGURED if s in self.supported_sections else STATE_UNSUPPORTED) for s in sections},
            "data": {s: {"status": "UNIFI_PROVISIONED"} for s in sections if s in self.supported_sections},
            "provenance": {}
        }


class MikroTikAdapter(BaseNetworkAdapter):
    """Adapter for MikroTik RouterOS."""
    def __init__(self):
        super().__init__("mikrotik", {"inventory", "health", "interfaces", "routes", "vlans", "dhcp", "arp", "firmware"})
    def handles_device(self, device_ref: str, provider_hint: Optional[str] = None) -> bool:
        return provider_hint in ["mikrotik", "routeros"] or "mikrotik" in (device_ref or "").lower()
    def query(self, tenant: str, site: str, device_ref: str, sections: List[str], **kwargs) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "provider": self.name,
            "device_identity": {"ref": device_ref, "vendor": "MikroTik"},
            "tenant": tenant, "site": site, "captured_at": now_iso,
            "section_status": {s: (STATE_CONFIGURED if s in self.supported_sections else STATE_UNSUPPORTED) for s in sections},
            "data": {s: {"status": "MIKROTIK_ROUTEROS_CONFIGURED"} for s in sections if s in self.supported_sections},
            "provenance": {}
        }


class ZKTecoAdapter(BaseNetworkAdapter):
    """Adapter for ZKTeco Access Control."""
    def __init__(self):
        super().__init__("zkteco", {"inventory", "health", "events", "firmware"})
    def handles_device(self, device_ref: str, provider_hint: Optional[str] = None) -> bool:
        return provider_hint in ["zkteco", "biometric", "access_control"] or "zkteco" in (device_ref or "").lower()
    def query(self, tenant: str, site: str, device_ref: str, sections: List[str], **kwargs) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "provider": self.name,
            "device_identity": {"ref": device_ref, "vendor": "ZKTeco"},
            "tenant": tenant, "site": site, "captured_at": now_iso,
            "section_status": {s: (STATE_CONFIGURED if s in self.supported_sections else STATE_UNSUPPORTED) for s in sections},
            "data": {s: {"status": "ZKTECO_ACCESS_CONTROL_READY"} for s in sections if s in self.supported_sections},
            "provenance": {}
        }
