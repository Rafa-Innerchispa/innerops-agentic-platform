from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from inneros_core_runtime import ops_interactive_recovery as oir
from inneros_core_runtime import ops_awaiting_claim as oac


def test_expired_interactive_claim_is_recovered():
    """An interactive ops task with an expired lease_until must be recovered, even if claim_token is set."""
    past_lease = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    task = {
        "task_id": "ops_stale_claim_probe",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claim_token": "token_stale_12345",
        "lease_until": past_lease,
        "claimed_at": past_lease,
        "claimed_by": "antigravity",
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col

    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    # Must find and recover the expired claim
    assert res["ok"] is True
    assert len(res["recovered"]) == 1
    assert res["recovered"][0]["task_id"] == "ops_stale_claim_probe"
    assert res["recovered"][0]["status"] == "awaiting_antigravity_claim"

    # Verify CAS update removed the expired token and reset claim metadata
    mock_col.update_one.assert_called_once()
    filter_arg, update_arg = mock_col.update_one.call_args[0]
    assert filter_arg["task_id"] == "ops_stale_claim_probe"
    assert update_arg["$set"]["status"] == "awaiting_antigravity_claim"
    assert "claim_token" in update_arg["$unset"]
    assert "lease_until" in update_arg["$unset"]
    assert "claimed_at" in update_arg["$unset"]


def test_active_valid_lease_is_never_recovered():
    """An active claim with valid lease_until in the future must never be recovered."""
    future_lease = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
    task = {
        "task_id": "ops_active_live_worker",
        "status": "claimed",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "cursor",
        "execution_lane": "cursor_interactive",
        "claim_token": "valid_token_live",
        "lease_until": future_lease,
        "claimed_at": (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
        "claimed_by": "cursor",
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_db.__getitem__.return_value = mock_col

    mock_col.find.return_value.sort.return_value.limit.return_value = [task]

    with patch.object(oir.mongo_store, "get_db", return_value=mock_db):
        res = oir.recover_orphan_interactive_ops_tasks(limit=10)

    assert res["ok"] is True
    assert len(res["recovered"]) == 0
    mock_col.update_one.assert_not_called()


def test_awaiting_claim_precedence_for_orchestrated_tasks():
    """Verify provider awaiting resolution for orchestrated tasks."""
    t_anti = {
        "task_id": "ops_orch_1",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
    }
    assert oac.awaiting_claim_status_for_task(t_anti) == "awaiting_antigravity_claim"

    t_cur = {
        "task_id": "ops_orch_2",
        "assignee": "inneros_orchestrator",
        "claimed_by": "cursor",
    }
    assert oac.awaiting_claim_status_for_task(t_cur) == "awaiting_cursor_claim"

    t_codex = {
        "task_id": "ops_orch_3",
        "assignee": "dev_swarm",
        "execution_lane": "codex_interactive",
    }
    assert oac.awaiting_claim_status_for_task(t_codex) == "awaiting_codex_claim"

    t_direct = {
        "task_id": "ops_orch_4",
        "assignee": "antigravity",
    }
    assert oac.awaiting_claim_status_for_task(t_direct) == "awaiting_antigravity_claim"
