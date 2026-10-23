"""Explicit-only owner WhatsApp connectivity preflight: GET requests, no send.

Does not print phone numbers, API keys, instance IDs or server URLs.
"""
import json
import os


def test_owner_whatsapp_readonly_connectivity():
    from raphiia_openai.notifications import evolution_client as evo

    status = evo.dual_whatsapp_status()
    safe = {
        node: {"api_up": bool(info.get("api_up")),
               "connected": bool(info.get("connected"))}
        for node, info in status.items()
    }
    safe["owner_alert_destination_configured"] = bool(
        (os.getenv("RALFIA_ALERTS_TO") or os.getenv("NOTIFY_WHATSAPP_TO") or "").strip()
    )
    safe["any_connected"] = bool(evo.any_whatsapp_connected())
    safe["read_only"] = True
    print("INNEROS_OWNER_WHATSAPP_PREFLIGHT=" + json.dumps(safe, sort_keys=True))
    assert safe["any_connected"], "No active WhatsApp Evolution session visible from test runner"
