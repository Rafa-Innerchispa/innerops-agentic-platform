"""Truth-first Nebius × NVIDIA client (public sanitized edition)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_LOCAL_MODEL = "deterministic_inneros_heuristic_v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TelemetrySanitizer:
    """Redact credentials and infrastructure identifiers before cloud use."""

    @classmethod
    def _redact_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            clean: Dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized == "authorization" or any(marker in normalized for marker in ("password", "secret", "token", "credential", "api_key", "serial")):
                    clean[str(key)] = "[REDACTED]"
                else:
                    clean[str(key)] = cls._redact_fields(item)
            return clean
        if isinstance(value, (list, tuple)):
            return [cls._redact_fields(item) for item in value]
        return value

    @classmethod
    def sanitize(cls, raw_data: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        raw_str = json.dumps(cls._redact_fields(raw_data))
        replacements = 0
        ip_pattern = re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")
        for index, match in enumerate(sorted(set(ip_pattern.findall(raw_str))), start=1):
            raw_str = raw_str.replace(match, f"10.0.0.{index}")
            replacements += 1
        mac_pattern = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
        for index, match in enumerate(sorted(set(mac_pattern.findall(raw_str))), start=1):
            raw_str = raw_str.replace(match, f"02:00:00:00:00:{index:02X}")
            replacements += 1
        raw_str = re.sub(r"(?i)(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", r"\1 [REDACTED]", raw_str)
        return json.loads(raw_str), replacements


class NebiusNvidiaReasoning:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self.base_url = (base_url or os.environ.get("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE_URL)).rstrip("/")
        self.model = model or os.environ.get("NEBIUS_NVIDIA_MODEL", "")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def is_nvidia_open_model(model_id: str) -> bool:
        normalized = str(model_id or "").lower()
        return normalized.startswith("nvidia/") or "nemotron" in normalized

    def list_models(self) -> list[str]:
        if not self.api_key:
            raise ValueError("NEBIUS_API_KEY is not configured")
        request = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return sorted(
            str(row.get("id") or "")
            for row in payload.get("data", [])
            if isinstance(row, dict) and row.get("id")
        )

    def resolve_live_nvidia_model(self) -> str:
        available = self.list_models()
        if self.model:
            if not self.is_nvidia_open_model(self.model) or self.model not in available:
                raise ValueError("configured_nvidia_model_not_in_live_catalog")
            return self.model
        candidates = [item for item in available if self.is_nvidia_open_model(item)]
        if not candidates:
            raise ValueError("no_nvidia_model_in_live_catalog")
        self.model = candidates[0]
        return self.model

    def _local(self, sanitized: Dict[str, Any], reason: str) -> Dict[str, Any]:
        diagnosis = {
            "root_cause": "Buffer saturation or memory pressure",
            "severity": "high",
            "recommended_action": "reboot",
            "recommended_capability": "network.device.reboot.v1",
            "target_device": sanitized.get("device_ref", "device_01"),
            "requires_approval": True,
            "confidence": 0.80,
        }
        return {
            "ok": True,
            "provider": "local_heuristic",
            "model": DEFAULT_LOCAL_MODEL,
            "inference_mode": "LOCAL_HEURISTIC",
            "diagnosis": diagnosis,
            "provider_receipt": {"evidence_mode": "NOT_RUN", "status": reason},
            "sanitized_inputs": sanitized,
        }

    def diagnose(self, telemetry: Dict[str, Any], *, force_local: bool = False) -> Dict[str, Any]:
        sanitized, replacement_count = TelemetrySanitizer.sanitize(telemetry)
        if force_local or not self.api_key or not self.model:
            result = self._local(
                sanitized,
                "FORCE_LOCAL" if force_local else "MISSING_API_KEY_OR_VALIDATED_MODEL",
            )
            result["sanitization"] = {"private_identifiers_replaced": replacement_count}
            return result
        if not self.is_nvidia_open_model(self.model):
            return self._local(sanitized, "MODEL_NOT_EXPLICITLY_NVIDIA")

        prompt = "Diagnose this sanitized physical infrastructure state and return JSON only:\n" + json.dumps(sanitized)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            diagnosis = json.loads(payload["choices"][0]["message"]["content"])
        except Exception as exc:
            result = self._local(sanitized, f"REMOTE_INFERENCE_FAILED:{type(exc).__name__}")
            result["provider_receipt"] = {
                "evidence_mode": "BLOCKED",
                "status": "REMOTE_INFERENCE_FAILED",
                "error_type": type(exc).__name__,
            }
            return result

        response_id = str(payload.get("id") or "")
        receipt_seed = f"{response_id}:{self.model}:{hashlib.sha256(prompt.encode()).hexdigest()}"
        return {
            "ok": True,
            "provider": "nebius_token_factory",
            "model": self.model,
            "inference_mode": "REAL",
            "diagnosis": diagnosis,
            "provider_receipt": {
                "evidence_mode": "REAL",
                "response_id": response_id or None,
                "receipt_sha256": hashlib.sha256(receipt_seed.encode()).hexdigest(),
                "received_at": now_iso(),
            },
            "sanitization": {"private_identifiers_replaced": replacement_count},
        }
