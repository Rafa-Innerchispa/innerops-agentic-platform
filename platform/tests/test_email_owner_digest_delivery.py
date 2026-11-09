from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PLATFORM_DIR / "scripts" / "run_email_owner_digest.py"
SERVICE = PLATFORM_DIR / "systemd" / "user" / "inneros-email-owner-digest.service"
TIMER = PLATFORM_DIR / "systemd" / "user" / "inneros-email-owner-digest.timer"


def _load_script():
    spec = importlib.util.spec_from_file_location("run_email_owner_digest_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_digest_cli_prints_delivery_evidence(capsys, monkeypatch):
    fake = types.ModuleType("inneros_core_runtime.notifications.email_owner_digest")

    def _deliver(*, hours, limit, whatsapp):
        return {
            "ok": True,
            "report_text": "# Digest de prueba",
            "delivered": True,
            "fanout": {
                "ok": True,
                "channels": {"telegram_fanout": {"ok": True}, "email": {"ok": False}},
            },
        }

    fake.deliver_email_owner_digest = _deliver
    pkg = types.ModuleType("inneros_core_runtime.notifications")
    pkg.email_owner_digest = fake
    monkeypatch.setitem(sys.modules, "inneros_core_runtime.notifications", pkg)
    monkeypatch.setitem(sys.modules, "inneros_core_runtime.notifications.email_owner_digest", fake)
    monkeypatch.setattr(sys, "argv", ["run_email_owner_digest.py", "--hours", "24", "--limit", "5"])

    mod = _load_script()
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "# Digest de prueba" in out
    assert '"delivered": true' in out
    assert '"telegram_fanout": true' in out
    assert '"email": false' in out


def test_digest_is_scheduled_by_systemd_units():
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    assert "run_email_owner_digest.py" in service
    assert "OnUnitActiveSec=6h" in timer
    assert "Unit=inneros-email-owner-digest.service" in timer
