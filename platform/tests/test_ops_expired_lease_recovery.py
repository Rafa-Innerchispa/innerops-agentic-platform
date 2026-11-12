from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from inneros_core_runtime.ops_interactive_recovery import recover_expired_lease_interactive_ops_tasks


def _mock_db(rows):
    col = MagicMock()
    col.find.return_value.sort.return_value.limit.return_value = rows
    db = MagicMock()
    db.__getitem__.return_value = col
    return db, col


def _claimed_task(**over):
    task = {
        "task_id": "ops_expired1",
        "status": "claimed",
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
        "claimed_by": "antigravity",
        "claim_token": "tok_expired",
        "claim_host": "ralphi-ia-ver-10",
        "lease_until": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    task.update(over)
    return task


def test_expired_lease_with_token_is_recovered() -> None:
    db, col = _mock_db([_claimed_task()])
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["ok"] is True
    assert out["scanned"] == 1
    assert out["recovered"] == [{"task_id": "ops_expired1", "status": "awaiting_antigravity_claim"}]
    filt, doc = col.update_one.call_args.args
    assert filt == {"task_id": "ops_expired1", "claim_token": "tok_expired", "lease_until": "2026-01-01T00:00:00+00:00"}
    assert doc["$set"]["status"] == "awaiting_antigravity_claim"
    assert doc["$set"]["claim_error"] == "expired_lease_recovered"
    assert doc["$set"]["recovered_from_status"] == "claimed"
    for field in ("claim_token", "claimed_by", "lease_until", "claim_host"):
        assert field in doc["$unset"]


def test_valid_lease_is_never_recovered() -> None:
    db, col = _mock_db([_claimed_task(lease_until="2030-01-01T00:00:00+00:00")])
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["recovered"] == []
    col.update_one.assert_not_called()


def test_lease_inside_grace_is_never_recovered() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    db, col = _mock_db([_claimed_task(lease_until=recent)])
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks(grace_seconds=300)

    assert out["recovered"] == []
    col.update_one.assert_not_called()


def test_task_without_token_is_not_touched() -> None:
    db, col = _mock_db([_claimed_task(claim_token="")])
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["recovered"] == []
    col.update_one.assert_not_called()


def test_non_interactive_lane_is_not_recovered() -> None:
    db, col = _mock_db(
        [_claimed_task(execution_lane="local_dev_swarm", assignee="dev_swarm", preferred_provider="dev_swarm")]
    )
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["recovered"] == []
    col.update_one.assert_not_called()


def test_lost_cas_race_is_not_reported_recovered() -> None:
    db, col = _mock_db([_claimed_task(lease_until="2026-01-01T00:00:00Z")])
    col.update_one.return_value = MagicMock(matched_count=0)
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["scanned"] == 1
    assert out["recovered"] == []
    filt = col.update_one.call_args.args[0]
    assert filt["lease_until"] == "2026-01-01T00:00:00Z"


def test_execution_stop_is_respected() -> None:
    db, col = _mock_db([_claimed_task(execution_stop=True)])
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = recover_expired_lease_interactive_ops_tasks()

    assert out["recovered"] == []
    col.update_one.assert_not_called()
