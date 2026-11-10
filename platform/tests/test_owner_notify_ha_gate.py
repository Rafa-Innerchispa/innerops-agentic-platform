"""Compuerta HA del fanout: Telegram primario, HA solo en critical."""
from __future__ import annotations

import sys
import types

from inneros_core_runtime.notifications import owner_notify_fanout as fanout


def test_ha_skipped_for_non_critical(monkeypatch):
    monkeypatch.setenv("NOTIFY_OPS_AUTH_HA", "1")
    monkeypatch.setenv("NOTIFY_OPS_TELEGRAM", "0")
    out = fanout.notify_owner(
        title="t",
        body="b",
        kind="probe",
        email_always=False,
        ha=True,
        telegram=False,
        severity="info",
    )
    assert out["channels"]["ha"] == {"ok": False, "skipped": "non_critical_severity"}


def test_ha_fires_for_critical_when_enabled(monkeypatch):
    fake = types.ModuleType("inneros_core_runtime.notifications.ops_ha_owner_auth")
    fake.notify_companion_scout_alert = lambda **kw: {"ok": True}
    monkeypatch.setitem(
        sys.modules,
        "inneros_core_runtime.notifications.ops_ha_owner_auth",
        fake,
    )
    monkeypatch.setenv("NOTIFY_OPS_AUTH_HA", "1")
    monkeypatch.setenv("NOTIFY_OPS_TELEGRAM", "0")
    out = fanout.notify_owner(
        title="t",
        body="b",
        kind="probe",
        email_always=False,
        ha=True,
        telegram=False,
        severity="critical",
    )
    assert out["channels"]["ha"] == {"ok": True}
    assert out["ok"] is True


def test_mirror_ops_alert_defaults_to_non_critical(monkeypatch):
    monkeypatch.setenv("NOTIFY_OPS_AUTH_HA", "1")
    monkeypatch.setenv("NOTIFY_OPS_TELEGRAM", "0")
    monkeypatch.setenv("INNEROS_WHATSAPP_NOTIFICATIONS", "0")
    out = fanout.mirror_ops_alert("hola", title="Alerta RalfIA")
    assert out["channels"]["ha"] == {"ok": False, "skipped": "non_critical_severity"}
