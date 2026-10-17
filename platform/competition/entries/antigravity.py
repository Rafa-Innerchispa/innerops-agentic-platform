"""Competencia Alexa — Antigravity."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from competition.announce_lib import announce_phrase

PHRASE = "Hola, soy Antigravity."


def run() -> dict:
    ha = announce_phrase(PHRASE)
    return {
        "ok": bool(ha.get("ok")),
        "provider": "antigravity",
        "phrase": PHRASE,
        "ha": ha,
        "meta": {"agent": "antigravity"},
    }


if __name__ == "__main__":
    print(json.dumps(run(), default=str))
