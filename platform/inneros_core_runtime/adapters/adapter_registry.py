"""
Adapter Registry for Network Device Query Capability
Correlation ID: bellini-capability-gateway-20260930
"""

from typing import Dict, Any, List, Optional
from .base_adapter import BaseNetworkAdapter
from .grandstream_gcc import GrandstreamGCCAdapter
from .grandstream_gwn import GrandstreamGWNAdapter
from .hikvision import HikvisionAdapter
from .dahua import DahuaAdapter
from .generic_and_aux import (
    GenericNetworkAdapter,
    UniFiAdapter,
    MikroTikAdapter,
    ZKTecoAdapter
)

class AdapterRegistry:
    """Central registry of device query adapters."""

    def __init__(self):
        self._adapters: List[BaseNetworkAdapter] = [
            GrandstreamGCCAdapter(),
            GrandstreamGWNAdapter(),
            HikvisionAdapter(),
            DahuaAdapter(),
            UniFiAdapter(),
            MikroTikAdapter(),
            ZKTecoAdapter(),
            GenericNetworkAdapter() # Fallback last
        ]

    def resolve_adapter(self, device_ref: str, provider_hint: Optional[str] = None) -> BaseNetworkAdapter:
        """Find the most specific adapter for the given device and optional hint."""
        if provider_hint:
            hint = provider_hint.lower().strip()
            for ad in self._adapters:
                if ad.name.lower() == hint or hint in ad.name.lower():
                    return ad
        
        for ad in self._adapters:
            if ad.handles_device(device_ref, provider_hint):
                return ad

        return self._adapters[-1] # Generic fallback

# Global default registry instance
default_adapter_registry = AdapterRegistry()
