"""Explicit-only read-only check of OPS email fallback settings, no secrets."""
from __future__ import annotations

import json
import os


def test_ops_email_fallback_config_report_only():
    fields = ["RALFIA_OPS_AUTH_EMAIL_TO", "INNEROS_ADMIN_EMAILS",
              "NOTIFY_EMAIL_TO", "RALFIA_ALERTS_EMAIL_TO",
              "NOTIFY_OPS_AUTH_EMAIL_FALLBACK",
              "RALFIA_ALERTS_TO", "NOTIFY_WHATSAPP_TO"]
    present = {name: bool(os.getenv(name, "").strip()) for name in fields}
    active = os.getenv("NOTIFY_OPS_AUTH_EMAIL_FALLBACK", "1").strip().lower() not in {"0", "false", "off", "no"}
    configured = any(present[k] for k in ["RALFIA_OPS_AUTH_EMAIL_TO", "INNEROS_ADMIN_EMAILS", "NOTIFY_EMAIL_TO"])
    print("OPS_EMAIL_FALLBACK_CONFIG=" + json.dumps({
        "configured_delivery_recipient": configured,
        "fallback_enabled": active,
        "env_presence_only": present,
    }, sort_keys=True))
