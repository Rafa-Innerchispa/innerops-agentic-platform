"""Transport failover policy tests. No production API or network sends."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest


path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "notifications" / "owner_notification_router.py"
spec = importlib.util.spec_from_file_location("notification_router_under_test", path)
r = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = r
spec.loader.exec_module(r)

NOW = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)


def event(kind="report", severity="medium", owner_ack=False):
    return r.Notice(event_id="evt-20261022-00001", kind=kind, severity=severity,
                    title="Resumen de InnerOS", requires_owner_ack=owner_ack)


def progress():
    return r.NotificationProgress(event_id="evt-20261022-00001")


def send(ok=True, label="receipt"):
    return Mock(return_value={"ok": ok, "provider_message_id": label})


def test_all_event_categories_default_enabled():
    preferences = r.Preferences()
    assert all(preferences.eligible(event(k)) for k in r.KINDS)
    assert tuple(preferences.channel_enabled) == r.CHANNELS


def test_order_is_push_whatsapp_telegram_email():
    funcs = {ch: send(False) for ch in r.CHANNELS}
    funcs["email"] = send(True, "smtp-id")
    result = r.route_next(event(), progress(), r.Preferences(), funcs, now=NOW)
    assert result.attempted == ["push", "whatsapp", "telegram", "email"]
    assert result.last_channel == "email"
    assert result.state == "provider_accepted"
    assert funcs["email"].call_count == 1


def test_push_is_first_and_stops_unnecessary_sends():
    funcs = {ch: send(True) for ch in r.CHANNELS}
    p = r.route_next(event(), progress(), r.Preferences(), funcs, now=NOW)
    assert p.attempted == ["push"]
    assert p.state == "provider_accepted"
    r.route_next(event(), p, r.Preferences(), funcs, now=NOW+timedelta(hours=3))
    assert p.attempted == ["push"]
    funcs["whatsapp"].assert_not_called()


def test_fallback_to_whatsapp_after_push_fails():
    funcs = {"push": send(False), "whatsapp": send(True), "telegram": send(True)}
    p = r.route_next(event(), progress(), r.Preferences(), funcs, now=NOW)
    assert p.attempted == ["push", "whatsapp"]
    assert p.state == "provider_accepted"
    funcs["telegram"].assert_not_called()


def test_approval_escalates_without_owner_ack():
    funcs = {ch: send(True, ch) for ch in r.CHANNELS}
    p = r.route_next(event(kind="approval"), progress(), r.Preferences(), funcs, now=NOW)
    assert p.state == "awaiting_owner"
    assert p.last_channel == "push"
    r.route_next(event(kind="approval"), p, r.Preferences(), funcs, now=NOW+timedelta(seconds=119))
    assert p.attempted == ["push"]
    r.route_next(event(kind="approval"), p, r.Preferences(), funcs, now=NOW+timedelta(seconds=121))
    assert p.attempted == ["push", "whatsapp"]
    r.route_next(event(kind="approval"), p, r.Preferences(), funcs, now=NOW+timedelta(seconds=242))
    assert p.attempted == ["push", "whatsapp", "telegram"]


def test_explicit_ack_stops_escalation_but_never_authorizes():
    funcs = {ch: send(True) for ch in r.CHANNELS}
    p = r.route_next(event(kind="approval"), progress(), r.Preferences(), funcs, now=NOW)
    r.owner_acknowledge(p, NOW+timedelta(seconds=10))
    assert p.state == "acknowledged"
    assert p.acknowledged_at
    r.route_next(event(kind="approval"), p, r.Preferences(), funcs, now=NOW+timedelta(hours=5))
    assert p.attempted == ["push"]


def test_category_toggle_mutes_report_not_security_alert():
    prefs = r.Preferences(category_enabled={"report": False, "incident": False, "approval": False})
    p = r.route_next(event("report"), progress(), prefs, {"push": send(True)}, now=NOW)
    assert p.state == "muted"
    assert not p.attempted
    assert prefs.eligible(event("approval"))
    assert prefs.eligible(event("incident"))


def test_telegram_and_email_fallback_if_other_channels_switched_off():
    prefs = r.Preferences(channel_enabled={"push": False, "whatsapp": False, "telegram": True, "email": True})
    funcs = {"telegram": send(False), "email": send(True)}
    p = r.route_next(event("report"), progress(), prefs, funcs, now=NOW)
    assert p.attempted == ["telegram", "email"]


def test_no_channels_available_is_preserved_for_manual_recovery():
    funcs = {ch: send(False) for ch in r.CHANNELS}
    p = r.route_next(event(kind="approval"), progress(), r.Preferences(), funcs, now=NOW)
    assert p.state == "exhausted"
    assert len(p.receipts) == 4
    assert not any(x["accepted"] for x in p.receipts)


def test_call_errors_contained_and_no_sensitive_errors_echoed():
    functions = {"push": Mock(side_effect=RuntimeError("not-for-logs")),
                 "whatsapp": send(True)}
    p = r.route_next(event(), progress(), r.Preferences(), functions, now=NOW)
    assert p.attempted == ["push", "whatsapp"]
    assert "not-for-logs" not in str(p.receipts)


def test_does_not_count_provider_acceptance_as_read_or_approved():
    p = r.route_next(event(kind="approval"), progress(), r.Preferences(),
                     {"push": send(True, "ntfy-id")}, now=NOW)
    assert p.state == "awaiting_owner"
    assert p.acknowledged_at is None
    assert p.receipts[0]["provider_message_id"] == "ntfy-id"


def test_reject_unexpected_event_progress_pair():
    p = progress()
    with pytest.raises(ValueError):
        r.route_next(r.Notice(event_id="evt-other-00002", kind="report",
                              severity="medium", title="Otro"),
                     p, r.Preferences(), {}, now=NOW)


def test_event_ids_task_ids_and_preferences_validated():
    with pytest.raises(ValueError):
        r.route_next(r.Notice(event_id="bad", kind="report", severity="low", title="x"),
                     progress(), r.Preferences(), {}, now=NOW)
    with pytest.raises(ValueError):
        r.Preferences(escalation_seconds=5).validate()
    with pytest.raises(ValueError):
        r.Preferences(channel_enabled={"shell": True}).validate()


def test_high_priority_regular_event_escalates():
    p = r.route_next(event(kind="test_result", severity="high"), progress(),
                     r.Preferences(), {"push": send(True)}, now=NOW)
    assert p.state == "awaiting_owner"


def test_unseen_channel_without_config_does_not_block_fallback():
    funcs = {"email": send(True)}
    p = r.route_next(event(), progress(), r.Preferences(), funcs, now=NOW)
    assert p.last_channel == "email"
    assert p.attempted == list(r.CHANNELS)
