"""Competencia Alexa — Cursor."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from competition.announce_lib import announce_phrase

PHRASE = "Hola, soy Cursor."


def run() -> dict:
    proc = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        return {"ok": False, "error": "cursor_subprocess_check_failed"}
    ha = announce_phrase(PHRASE)
    return {"ok": bool(ha.get("ok")), "provider": "cursor", "phrase": PHRASE, "ha": ha}


if __name__ == "__main__":
    print(json.dumps(run(), default=str))
