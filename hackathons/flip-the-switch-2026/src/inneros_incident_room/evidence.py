"""Event-neutral checksum verification for synthetic evidence receipts.

This verifier recomputes the receipt checksum. It is NOT a signature,
nonrepudiation, an authenticated approval, or a substitute for live readback.
"""
from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest

from .core import ExecutionReceipt, canonical_json


def verify_receipt_integrity(receipt: ExecutionReceipt) -> bool:
    """Check whether a synthetic receipt was altered since its digest was made."""
    if receipt.source != "synthetic" or len(receipt.evidence_sha256) != 64:
        return False
    evidence = {
        "incident_id": receipt.incident_id,
        "action_id": receipt.action_id,
        "source": "synthetic",
        "operation": receipt.requested_operation,
        "scope": "synthetic_fixture",
        "approval": receipt.approval,
        "pre_state": receipt.pre_state,
        "post_state": receipt.post_state,
        "outcome": receipt.outcome,
        "independent_verification": receipt.independent_verification,
    }
    digest = sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
    return compare_digest(digest, receipt.evidence_sha256)
