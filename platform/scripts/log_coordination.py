#!/usr/bin/env python3
"""Registra evento en Mongo ralfia_coordination_log + append SESSION_LOG."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import mongo_store, ralfia_time  # noqa: E402

COORD_DIR = Path("/home/rlopez/data/ai_coordination")
SESSION_LOG = COORD_DIR / "SESSION_LOG.md"


def _append_session_log(agent: str, summary: str) -> None:
    if not SESSION_LOG.parent.exists():
        return
    ts = ralfia_time.format_log()
    line = f"{ts} | {agent.upper()} | {summary}\n"
    with SESSION_LOG.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Log coordinación RalfIA → Mongo + SESSION_LOG")
    parser.add_argument("--agent", required=True, help="CURSOR, CODEX, RAFAEL, …")
    parser.add_argument("--summary", required=True, help="Resumen corto")
    parser.add_argument("--project", default=None)
    parser.add_argument("--tool", dest="tool_used", default=None)
    parser.add_argument("--event", default="development")
    args = parser.parse_args()

    doc = mongo_store.log_coordination(
        agent=args.agent,
        summary=args.summary,
        event=args.event,
        project=args.project,
        tool_used=args.tool_used,
    )
    _append_session_log(args.agent, args.summary)
    print(doc.get("_id"), doc.get("summary"))


if __name__ == "__main__":
    main()
