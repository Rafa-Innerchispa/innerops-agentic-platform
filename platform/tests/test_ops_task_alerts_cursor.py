from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import importlib.util

_alerts_path = PLATFORM_DIR / "inneros_core_runtime" / "notifications" / "ops_task_alerts.py"
_spec = importlib.util.spec_from_file_location("ops_task_alerts_cursor_test", _alerts_path)
assert _spec and _spec.loader
alerts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alerts)


def test_notify_cursor_awaiting_claim_sends_whatsapp():
    task = {
        "task_id": "ops_test",
        "title": "Pin model",
        "status": "awaiting_cursor_claim",
        "assignee": "cursor",
        "correlation_id": "inneros-core-autonomy-model-pin-20261008",
    }
    alerts._STATE["cooldowns"] = {}
    alerts._STATE["sent"] = []
    with mock.patch.object(alerts, "send_alert_whatsapp", return_value={"ok": True}) as send:
        out = alerts.notify_cursor_awaiting_claim(task, previous_status="queued")
    assert out["ok"] is True
    send.assert_called_once()
    body = send.call_args[0][0]
    assert "procede cursor" in body
    assert "inneros-core-autonomy-model-pin-20261008" in body
