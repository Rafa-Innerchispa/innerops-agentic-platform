from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

_alerts_path = PLATFORM_DIR / "inneros_core_runtime" / "notifications" / "ops_task_alerts.py"
_spec = importlib.util.spec_from_file_location("ops_task_alerts_owner_test", _alerts_path)
assert _spec and _spec.loader
alerts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alerts)


def test_notify_ops_owner_authorization_request_cursor():
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
    from inneros_core_runtime import execution_binding as eb

    binding = eb.resolve_execution_binding(task)
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with (
        mock.patch(
            "inneros_core_runtime.notifications.ops_ha_owner_auth.ha_auth_enabled",
            return_value=False,
        ),
        mock.patch(
            "inneros_core_runtime.notifications.telegram_client.telegram_enabled",
            return_value=True,
        ),
        mock.patch(
            "inneros_core_runtime.notifications.telegram_client.configured",
            return_value=True,
        ),
        mock.patch(
            "inneros_core_runtime.notifications.telegram_client.send_message",
            return_value={"ok": True},
        ) as send,
        mock.patch.object(alerts, "_mark_owner_auth_sent_mongo"),
    ):
        out = alerts.notify_ops_owner_authorization_request(task, binding=binding, source_agent="notion")
    assert out["ok"] is True
    assert out["delivery_mode"] == "telegram"
    body = send.call_args[0][0]
    assert "*Agente:* CURSOR" in body
    assert "gasta créditos" in body.lower()
    assert "CONFIRMAR" in body
    assert "ops_new1" in body
    keyboard = send.call_args[1].get("reply_markup") or {}
    assert "inline_keyboard" in keyboard
    assert len(alerts._STATE["sent"]) == 1
