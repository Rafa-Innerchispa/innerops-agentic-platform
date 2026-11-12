from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime.cursor_ops_runner import cancel_ops_task


def _mock_db():
    col = MagicMock()
    db = MagicMock()
    db.__getitem__.return_value = col
    return db, col


def test_cancel_claimed_task_with_live_lease_evicts() -> None:
    db, col = _mock_db()
    known = {
        "task_id": "ops_abc123",
        "status": "claimed",
        "assignee": "antigravity",
        "claimed_by": "antigravity",
        "claim_token": "tok123",
        "lease_until": "2026-11-12T04:06:16+00:00",
        "claim_host": "ralphi-ia-ver-10",
    }
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event") as pub,
    ):
        out = cancel_ops_task("ops_abc123", reason="owner_cancel", channel="telegram", known_task=known)

    assert out["ok"] is True
    assert out["status"] == "cancelled"
    assert out["evicted"] is True
    assert out["previous_status"] == "claimed"
    filt, doc = col.update_one.call_args.args
    assert filt["task_id"] == "ops_abc123"
    assert "cancelled" in filt["status"]["$nin"]
    assert doc["$set"]["status"] == "cancelled"
    assert doc["$set"]["execution_stop"] is True
    assert doc["$set"]["cancelled_by"] == "RAFAEL"
    assert doc["$set"]["cancellation_channel"] == "telegram"
    assert doc["$set"]["cancellation_requested_at"]
    for field in ("claim_token", "claimed_by", "claimed_at", "lease_until", "claim_host"):
        assert field in doc["$unset"]
    assert "worktree" not in doc["$unset"]
    pub.assert_called_once()
    assert pub.call_args.args[0] == "task.cancelled"


def test_cancel_awaiting_task_without_claim() -> None:
    db, col = _mock_db()
    known = {"task_id": "ops_abc123", "status": "awaiting_antigravity_claim"}
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
    ):
        out = cancel_ops_task("ops_abc123", known_task=known)

    assert out["ok"] is True
    assert out["status"] == "cancelled"
    assert out["evicted"] is False


def test_cancel_terminal_task_is_noop() -> None:
    db, col = _mock_db()
    known = {"task_id": "ops_abc123", "status": "completed"}
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event") as pub,
    ):
        out = cancel_ops_task("ops_abc123", known_task=known)

    assert out["ok"] is True
    assert out["already_terminal"] is True
    assert out["evicted"] is False
    col.update_one.assert_not_called()
    pub.assert_not_called()


def test_cancel_missing_task_reports_not_found() -> None:
    db, col = _mock_db()
    col.update_one.return_value = MagicMock(matched_count=0)
    col.find_one.return_value = None
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
    ):
        out = cancel_ops_task("ops_nope")

    assert out["ok"] is False
    assert out["error"] == "task_not_found"


def test_cancel_conflict_when_task_raced_to_nonterminal() -> None:
    db, col = _mock_db()
    col.update_one.return_value = MagicMock(matched_count=0)
    col.find_one.return_value = {"task_id": "ops_abc123", "status": "in_progress"}
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
    ):
        out = cancel_ops_task("ops_abc123")

    assert out["ok"] is False
    assert out["error"] == "cancel_conflict"


def test_deny_on_live_claim_evicts_and_reports_terminal() -> None:
    from inneros_core_runtime import ops_whatsapp_owner as owner

    tid = "ops_abc123"
    before = {"task_id": tid, "status": "claimed", "assignee": "antigravity", "claim_token": "tok999"}
    after = {"task_id": tid, "status": "cancelled"}
    col = MagicMock()
    col.find_one.side_effect = [before, after]
    db = MagicMock()
    db.__getitem__.return_value = col

    with (
        patch.object(owner, "_resolve_task_id", return_value=tid),
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.whatsapp_ops_auth_pending.mark_cancel_requested"),
        patch("inneros_core_runtime.whatsapp_ops_auth_pending.clear_pending") as clear,
        patch("inneros_core_runtime.cursor_ops_runner._publish_task_event"),
    ):
        out = owner.handle_owner_reply("CANCELAR abc123")

    assert out["action"] == "deny"
    assert "Acción cancelada" in out["text"]
    clear.assert_called_once_with(tid)
    doc = col.update_one.call_args.args[1]
    assert doc["$set"]["status"] == "cancelled"
    assert "claim_token" in doc["$unset"]
    assert "lease_until" in doc["$unset"]
