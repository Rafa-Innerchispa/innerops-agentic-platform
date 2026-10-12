"""Admission contract: ACK != claim, owner authorization must be durable."""
from inneros_core_runtime.ops_auto_claim_admission import claim_admission, pending_admission_summary


def _task(**overrides):
    t = {"task_id": "ops_123", "status": "awaiting_cursor_claim",
         "assignee": "cursor", "owner_authorized_at": "2026-10-12T20:00:00Z"}
    t.update(overrides)
    return t


def test_authorized_cursor_ready():
    assert claim_admission(_task(), provider="cursor", ready=True)["eligible"]


def test_missing_key_blocks_without_claim():
    result = claim_admission(_task(), provider="cursor", ready=False, not_ready_reason="cursor_api_key_missing")
    assert not result["eligible"]
    assert result["reason"] == "cursor_api_key_missing"


def test_payload_cannot_forge_owner_grant():
    row = _task(owner_authorized_at=None, payload={"owner_approved": True})
    assert claim_admission(row, provider="cursor", ready=True)["reason"] == "owner_authorization_not_recorded"


def test_no_reclaim_of_active_or_foreign_task():
    assert claim_admission(_task(status="in_progress", claim_token="original"), provider="cursor", ready=True)["reason"] == "already_claimed"
    assert claim_admission(_task(), provider="codex", ready=True)["reason"] == "different_assignee"


def test_manual_tasks_are_never_auto_claimed():
    assert claim_admission(_task(do_not_auto_dispatch=True), provider="cursor", ready=True)["reason"] == "manual_dispatch_only"


def test_internal_dev_swarm_proposed_only():
    row = {"task_id": "x", "assignee": "dev_swarm", "status": "proposed"}
    assert claim_admission(row, provider="dev_swarm", ready=True)["eligible"]
    assert claim_admission({**row, "status": "queued"}, provider="dev_swarm", ready=True)["reason"] == "internal_task_not_proposed"


def test_provider_agnostic_external_ide():
    row = {"task_id": "x", "assignee": "antigravity", "status": "awaiting_antigravity_claim",
           "owner_authorized_at": "2026-10-12T20:00:00Z"}
    assert claim_admission(row, provider="antigravity", ready=True)["eligible"]


def test_aggregated_blocker_report():
    rows = [_task(), _task(task_id="ops_456", owner_authorized_at=None)]
    report = pending_admission_summary(rows, provider="cursor", ready=False, not_ready_reason="cursor_api_key_missing")
    assert report["reasons"]["cursor_api_key_missing"] == 1
    assert report["reasons"]["owner_authorization_not_recorded"] == 1
