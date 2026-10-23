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
    with mock.patch("raphiia_openai.notifications.evolution_client.any_whatsapp_connected", return_value=True):
        with mock.patch(
            "raphiia_openai.notifications.evolution_client.send_whatsapp_interactive",
            return_value={"ok": True},
        ) as send:
            out = alerts.notify_ops_owner_authorization_request(task, binding=binding, source_agent="notion")
    assert out["ok"] is True
    body = send.call_args[0][0]
    assert body.splitlines()[0].startswith("[")
    assert "OPS actual: ops_new1" in body
    assert "procede cursor" in body
    assert alerts.owner_auth_notified("ops_new1")


def _owner_task(*, priority="urgent"):
    return {
        "task_id": "ops_abcdef123456",
        "human_task_id": "P0-WA-FALLBACK",
        "title": "Revisar reparación del disco",
        "assignee": "cursor",
        "preferred_provider": "cursor",
        "execution_lane": "cursor_interactive",
        "do_not_auto_dispatch": True,
        "priority": priority,
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
    }


def test_smtp_fallback_when_both_whatsapp_sessions_closed():
    from inneros_core_runtime.execution_binding import owner_execution_summary

    task = _owner_task()
    alerts._STATE["sent"] = []
    alerts._STATE["cooldowns"] = {}
    with (
        mock.patch("raphiia_openai.notifications.evolution_client.any_whatsapp_connected",
                   return_value=False),
        mock.patch("inneros_core_runtime.execution_binding.owner_execution_summary",
                   return_value={"owner_whatsapp_alert_kind": "external_spend",
                                 "provider": "cursor",
                                 "why_not_internal": "credit gate",
                                 "owner_action_hint": "review task",
                                 "internal_alternative": ""}),
        mock.patch("raphiia_openai.notifications.evolution_client.send_whatsapp_interactive") as interactive,
        mock.patch("raphiia_openai.notifications.evolution_client.send_alert_whatsapp") as plain,
        mock.patch.object(alerts, "_notify_ops_auth_email_fallback",
                          return_value={"ok": True, "channel": "email"}) as fallback,
        mock.patch.object(alerts, "_mark_owner_auth_sent_mongo"),
    ):
        result = alerts.notify_ops_owner_authorization_request(task, force=True)
    assert result["ok"] is True
    assert result["delivery_mode"] == "email_fallback"
    assert result["email_fallback"]["ok"] is True
    fallback.assert_called_once()
    assert fallback.call_args.kwargs["tid"] == task["task_id"]
    interactive.assert_not_called()
    plain.assert_not_called()


def test_urgent_internal_fix_uses_email_instead_of_silent_drop():
    task = _owner_task(priority="urgent")
    alerts._STATE["sent"] = []
    alerts._STATE["cooldowns"] = {}
    with (
        mock.patch("raphiia_openai.notifications.evolution_client.any_whatsapp_connected",
                   return_value=False),
        mock.patch("inneros_core_runtime.execution_binding.owner_execution_summary",
                   return_value={"owner_whatsapp_alert_kind": "internal_fix",
                                 "provider": "dev_swarm",
                                 "why_not_internal": "repo contract incomplete",
                                 "owner_action_hint": "",
                                 "internal_alternative": ""}),
        mock.patch("raphiia_openai.notifications.evolution_client.send_alert_whatsapp") as plain,
        mock.patch.object(alerts, "_notify_ops_auth_email_fallback",
                          return_value={"ok": True, "channel": "email"}) as fallback,
        mock.patch.object(alerts, "_mark_owner_auth_sent_mongo"),
    ):
        result = alerts.notify_ops_owner_authorization_request(task, force=True)
    assert result["ok"] is True
    assert result["delivery_mode"] == "email_fallback"
    assert fallback.call_args.kwargs["alert_kind"] == "internal_fix"
    plain.assert_not_called()


def test_fallback_email_does_not_claim_email_replies_are_authorized():
    task = _owner_task()
    with (
        mock.patch.dict("os.environ", {
            "NOTIFY_OPS_AUTH_EMAIL_FALLBACK": "1",
            "RALFIA_OPS_AUTH_EMAIL_TO": "rafagye@gmail.com",
        }),
        mock.patch("inneros_core_runtime.notifications.email_client.send_email",
                   return_value={"ok": True}) as send,
    ):
        external = alerts._notify_ops_auth_email_fallback(
            task, body="Prueba", provider="cursor", tid=task["task_id"])
        internal = alerts._notify_ops_auth_email_fallback(
            task, body="Prueba", provider="dev_swarm",
            tid=task["task_id"], alert_kind="internal_fix")
    assert external["ok"] and internal["ok"]
    body_external = send.call_args_list[0].kwargs["body"]
    body_internal = send.call_args_list[1].kwargs["body"]
    assert "NO se procesa automáticamente" in body_external
    assert "CONFIRMAR" not in body_internal
    assert "No se requiere autorización" in body_internal
