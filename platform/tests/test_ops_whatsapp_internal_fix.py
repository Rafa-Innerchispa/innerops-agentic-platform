from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

_alerts_path = PLATFORM_DIR / "inneros_core_runtime" / "notifications" / "ops_task_alerts.py"
_spec = importlib.util.spec_from_file_location("ops_task_alerts_whatsapp_fix_test", _alerts_path)
assert _spec and _spec.loader
alerts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alerts)

from inneros_core_runtime import execution_binding as eb


def _qwen_no_repo_task(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "title": "Normalized task message",
        "assignee": "qwen-coding",
        "preferred_provider": "qwen-coding",
        "execution_lane": "internal",
        "repo": None,
        "from_agent": "RAFAEL",
    }


def test_bounded_runner_requires_repo_is_internal_fix_not_credit_auth():
    task = _qwen_no_repo_task("ops_b5797ff8d8af")
    binding = eb.resolve_execution_binding(task)
    assert binding["error"] == "bounded_runner_requires_repo"
    summary = eb.owner_execution_summary(task, binding)
    assert summary["owner_whatsapp_alert_kind"] == "internal_fix"
    assert summary["requires_owner_authorization"] is False
    assert summary["requires_external_credit_authorization"] is False
    assert summary["blocked_internal_route"] is True


def test_qwen_canary_fixture_skips_whatsapp():
    task = {
        **_qwen_no_repo_task("ops_b0e5c11596e7"),
        "title": "P0 offline canary",
        "source_message_id": "msg_test_source",
        "execution_lane": "canary",
    }
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with mock.patch.object(alerts, "send_alert_whatsapp", return_value={"ok": True}) as send:
        out = alerts.notify_ops_owner_authorization_request(task, force=True)
    assert out["skipped"] == "synthetic_source_message"
    send.assert_not_called()


def test_internal_fix_whatsapp_no_credit_wording_no_confirm_buttons():
    task = _qwen_no_repo_task("ops_b5797ff8d8af")
    binding = eb.resolve_execution_binding(task)
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with (
        mock.patch("raphiia_openai.notifications.evolution_client.any_whatsapp_connected",
                   return_value=True),
        mock.patch("raphiia_openai.notifications.evolution_client.send_alert_whatsapp",
                   return_value={"ok": True}) as send,
    ):
        out = alerts.notify_ops_owner_authorization_request(task, binding=binding, force=True)
    assert out["ok"] is True
    assert out["delivery_mode"] == "text_internal_fix"
    body = send.call_args[0][0]
    assert "gasta créditos" not in body.lower()
    assert "carril interno bloqueado" in body.lower()
    assert "CONFIRMAR" not in body


def test_local_coding_with_repo_still_internal_ready():
    task = {
        "task_id": "ops_local_repo_ok",
        "title": "Fix with repo",
        "assignee": "qwen-coding",
        "preferred_provider": "local-amd-5",
        "execution_lane": "internal",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
    }
    binding = eb.resolve_execution_binding(task)
    assert binding["allowed"] is True
    summary = eb.owner_execution_summary(task, binding)
    assert summary["owner_whatsapp_alert_kind"] == "internal_ready"


def test_notify_ops_owner_authorization_request_cursor_external_spend():
    task = {
        "task_id": "ops_new1",
        "title": "Pin Composer",
        "assignee": "cursor",
        "preferred_provider": "cursor",
        "execution_lane": "cursor_interactive",
        "correlation_id": "inneros-core-autonomy-model-pin-20261008",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "do_not_auto_dispatch": True,
    }
    binding = eb.resolve_execution_binding(task)
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with (
        mock.patch("raphiia_openai.notifications.evolution_client.any_whatsapp_connected",
                   return_value=True),
        mock.patch("raphiia_openai.notifications.evolution_client.send_whatsapp_interactive",
                   return_value={"ok": True}) as send,
        mock.patch("inneros_core_runtime.whatsapp_ops_auth_pending.register_pending"),
    ):
        out = alerts.notify_ops_owner_authorization_request(
            task, binding=binding, source_agent="notion", force=True
        )
    assert out["ok"] is True
    body = send.call_args[0][0]
    assert "Por qué no runner interno" in body
    assert "procede cursor" in body
    assert "gasta créditos" in body.lower()
    assert alerts.owner_auth_notified("ops_new1")
