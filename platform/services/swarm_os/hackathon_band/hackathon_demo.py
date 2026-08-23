#!/usr/bin/env python3
"""CLI hackathon Band — pipeline real end-to-end."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hackathon_band.exceptions import HackathonConfigError, HackathonIntegrationError
from hackathon_band.pipeline import run_collaboration
from hackathon_band.validate import readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Hackathon Band of Agents — demo CLI")
    parser.add_argument("-q", "--question", default=None, help="Pregunta operativa")
    parser.add_argument("--check", action="store_true", help="Solo verificar .env")
    args = parser.parse_args()

    status = readiness()
    print("=== Hackathon Band — readiness ===")
    print(json.dumps(status, indent=2, ensure_ascii=False))

    if args.check:
        return 0 if status["ready"] else 1

    if not status["ready"]:
        print("\nERROR: Faltan variables en .env. Usa --check para ver la lista.")
        return 1

    def on_progress(ev: dict) -> None:
        step = ev.get("step", "?")
        print(f"\n--- {step} ---")
        if "llm" in ev:
            llm = ev["llm"]
            print(f"  LLM: {llm.get('provider')} / {llm.get('model')}")
        if "sources" in ev:
            print(f"  Fuentes memoria: {ev['sources'][:5]}")

    try:
        result = run_collaboration(args.question, on_progress=on_progress)
    except (HackathonConfigError, HackathonIntegrationError) as exc:
        print(f"\nFALLO: {exc}")
        return 2

    print("\n=== OK ===")
    print(f"Band mode: {result['band_mode']}")
    print(f"Chat ID: {result['chat_id']}")
    print(f"Reporte: {result['report_path']}")
    print(f"Mensajes Band: {len(result['messages'])}")
    print("\n--- Preview reporte (500 chars) ---")
    print(result["report_markdown"][:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
