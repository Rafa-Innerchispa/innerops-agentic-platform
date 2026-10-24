"""Sanitized frontend contract for the Nebius × NVIDIA Guardian.

These routes never perform an unapproved mutation.  Action planning is forced
to dry-run; real execution remains in the governed capability plane.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from inneros_core_runtime.capability_gateway import capability_invoke
from inneros_core_runtime.nebius_nvidia_reasoning import (
    NebiusNvidiaReasoning,
    TelemetrySanitizer,
    load_nebius_api_key_from_vault,
)


router = APIRouter(prefix="/api/guardian", tags=["guardian"])
_EVIDENCE: dict[str, dict[str, Any]] = {}
_MAX_EVIDENCE = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(value: dict[str, Any]) -> dict[str, Any]:
    sanitized, _mapping = TelemetrySanitizer.sanitize(value)
    return sanitized


def _record(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    evidence_id = f"evidence_{uuid.uuid4().hex[:16]}"
    row = _public({
        "evidence_id": evidence_id,
        "kind": kind,
        "created_at": _now(),
        "payload": payload,
    })
    _EVIDENCE[evidence_id] = row
    while len(_EVIDENCE) > _MAX_EVIDENCE:
        _EVIDENCE.pop(next(iter(_EVIDENCE)))
    return row


@router.get("/overview")
def guardian_overview() -> dict[str, Any]:
    return {
        "ok": True,
        "contract_version": "guardian.v1",
        "execution_policy": "DRY_RUN_PLANNING_ONLY",
        "external_inference_policy": "VAULT_KEY_AND_EXPLICIT_CREDIT_AUTHORIZATION_REQUIRED",
        "evidence_modes": ["REAL", "SIMULATED", "BLOCKED", "NOT_RUN"],
        "capabilities": [
            "network.device.reboot.v1",
            "network.device.poe_cycle.v1",
            "network.device.verify_recovery.v1",
        ],
        "routes": [
            "GET /api/guardian/overview",
            "POST /api/guardian/diagnose",
            "POST /api/guardian/actions/plan",
            "POST /api/guardian/recovery/verify",
            "GET /api/guardian/evidence/{id}",
        ],
    }


@router.post("/diagnose")
def guardian_diagnose(body: dict[str, Any]) -> dict[str, Any]:
    telemetry = body.get("telemetry")
    if not isinstance(telemetry, dict):
        raise HTTPException(status_code=422, detail="telemetry_object_required")
    live_requested = body.get("inference_mode") == "REAL"
    live_authorized = os.environ.get("NEBIUS_LIVE_SMOKE_AUTHORIZED", "").strip() == "1"
    api_key = ""
    credential_source = "unavailable"
    if live_requested and live_authorized:
        api_key, credential_source = load_nebius_api_key_from_vault()
    if live_requested and (not live_authorized or not api_key):
        blocked = _record("diagnosis", {
            "ok": False,
            "evidence_mode": "BLOCKED",
            "error": "live_inference_not_authorized_or_vault_key_missing",
        })
        raise HTTPException(status_code=409, detail=blocked)

    reasoner = NebiusNvidiaReasoning(
        api_key=api_key,
        model=str(body.get("model") or os.environ.get("NEBIUS_NVIDIA_MODEL", "")).strip(),
    )
    if live_requested:
        reasoner.resolve_live_nvidia_model()
    result = reasoner.diagnose(telemetry, force_local=not live_requested)
    result["credential_source"] = credential_source if live_requested else "not_used"
    evidence = _record("diagnosis", result)
    return {"ok": True, "evidence_id": evidence["evidence_id"], "result": evidence["payload"]}


@router.post("/actions/plan")
def guardian_plan_action(body: dict[str, Any]) -> dict[str, Any]:
    capability_id = str(body.get("capability_id") or "").strip()
    allowed = {"network.device.reboot.v1", "network.device.poe_cycle.v1"}
    if capability_id not in allowed:
        raise HTTPException(status_code=422, detail="unsupported_plan_capability")
    parameters = dict(body.get("parameters") or {})
    parameters["dry_run"] = True
    parameters.pop("approval_token", None)
    parameters.pop("owner_approval_ref", None)
    result = capability_invoke(capability_id=capability_id, parameters=parameters)
    evidence = _record("action_plan", result)
    return {"ok": result.get("ok", False), "evidence_id": evidence["evidence_id"], "result": evidence["payload"]}


@router.post("/recovery/verify")
def guardian_verify_recovery(body: dict[str, Any]) -> dict[str, Any]:
    parameters = {
        "device_ref": str(body.get("device_ref") or "").strip(),
        "provider": str(body.get("provider") or "device_fabric").strip(),
        "expected_status": str(body.get("expected_status") or "online").strip(),
        "mock_probe": bool(body.get("simulation", False)),
    }
    result = capability_invoke(
        capability_id="network.device.verify_recovery.v1",
        parameters=parameters,
    )
    evidence = _record("recovery_verification", result)
    return {"ok": result.get("ok", False), "evidence_id": evidence["evidence_id"], "result": evidence["payload"]}


@router.get("/evidence/{evidence_id}")
def guardian_evidence(evidence_id: str) -> dict[str, Any]:
    row = _EVIDENCE.get(evidence_id)
    if row is None:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    return {"ok": True, "evidence": row}
