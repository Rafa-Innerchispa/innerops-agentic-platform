"""Competencia Alexa — Codex."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from competition.announce_lib import announce_phrase

PHRASE = "Hola, soy Codex."


def run() -> dict:
    from raphiia_openai import homeassistant_client as ha

    ping = ha.ping()
    if not ping.get("ok"):
        return {"ok": False, "error": "ha_ping_failed", "detail": ping}
    out_ha = announce_phrase(PHRASE)
    return {"ok": bool(out_ha.get("ok")), "provider": "codex", "phrase": PHRASE, "ha": out_ha}


if __name__ == "__main__":
    print(json.dumps(run(), default=str))
