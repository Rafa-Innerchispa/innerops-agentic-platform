"""Registro automático de acciones — sin pedir OUTBOX manual a agentes.

Todo daemon, script o tool que ejecute trabajo debe llamar ``record_agent_run()``.
Escribe: Mongo (activity + coordination), HUB/feed.jsonl, SESSION_LOG (1 línea).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.settings import COORD_ROOT

HUB_FEED = COORD_ROOT / "HUB" / "feed.jsonl"
SESSION_LOG = COORD_ROOT / "SESSION_LOG.md"
COL_AGENT_ACTIVITY = "agent_activity_log"


def record_agent_run(
    agent: str,
    *,
    action: str,
    summary: str,
    project: str = "ralfia",
    tool_used: str | None = None,
    metadata: dict[str, Any] | None = None,
    mirror_session_log: bool = True,
    mirror_feed: bool = True,
) -> dict[str, Any]:
    """Registro canónico de una ejecución automática o manual."""
    agent_u = agent.strip().upper()
    now_iso = ralfia_time.now_utc_iso()
    ts_display = ralfia_time.format_log()
    meta = metadata or {}

    db = mongo_store.get_db()
    activity = {
        "agent": agent_u,
        "action": action.strip(),
        "status": "completed",
        "summary": summary.strip(),
        "project": project,
        "tool_used": tool_used,
        "metadata": meta,
        "auto_logged": True,
        "finished_at": now_iso,
        "updated_at": now_iso,
        "ts_display": ts_display,
    }
    res = db[COL_AGENT_ACTIVITY].insert_one(activity)

    mongo_store.log_coordination(
        agent=agent_u,
        summary=summary,
        event=f"auto_{action}",
        project=project,
        tool_used=tool_used or "record_agent_run",
        metadata={"activity_id": str(res.inserted_id), "action": action, **meta},
    )

    if mirror_feed:
        _append_feed(
            {
                "ts": ts_display,
                "agent": agent_u,
                "action": action,
                "event": "auto_run",
                "summary": summary[:500],
                "project": project,
                "tool_used": tool_used,
            }
        )

    if mirror_session_log:
        _append_session_log(agent_u, action, summary)

    return {"ok": True, "activity_id": str(res.inserted_id), "ts": ts_display}


def _append_feed(entry: dict[str, Any]) -> None:
    HUB_FEED.parent.mkdir(parents=True, exist_ok=True)
    with HUB_FEED.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_session_log(agent: str, action: str, summary: str) -> None:
    if not SESSION_LOG.parent.is_dir():
        return
    line = f"- **{ralfia_time.format_log()}** | `{agent}` · `{action}` — {summary.strip()[:240]}\n"
    if not SESSION_LOG.is_file():
        SESSION_LOG.write_text("# SESSION LOG\n\n", encoding="utf-8")
    with SESSION_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
