"""Competencia Alexa — Codex."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from competition.announce_lib import announce_phrase

PHRASE = "Hola, soy Codex."


def run() -> dict:
    try:
        ping = urllib.request.urlopen("http://192.168.1.4:8123/api/", timeout=5)
        if ping.status >= 500:
            return {"ok": False, "error": "ha_ping_failed"}
    except Exception as exc:
        return {"ok": False, "error": "ha_ping_unreachable", "detail": str(exc)[:120]}
    ha = announce_phrase(PHRASE)
    return {"ok": bool(ha.get("ok")), "provider": "codex", "phrase": PHRASE, "ha": ha}


if __name__ == "__main__":
    print(json.dumps(run(), default=str))
