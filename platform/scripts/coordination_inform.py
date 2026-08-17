#!/usr/bin/env python3
"""Informa avance a todos los agentes vía Mongo + bump ESTADO_VIVO."""

from __future__ import annotations

import sys

from raphiia_openai.coordination_live import bump_revision, refresh_estado_vivo
from raphiia_openai.memory.agent_messages import compact_agent_mailbox, create_agent_message


def inform(title: str, body: str, *, priority: str = "high", revision_reason: str | None = None) -> dict:
    targets = ("chatgpt", "codex", "antigravity", "notion", "gemini", "cursor")
    ids = []
    for t in targets:
        if t == "cursor":
            continue
        res = create_agent_message(
            from_agent="CURSOR",
            target_agent=t,
            title=title,
            body=body,
            priority=priority,
            tags=["progress", "cot"],
        )
        ids.append(res.get("message_id"))
    rev = bump_revision(reason=revision_reason or title[:120], source="cursor")
    refresh_estado_vivo()
    for a in targets:
        compact_agent_mailbox(a, max_open=8)
    return {"ok": True, "message_ids": ids, "revision": rev.get("revision")}


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "Avance COT"
    body = sys.stdin.read() if not sys.stdin.isatty() else (sys.argv[2] if len(sys.argv) > 2 else title)
    print(inform(title, body))
