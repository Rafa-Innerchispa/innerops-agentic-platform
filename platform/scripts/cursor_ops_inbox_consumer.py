#!/usr/bin/env python3
"""Poll Cursor agent inbox, ACK open messages, register authentic consumer heartbeat.

Does not execute ops tasks (no headless Cursor runner). Interactive execution
happens in an active Cursor agent session after delivery + claim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_execution_plane as cep
from inneros_core_runtime.memory import agent_messages as am


def run(*, limit: int = 20, ack_open: bool = True) -> dict:
    if ack_open:
        polled = am.poll_agent_inbox(agent="cursor", limit=limit, auto_ack=True)
        acks = polled.get("acknowledged") or []
        listed = {"messages": polled.get("messages") or [], "count": polled.get("count")}
    else:
        listed = am.list_agent_messages(agent="cursor", status="open", limit=limit, role="inbox")
        acks = []

    import socket

    hb = cep.register_cursor_consumer_heartbeat(
        identity={"mailbox": "cursor", "host": socket.gethostname(), "role": "inbox_consumer"},
    )
    live = cep.read_session_liveness()
    return {
        "ok": True,
        "heartbeat": hb,
        "session_active": live.get("active"),
        "open_listed": len(listed.get("messages") or []),
        "acks": acks if isinstance(acks, list) else [],
        "classification": cep.classify_cursor_execution(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor inbox consumer (ACK + authentic heartbeat)")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--no-ack", action="store_true")
    args = parser.parse_args()
    out = run(limit=max(1, min(args.limit, 100)), ack_open=not args.no_ack)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("session_active") else 2


if __name__ == "__main__":
    raise SystemExit(main())
