"""Carril A — competencia identidad Alexa."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from competition.announce_lib import announce_phrase
PHRASE = "Hola, soy carril A."
def run() -> dict:
    ha = announce_phrase(PHRASE)
    return {"ok": bool(ha.get("ok")), "carril": "A", "phrase": PHRASE, "ha": ha}
if __name__ == "__main__":
    print(json.dumps(run(), default=str))
