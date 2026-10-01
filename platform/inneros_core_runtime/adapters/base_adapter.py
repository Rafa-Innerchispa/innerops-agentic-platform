"""
Base Network Adapter Contract for Capability Gateway
Correlation ID: bellini-capability-gateway-20260930
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set

# Standard telemetry states
STATE_MEASURED = "MEASURED"
STATE_CONFIGURED = "CONFIGURED"
STATE_OBSERVED = "OBSERVED"
STATE_INFERRED = "INFERRED"
STATE_OWNER_REPORTED = "OWNER_REPORTED"
STATE_UNKNOWN = "UNKNOWN"
STATE_UNSUPPORTED = "UNSUPPORTED"
STATE_UNREACHABLE = "UNREACHABLE"

VALID_STATES = {
    STATE_MEASURED,
    STATE_CONFIGURED,
    STATE_OBSERVED,
    STATE_INFERRED,
    STATE_OWNER_REPORTED,
    STATE_UNKNOWN,
    STATE_UNSUPPORTED,
    STATE_UNREACHABLE
}

ALL_SECTIONS = [
    "inventory",
    "health",
    "interfaces",
    "arp",
    "dhcp",
    "vlans",
    "mac_table",
    "lldp",
    "routes",
    "clients",
    "logs",
    "events",
    "poe",
    "channels",
    "storage",
    "firmware"
]


class BaseNetworkAdapter(ABC):
    """Abstract Base Class for all network device query adapters."""

    def __init__(self, name: str, supported_sections: Set[str]):
        self.name = name
        self.supported_sections = supported_sections

    @abstractmethod
    def handles_device(self, device_ref: str, provider_hint: Optional[str] = None) -> bool:
        """Return True if this adapter can handle the given device identifier or provider hint."""
        pass

    @abstractmethod
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
        """Execute a read-only query against the device and return normalized telemetry."""
        pass

    def build_section_response(
        self,
        section: str,
        state: str,
        data: Any,
        confidence: float = 1.0,
        raw_evidence_ref: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Helper to format a single section's standardized payload."""
        if state not in VALID_STATES:
            state = STATE_UNKNOWN
        return {
            "state": state,
            "confidence": confidence,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "raw_evidence_ref": raw_evidence_ref,
            "notes": notes,
            "data": data
        }
