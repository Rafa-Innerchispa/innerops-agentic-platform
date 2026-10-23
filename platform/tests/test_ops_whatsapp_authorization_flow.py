from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import ops_whatsapp_owner as owner
from inneros_core_runtime.notifications import ops_task_alerts as alerts


def test_awaiting_claim_notice_is_suppressed_when_persistent_auth_pending():
    task = {
        "task_id": "ops_abcdef123456",
        "title": "Read only Bellini audit",
        "status": "awaiting_antigravity_claim",
        "assignee": "antigravity",
    }
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with (
        patch(
            "inneros_core_runtime.whatsapp_ops_auth_pending.get_by_task_id",
            return_value={"task_id": task["task_id"], "status": "pending"},
        ),
        patch.object(alerts, "send_alert_whatsapp", return_value={"ok": True}) as send,
    ):
        out = alerts.notify_cursor_awaiting_claim(task, previous_status="queued")
    assert out["ok"] is False
    assert out["skipped"] == "already_notified_on_create"
    send.assert_not_called()


def test_cancel_signal_does_not_claim_terminal_cancel_before_projection_confirms():
    tid = "ops_abcdef123456"
    task = {"task_id": tid, "status": "awaiting_antigravity_claim", "assignee": "antigravity"}
    col = MagicMock()
    col.find_one.side_effect = [task, task]
    db = MagicMock()
    db.__getitem__.return_value = col

    with (
        patch.object(owner, "_resolve_task_id", return_value=tid),
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.whatsapp_ops_auth_pending.mark_cancel_requested") as mark,
        patch("inneros_core_runtime.whatsapp_ops_auth_pending.clear_pending") as clear,
    ):
        out = owner.handle_owner_reply("CANCELAR abcdef123456")

    assert out["ok"] is True
    assert out["action"] == "deny_pending"
    assert "Cancelación solicitada" in out["text"]
    assert "Acción cancelada" not in out["text"]
    mark.assert_called_once_with(tid)
    clear.assert_not_called()
    assert col.update_one.call_count == 1
    update = col.update_one.call_args.args[1]["$set"]
    assert update["cancellation_requested_by"] == "RAFAEL"
    assert update["cancellation_channel"] == "whatsapp"
    assert update["cancellation_requested_at"]


def test_terminal_cancel_clears_pending_and_reports_cancelled():
    tid = "ops_abcdef123456"
    before = {"task_id": tid, "status": "awaiting_antigravity_claim"}
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
    ):
        out = owner.handle_owner_reply("CANCELAR abcdef123456")

    assert out["action"] == "deny"
    assert "Acción cancelada" in out["text"]
    clear.assert_called_once_with(tid)


def test_numeric_auth_refuses_ambiguity():
    with patch(
        "inneros_core_runtime.whatsapp_ops_auth_pending.pending_for_phone",
        return_value=[
            {"task_id": "ops_111111111111", "status": "pending"},
            {"task_id": "ops_222222222222", "status": "pending"},
        ],
    ):
        out = owner.handle_owner_reply("1", phone="593000000000")
    assert out["ok"] is False
    assert out["action"] == "ambiguous_numeric_auth"
    assert "botón de la tarea exacta" in out["text"]


def test_authorization_is_blocked_after_cancel_requested():
    tid = "ops_abcdef123456"
    task = {
        "task_id": tid,
        "status": "awaiting_antigravity_claim",
        "assignee": "antigravity",
        "cancellation_requested_at": "2026-10-14T00:00:00Z",
    }
    col = MagicMock()
    col.find_one.return_value = task
    db = MagicMock()
    db.__getitem__.return_value = col

    with (
        patch.object(owner, "_resolve_task_id", return_value=tid),
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
    ):
        out = owner.handle_owner_reply("CONFIRMAR abcdef123456")

    assert out["ok"] is False
    assert out["action"] == "auth_cancel_pending"


def test_resend_exact_task_does_not_create_new_ops_task():
    tid = "ops_abcdef123456"
    task = {"task_id": tid, "status": "awaiting_antigravity_claim"}
    col = MagicMock()
    col.find_one.return_value = task
    db = MagicMock()
    db.__getitem__.return_value = col

    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch.object(
            alerts,
            "notify_ops_owner_authorization_request",
            return_value={"ok": True, "task_id": tid, "delivery_mode": "buttons_plus_text"},
        ) as notify,
    ):
        out = alerts.resend_ops_owner_authorization(tid)

    assert out["ok"] is True
    notify.assert_called_once_with(task, force=True)
    col.insert_one.assert_not_called()


def test_awaiting_claim_uses_email_when_both_whatsapp_sessions_are_down():
    task = {
        "task_id": "ops_abcdef123456",
        "status": "awaiting_cursor_claim",
        "assignee": "cursor",
        "preferred_provider": "cursor",
        "title": "Diagnosticar disco",
    }
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with (
        patch("inneros_core_runtime.execution_binding.resolve_execution_binding", return_value={}),
        patch("inneros_core_runtime.execution_binding.requires_external_owner_authorization", return_value=True),
        patch("inneros_core_runtime.whatsapp_ops_auth_pending.get_by_task_id", return_value=None),
        patch.object(alerts, "owner_auth_notified", return_value=False),
        patch("raphiia_openai.notifications.evolution_client.any_whatsapp_connected", return_value=False),
        patch.object(alerts, "send_alert_whatsapp") as send,
        patch.object(alerts, "_notify_ops_auth_email_fallback", return_value={"ok": True}) as fallback,
    ):
        out = alerts.notify_cursor_awaiting_claim(task, previous_status="queued")
    assert out["ok"] is True
    assert out["result"]["channel"] == "email_fallback"
    assert fallback.call_args.kwargs["tid"] == "ops_abcdef123456"
    send.assert_not_called()
