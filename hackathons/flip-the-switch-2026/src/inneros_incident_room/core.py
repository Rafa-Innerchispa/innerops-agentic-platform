"""Pure-Python synthetic incident domain model, not a production executor.

This package is pre-existing/reusable preparation. It MUST NOT control devices.
Switch-specific integration and the actual competition workflow belong in the
hackathon-period commit series, not this preparatory package.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable
import json
from typing import Literal


class PolicyDenied(Exception):
    """A mutation is unsafe or lacks correctly scoped human approval."""


@dataclass(frozen=True)
class Incident:
    incident_id: str
    site_alias: str
    symptom: str
    device_alias: str
    source: Literal["synthetic"]
    observed_at: str


@dataclass(frozen=True)
class Action:
    incident_id: str
    action_id: str
    target_alias: str
    operation: Literal["observe", "simulate_restart"]
    scope: Literal["synthetic_fixture"]
    reason: str


@dataclass(frozen=True)
class HumanApproval:
    action_id: str
    target_alias: str
    actor: str
    approved: bool


@dataclass(frozen=True)
class ExecutionReceipt:
    incident_id: str
    action_id: str
    source: str
    requested_operation: str
    outcome: str
    approval: str
    pre_state: str
    post_state: str
    independent_verification: bool
    evidence_sha256: str


def canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_incident(incident: Incident) -> None:
    if incident.source != "synthetic":
        raise PolicyDenied("Only synthetic incidents are supported by this offline package")
    if not incident.incident_id.strip() or not incident.device_alias.strip():
        raise ValueError("Incident ID and device alias are required")
    datetime.fromisoformat(incident.observed_at.replace("Z", "+00:00"))


def propose_actions(incident: Incident) -> list[Action]:
    """Deterministic proposals, no model inference and no live I/O."""
    validate_incident(incident)
    return [
        Action(incident.incident_id, f"{incident.incident_id}-observe", incident.device_alias,
               "observe", "synthetic_fixture", "Collect state before any change"),
        Action(incident.incident_id, f"{incident.incident_id}-simulate", incident.device_alias,
               "simulate_restart", "synthetic_fixture", "Demonstrate a gated remediation"),
    ]


def enforce(action: Action, incident: Incident, approval: HumanApproval | None = None) -> None:
    validate_incident(incident)
    if action.scope != "synthetic_fixture" or action.incident_id != incident.incident_id:
        raise PolicyDenied("Action outside the authorized synthetic incident scope")
    if action.target_alias != incident.device_alias:
        raise PolicyDenied("Target mismatch")
    if action.operation not in {"observe", "simulate_restart"}:
        raise PolicyDenied("Operation not allowlisted")
    if action.operation != "observe":
        if approval is None or not approval.approved:
            raise PolicyDenied("Human approval required")
        if not approval.actor.strip() or approval.action_id != action.action_id:
            raise PolicyDenied("Approval identity or action mismatch")
        if approval.target_alias != action.target_alias:
            raise PolicyDenied("Approval target mismatch")


def execute_fixture(action: Action, incident: Incident, state: dict,
                    approval: HumanApproval | None = None, *,
                    readback: Callable[[str], str] | None = None) -> ExecutionReceipt:
    """Mutates *only* the caller-provided in-memory fixture after policy checks.

    A caller may inject an independent *synthetic* readback for failure tests.
    Default readback observes the same in-memory fixture; that is NOT
    independent physical-device evidence. Never pass real device SDK objects
    or credentials as `state`. HumanApproval is synthetic data, not proof of
    an authenticated human identity.
    """
    enforce(action, incident, approval)
    before = state.get(action.target_alias, "unknown")
    if action.operation == "simulate_restart":
        if before != "degraded":
            raise PolicyDenied("Synthetic restart only permitted from degraded")
        state[action.target_alias] = "healthy"
    try:
        after = (readback(action.target_alias) if readback is not None
                 else state.get(action.target_alias, "unknown"))
    except Exception:
        # Synthetic actuator may have changed state, but cannot claim success.
        after = "readback_unavailable"
    verified = (after == "healthy" if action.operation == "simulate_restart" else after == before)
    outcome = "verified_simulation" if verified else "unverified"
    evidence = {
        "incident_id": incident.incident_id,
        "action_id": action.action_id,
        "source": "synthetic",
        "operation": action.operation,
        "scope": action.scope,
        "approval": approval.actor if approval else "not_required",
        "pre_state": before,
        "post_state": after,
        "outcome": outcome,
        "independent_verification": verified,
    }
    # A digest identifies data; a plain hash is NOT a signed, tamper-proof audit trail.
    digest = sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
    return ExecutionReceipt(incident.incident_id, action.action_id, "synthetic",
                            action.operation, outcome, evidence["approval"], before,
                            after, verified, digest)


def load_incident_dict(raw: dict) -> Incident:
    incident = Incident(**raw)
    validate_incident(incident)
    return incident


def receipt_as_dict(receipt: ExecutionReceipt) -> dict:
    return asdict(receipt)
