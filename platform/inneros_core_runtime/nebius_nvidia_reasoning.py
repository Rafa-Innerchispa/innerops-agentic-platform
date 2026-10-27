"""Nebius × NVIDIA Physical AI Reasoning Adapter for InnerOS.

Core Thesis:
"Cloud intelligence. Local authority. Verified physical actions."

Architecture:
- Cloud Reasoning: Uses NVIDIA open models hosted on Nebius AI Cloud / Token Factory.
- Strict Sanitization: Private network data (customer names, private IPs, MACs, credentials)
  are sanitized before transmission to Nebius. Nebius never receives direct control or private credentials.
- Local Authority: Actions are planned and executed locally through InnerOS Capability Gateway.
- Approval Gating: Live physical mutations strictly require owner authorization.
- Resilient Fallback: Uses an explicitly labeled deterministic local heuristic
  when Nebius is unavailable; it never claims local-model inference without a receipt.
- Bounded 7-step Physical AI Workflow:
  Discover -> Diagnose -> Recommend -> Approval -> Execute Locally -> Verify Recovery -> Evidence Receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.request
import urllib.error


DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
# Live inference must name a model returned by the authenticated Token Factory
# ``GET /models`` call.  Keeping this empty prevents an old model label from
# being presented as current evidence.
DEFAULT_NEBIUS_MODEL = ""
DEFAULT_LOCAL_MODEL = "deterministic_inneros_heuristic_v1"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000/v1"
NEBIUS_VAULT_REFS = (
    ("nebius_token_factory", "api_key"),
    ("nebius", "api_key"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_nebius_api_key_from_vault() -> Tuple[str, str]:
    """Load a Nebius key server-side; return ``(secret, source_ref)``.

    The helper never logs or serializes the secret. Environment fallback is
    disabled unless an operator explicitly sets ``NEBIUS_ALLOW_ENV_KEY=1``.
    """
    try:
        from inneros_core_runtime import owner_vault

        for category, key in NEBIUS_VAULT_REFS:
            row = owner_vault.get_owner_credential(
                key,
                category=category,
                reveal=True,
                actor="RAFAEL",
            )
            secret = str(row.get("secret") or "").strip() if isinstance(row, dict) else ""
            if row.get("ok") and secret:
                return secret, f"owner_vault:{category}/{key}"
    except Exception:
        pass

    if os.environ.get("NEBIUS_ALLOW_ENV_KEY", "").strip() == "1":
        secret = os.environ.get("NEBIUS_API_KEY", "").strip()
        if secret:
            return secret, "environment:NEBIUS_API_KEY"
    return "", "unavailable"


# ----------------------------------------------------------------------
# Telemetry Sanitizer
# ----------------------------------------------------------------------

class NebiusResponseError(ValueError):
    """Provider replied, but did not supply a usable diagnostic JSON object."""

    def __init__(self, code: str, receipt: Dict[str, Any]) -> None:
        super().__init__(code)
        self.receipt = {**receipt, "evidence_mode": "BLOCKED", "status": code}


class TelemetrySanitizer:
    """Sanitizes sensitive customer infrastructure metadata before external reasoning."""

    # Words to redact or mask
    SENSITIVE_NAMES = [
        "bellini", "torre bellini", "danzasjazz", "ecuador", "guayaquil",
        "rafael", "lopez", "innerchispa"
    ]
    SENSITIVE_KEYS = {
        "access_key", "api_key", "authorization", "cookie", "credential",
        "imei", "password", "private_key", "secret", "serial",
        "serial_number", "session", "token",
    }

    @classmethod
    def _redact_sensitive_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            clean: Dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in cls.SENSITIVE_KEYS or any(
                    marker in normalized
                    for marker in ("password", "secret", "token", "private_key", "api_key")
                ):
                    clean[str(key)] = "[REDACTED]"
                else:
                    clean[str(key)] = cls._redact_sensitive_fields(item)
            return clean
        if isinstance(value, list):
            return [cls._redact_sensitive_fields(item) for item in value]
        if isinstance(value, tuple):
            return [cls._redact_sensitive_fields(item) for item in value]
        return value

    @classmethod
    def sanitize(cls, raw_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Sanitize payload and return (sanitized_payload, deobfuscation_map)."""
        mapping: Dict[str, str] = {}
        ip_counter = 1
        mac_counter = 1

        raw_str = json.dumps(cls._redact_sensitive_fields(raw_data))

        # 1. Mask private IPv4 addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
        ip_pattern = re.compile(r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b')
        for match in set(ip_pattern.findall(raw_str)):
            anon_ip = f"10.0.0.{ip_counter}"
            mapping[anon_ip] = match
            raw_str = raw_str.replace(match, anon_ip)
            ip_counter += 1

        # 2. Mask MAC addresses (XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX)
        mac_pattern = re.compile(r'\b(?:[0-9A-Fa-f]{2}[:-]){5}(?:[0-9A-Fa-f]{2})\b')
        for match in set(mac_pattern.findall(raw_str)):
            anon_mac = f"02:00:00:00:00:{mac_counter:02X}"
            mapping[anon_mac] = match
            raw_str = raw_str.replace(match, anon_mac)
            mac_counter += 1

        # 3. Anonymize known customer / tenant names
        for word in cls.SENSITIVE_NAMES:
            raw_str = re.sub(re.escape(word), "Site-Alpha-01", raw_str, flags=re.IGNORECASE)

        # 4. Remove common bearer/basic credential fragments from free text.
        raw_str = re.sub(
            r"(?i)(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
            r"\1 [REDACTED]",
            raw_str,
        )

        sanitized_dict = json.loads(raw_str)
        return sanitized_dict, mapping


# ----------------------------------------------------------------------
# Nebius × NVIDIA Reasoning Adapter
# ----------------------------------------------------------------------

class NebiusNvidiaReasoning:
    """Reasoning engine bridging Nebius NVIDIA models with local InnerOS execution."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        local_base_url: Optional[str] = None,
        local_model: Optional[str] = None,
        timeout_seconds: float = 8.0,
        max_output_tokens: int = 512,
    ) -> None:
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self.base_url = (base_url or os.environ.get("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE_URL)).rstrip("/")
        self.model = model or os.environ.get("NEBIUS_NVIDIA_MODEL", DEFAULT_NEBIUS_MODEL)
        self.local_base_url = (local_base_url or os.environ.get("LOCAL_MODEL_URL", DEFAULT_LOCAL_BASE_URL)).rstrip("/")
        self.local_model = local_model or os.environ.get("LOCAL_MODEL_NAME", DEFAULT_LOCAL_MODEL)
        self.timeout_seconds = timeout_seconds
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 2048:
            raise ValueError("max_output_tokens_must_be_between_1_and_2048")
        self.max_output_tokens = max_output_tokens

    def _build_prompt(self, sanitized_telemetry: Dict[str, Any]) -> str:
        return (
            "You are the InnerOS Infrastructure Guardian Physical AI diagnostic engine.\n"
            "Analyze the following sanitized network telemetry and diagnostic state:\n"
            f"{json.dumps(sanitized_telemetry, indent=2)}\n\n"
            "Provide an operational diagnosis and recommendation. "
            "You must return ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "root_cause": "description of identified fault",\n'
            '  "severity": "low" | "medium" | "high" | "critical",\n'
            '  "impact": "description of client impact",\n'
            '  "recommended_action": "reboot" | "poe_cycle" | "none",\n'
            '  "recommended_capability": "network.device.reboot.v1" | "network.device.poe_cycle.v1" | "none",\n'
            '  "target_device_ref": "identifier of device needing intervention",\n'
            '  "target_port": 1,\n'
            '  "requires_approval": true,\n'
            '  "confidence": 0.95,\n'
            '  "rationale": "clear justification for action",\n'
            '  "verification_plan": {\n'
            '    "capability_id": "network.device.verify_recovery.v1",\n'
            '    "expected_status": "online"\n'
            '  }\n'
            "}\n"
        )

    @staticmethod
    def is_nvidia_open_model(model_id: str) -> bool:
        """Return whether an API model identifier is explicitly NVIDIA/Nemotron."""
        normalized = str(model_id or "").strip().lower()
        return normalized.startswith("nvidia/") or "nemotron" in normalized

    def list_models(self) -> List[str]:
        """Return live Token Factory model IDs without exposing credentials."""
        if not self.api_key:
            raise ValueError("NEBIUS_API_KEY is not configured")
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Token Factory /models returned an invalid payload")
        return sorted(
            str(row.get("id") or "").strip()
            for row in rows
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        )

    def resolve_live_nvidia_model(self) -> str:
        """Validate/select an NVIDIA model against the authenticated live catalog."""
        available = self.list_models()
        if self.model:
            if not self.is_nvidia_open_model(self.model):
                raise ValueError("configured_model_is_not_explicitly_nvidia")
            if self.model not in available:
                raise ValueError("configured_nvidia_model_not_in_live_catalog")
            return self.model
        candidates = [model_id for model_id in available if self.is_nvidia_open_model(model_id)]
        if not candidates:
            raise ValueError("no_nvidia_model_in_live_catalog")
        self.model = candidates[0]
        return self.model

    def _call_nebius_api(self, prompt: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Call Token Factory and return diagnosis plus a sanitized provider receipt."""
        if not self.api_key:
            raise ValueError("NEBIUS_API_KEY is not configured")
        if not self.model:
            raise ValueError("NEBIUS_NVIDIA_MODEL is not configured or validated")
        if not self.is_nvidia_open_model(self.model):
            raise ValueError("configured_model_is_not_explicitly_nvidia")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a Physical AI network diagnostic engine."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            response_id = str(data.get("id") or "")
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            receipt_seed = json.dumps(
                {
                    "response_id": response_id,
                    "model": self.model,
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "usage": usage,
                },
                sort_keys=True,
            )
            receipt = {
                "evidence_mode": "REAL",
                "provider": "nebius_token_factory",
                "base_url": self.base_url,
                "model": self.model,
                "response_id": response_id or None,
                "usage": usage,
                "receipt_sha256": hashlib.sha256(receipt_seed.encode("utf-8")).hexdigest(),
                "received_at": _now(),
            }
            choices = data.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            if not isinstance(choice, dict):
                raise NebiusResponseError("INVALID_RESPONSE_CHOICES", receipt)
            finish_reason = choice.get("finish_reason")
            receipt["finish_reason"] = (
                finish_reason if finish_reason in ("stop", "length", "content_filter", "tool_calls")
                else "other"
            )
            message = choice.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if finish_reason == "length":
                raise NebiusResponseError("OUTPUT_TOKEN_LIMIT_REACHED", receipt)
            if not isinstance(content, str) or not content.strip():
                raise NebiusResponseError("EMPTY_DIAGNOSTIC_CONTENT", receipt)
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                raise NebiusResponseError("INVALID_DIAGNOSTIC_JSON", receipt) from None
            if not isinstance(parsed, dict):
                raise NebiusResponseError("INVALID_DIAGNOSTIC_OBJECT", receipt)
            return parsed, receipt

    def _fallback_local_reasoning(self, sanitized_telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic local fallback reasoning when external AI Cloud is unreachable."""
        # Analyze telemetry rules
        device_ref = sanitized_telemetry.get("device_ref") or "device_01"
        offline = sanitized_telemetry.get("offline", False)
        high_latency = sanitized_telemetry.get("latency_ms", 0) > 100
        memory_pressure = sanitized_telemetry.get("memory_utilization", 0) > 85
        poe_hung = sanitized_telemetry.get("poe_hung", False)

        if poe_hung:
            return {
                "root_cause": "PoE device controller frozen / unresponsive on bus",
                "severity": "critical",
                "impact": "Attached physical device unresponsive and unpingable",
                "recommended_action": "poe_cycle",
                "recommended_capability": "network.device.poe_cycle.v1",
                "target_device_ref": str(device_ref),
                "target_port": sanitized_telemetry.get("port", 1),
                "requires_approval": True,
                "confidence": 0.94,
                "rationale": "Hardware watchdog frozen; hard PoE power cut required to trigger cold boot.",
                "verification_plan": {
                    "capability_id": "network.device.verify_recovery.v1",
                    "expected_status": "online",
                },
            }
        elif offline or memory_pressure or high_latency:
            return {
                "root_cause": "Access Point buffer bloat / memory pressure",
                "severity": "high",
                "impact": "Clients experiencing frame drops and intermittent disconnects",
                "recommended_action": "reboot",
                "recommended_capability": "network.device.reboot.v1",
                "target_device_ref": str(device_ref),
                "target_port": None,
                "requires_approval": True,
                "confidence": 0.91,
                "rationale": "Soft reboot will clear saturated buffers and restart radio interfaces.",
                "verification_plan": {
                    "capability_id": "network.device.verify_recovery.v1",
                    "expected_status": "online",
                },
            }
        else:
            return {
                "root_cause": "Normal operating parameters",
                "severity": "low",
                "impact": "No active client degradation",
                "recommended_action": "none",
                "recommended_capability": "none",
                "target_device_ref": str(device_ref),
                "target_port": None,
                "requires_approval": False,
                "confidence": 0.98,
                "rationale": "Infrastructure telemetry healthy; no intervention needed.",
                "verification_plan": {
                    "capability_id": "network.device.verify_recovery.v1",
                    "expected_status": "online",
                },
            }

    def diagnose(
        self,
        telemetry: Dict[str, Any],
        force_local: bool = False,
    ) -> Dict[str, Any]:
        """Diagnose network state, sanitizing inputs and using Nebius or local fallback."""
        sanitized, mapping = TelemetrySanitizer.sanitize(telemetry)
        prompt = self._build_prompt(sanitized)

        used_provider = "nebius_token_factory"
        used_model = self.model
        parsed: Dict[str, Any] = {}
        error_detail: Optional[str] = None
        provider_receipt: Dict[str, Any] = {
            "evidence_mode": "NOT_RUN",
            "provider": "nebius_token_factory",
            "status": "NOT_REQUESTED",
        }

        if not force_local and self.api_key and self.model:
            try:
                parsed, provider_receipt = self._call_nebius_api(prompt)
            except Exception as exc:
                used_provider = "local_heuristic"
                used_model = self.local_model
                error_detail = f"Token Factory call failed: {type(exc).__name__}; local heuristic used"
                provider_receipt = {
                    "evidence_mode": "BLOCKED",
                    "provider": "nebius_token_factory",
                    "status": "REMOTE_INFERENCE_FAILED",
                    "error_type": type(exc).__name__,
                }
                if isinstance(exc, NebiusResponseError):
                    provider_receipt = {**exc.receipt, "error_type": type(exc).__name__}
                parsed = self._fallback_local_reasoning(sanitized)
        else:
            used_provider = "local_heuristic"
            used_model = self.local_model
            provider_receipt = {
                "evidence_mode": "NOT_RUN",
                "provider": "nebius_token_factory",
                "status": (
                    "FORCE_LOCAL" if force_local
                    else "MISSING_API_KEY" if not self.api_key
                    else "MISSING_VALIDATED_NVIDIA_MODEL"
                ),
            }
            parsed = self._fallback_local_reasoning(sanitized)

        return {
            "ok": True,
            "provider": used_provider,
            "model": used_model,
            "inference_mode": "REAL" if used_provider == "nebius_token_factory" else "LOCAL_HEURISTIC",
            "fallback_engaged": (used_provider == "local_heuristic"),
            "fallback_reason": error_detail,
            "diagnosis": parsed,
            "sanitized_inputs": sanitized,
            "sanitization": {
                "private_identifiers_replaced": len(mapping),
                "deobfuscation_map_exposed": False,
            },
            "provider_receipt": provider_receipt,
            "timestamp": _now(),
        }


# ----------------------------------------------------------------------
# Bounded 7-step Physical AI Workflow Runner
# ----------------------------------------------------------------------

def run_physical_ai_workflow(
    device_ref: str,
    site_id: str = "home_pcdoctor_lab",
    client_id: str = "pcdoctor_lab",
    provider: str = "unifi",
    symptoms: Optional[Dict[str, Any]] = None,
    owner_approved: bool = False,
    approval_token: Optional[str] = None,
    dry_run: bool = True,
    reasoning_adapter: Optional[NebiusNvidiaReasoning] = None,
) -> Dict[str, Any]:
    """Execute the canonical 7-stage InnerOS Physical AI Workflow:

    1. Discover  -> Query physical device state via capability_gateway
    2. Diagnose  -> Sanitize and analyze via Nebius NVIDIA reasoning adapter
    3. Recommend -> Formulate bounded action (reboot or poe_cycle)
    4. Policy    -> Gate live execution behind explicit owner authorization
    5. Execute   -> Dispatch action locally through Capability Gateway
    6. Verify    -> Validate physical connectivity and recovery
    7. Receipt   -> Generate audit provenance evidence receipt
    """
    from inneros_core_runtime.capability_gateway import capability_invoke

    workflow_id = f"wf_phys_{uuid.uuid4().hex[:12]}"
    started_at = _now()
    step_trail: List[Dict[str, Any]] = []

    # Stage 1: Discover
    query_params = {
        "tenant_id": client_id,
        "site_id": site_id,
        "device_ref": device_ref,
        "sections": ["health", "inventory"],
    }
    discovery_res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters=query_params,
    )
    step_trail.append({"stage": "1_discover", "ok": discovery_res.get("ok"), "output": discovery_res})

    # Combine discovered data with observed symptoms
    diag_telemetry = {
        "device_ref": device_ref,
        "site_id": site_id,
        "tenant_id": client_id,
        "provider": provider,
        **(symptoms or {"offline": True, "latency_ms": 150, "memory_utilization": 92}),
    }

    # Stage 2: Diagnose via Nebius / NVIDIA open model
    reasoner = reasoning_adapter or NebiusNvidiaReasoning()
    diag_result = reasoner.diagnose(diag_telemetry)
    step_trail.append({
        "stage": "2_diagnose",
        "provider": diag_result.get("provider"),
        "model": diag_result.get("model"),
        "diagnosis": diag_result.get("diagnosis"),
    })

    rec = diag_result.get("diagnosis", {})
    action = rec.get("recommended_action", "none")
    cap_id = rec.get("recommended_capability", "none")

    # Stage 3: Recommend
    step_trail.append({
        "stage": "3_recommend",
        "action": action,
        "capability": cap_id,
        "requires_approval": rec.get("requires_approval", True),
        "confidence": rec.get("confidence", 0.0),
    })

    # Stage 4: Policy & Approval Gate
    approved = owner_approved or bool(approval_token)
    blocked_by_policy = (not dry_run) and (not approved)
    step_trail.append({
        "stage": "4_policy_check",
        "dry_run": dry_run,
        "approved": approved,
        "blocked": blocked_by_policy,
    })

    if blocked_by_policy:
        return {
            "ok": False,
            "workflow_id": workflow_id,
            "status": "BLOCKED_BY_POLICY",
            "error": "approval_required",
            "message": "Live execution of physical action requires explicit owner authorization.",
            "workflow_steps": step_trail,
            "started_at": started_at,
            "completed_at": _now(),
        }

    # Stage 5: Execute Locally via Capability Gateway
    exec_res: Dict[str, Any] = {}
    if cap_id in ("network.device.reboot.v1", "network.device.poe_cycle.v1"):
        exec_params: Dict[str, Any] = {
            "device_ref": device_ref,
            "switch_ref": device_ref,
            "provider": provider,
            "dry_run": dry_run,
            "tenant_id": client_id,
            "site_id": site_id,
            "approval_token": approval_token or ("owner_approved" if approved else ""),
            "owner_approved": approved,
        }
        if cap_id == "network.device.poe_cycle.v1":
            exec_params["port"] = rec.get("target_port") or 1

        exec_res = capability_invoke(
            capability_id=cap_id,
            parameters=exec_params,
            context={"owner_approved": approved},
        )
        step_trail.append({"stage": "5_execute_locally", "ok": exec_res.get("ok"), "output": exec_res})
    else:
        step_trail.append({"stage": "5_execute_locally", "skipped": True, "reason": "No action required"})

    # Stage 6: Verify Recovery.  Dry-runs may simulate the probe, but simulated
    # evidence is never promoted to a real recovery claim.
    verify_res = capability_invoke(
        capability_id="network.device.verify_recovery.v1",
        parameters={
            "device_ref": device_ref,
            "provider": provider,
            "expected_status": "online",
            "mock_probe": dry_run,
        },
    )
    step_trail.append({"stage": "6_verify_recovery", "ok": verify_res.get("ok"), "output": verify_res})

    # Stage 7: Evidence Receipt
    completed_at = _now()
    exec_payload = exec_res.get("result", {}) if isinstance(exec_res, dict) else {}
    verify_payload = verify_res.get("result", {}) if isinstance(verify_res, dict) else {}
    verification_mode = str(verify_payload.get("verification_mode") or "NOT_VERIFIED")
    real_recovery_verified = bool(
        verification_mode == "REAL" and verify_payload.get("recovered") is True
    )
    action_status = str(exec_payload.get("status") or "NO_ACTION")
    workflow_ok = bool(exec_res.get("ok", True)) and (dry_run or real_recovery_verified)
    workflow_status = (
        "COMPLETED_DRY_RUN" if dry_run and exec_res.get("ok", True)
        else "COMPLETED_VERIFIED" if workflow_ok
        else "FAILED_CLOSED"
    )
    receipt = {
        "workflow_id": workflow_id,
        "thesis": "Cloud intelligence. Local authority. Verified physical actions.",
        "intelligence": {
            "reasoning_provider": diag_result.get("provider"),
            "reasoning_model": diag_result.get("model"),
            "inference_mode": diag_result.get("inference_mode"),
            "fallback_engaged": diag_result.get("fallback_engaged"),
            "provider_receipt": diag_result.get("provider_receipt"),
        },
        "authority": {
            "execution_plane": "InnerOS Local Capability Gateway",
            "policy": "OWNER_APPROVAL_REQUIRED_FOR_LIVE_MUTATIONS",
            "approved": approved,
            "dry_run": dry_run,
        },
        "action": {
            "capability_id": cap_id,
            "target": device_ref,
            "status": action_status,
            "mutation_applied": bool(exec_payload.get("mutation_applied", False)),
            "evidence_mode": "SIMULATED" if dry_run else "REAL",
        },
        "verification": {
            "verification_mode": verification_mode,
            "real_recovery_verified": real_recovery_verified,
            "recovered": verify_payload.get("recovered") if verification_mode == "REAL" else None,
            "simulated_outcome": (
                bool(verify_payload.get("recovered")) if verification_mode == "SIMULATED" else None
            ),
            "state": verify_payload.get("current_status"),
        },
        "timeline": {
            "started_at": started_at,
            "completed_at": completed_at,
        },
    }
    step_trail.append({"stage": "7_evidence_receipt", "receipt": receipt})

    return {
        "ok": workflow_ok,
        "workflow_id": workflow_id,
        "status": workflow_status,
        "dry_run": dry_run,
        "stages_executed": len(step_trail),
        "evidence_receipt": receipt,
        "workflow_trail": step_trail,
    }
