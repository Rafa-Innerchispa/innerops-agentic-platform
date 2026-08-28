"""Auto-sync coordinación: watcher → Mongo hub_live + SESSION_LOG + MAPA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.settings import COL_COORDINATION_STATE, COORD_ROOT

SESSION_LOG = COORD_ROOT / "SESSION_LOG.md"
MAPA = COORD_ROOT / "MAPA_CENTRAL.md"
HUB_FEED = COORD_ROOT / "HUB" / "feed.jsonl"


def _now() -> str:
    return ralfia_time.format_log()


def _append_session_log(line: str) -> None:
    if not SESSION_LOG.parent.is_dir():
        return
    header = f"- **{_now()}** | {line}\n"
    if not SESSION_LOG.is_file():
        SESSION_LOG.write_text("# SESSION LOG\n\n", encoding="utf-8")
    with SESSION_LOG.open("a", encoding="utf-8") as f:
        f.write(header)


def _patch_mapa_sync(extra: str = "") -> None:
    if not MAPA.is_file():
        return
    marker = "**Última sync:**"
    line = f"{marker} {_now()} · auto-sync{(' · ' + extra) if extra else ''}"
    text = MAPA.read_text(encoding="utf-8")
    if marker in text:
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith(marker):
                lines[i] = line
                break
        MAPA.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        MAPA.write_text(line + "\n\n" + text, encoding="utf-8")


def _hub_live_patch(changes: list[str]) -> dict[str, Any]:
    db = mongo_store.get_db()
    doc = {
        "updated_at": _now(),
        "last_changes": changes[:20],
        "change_count": len(changes),
        "feed_tail": _read_feed_tail(8),
    }
    db[COL_COORDINATION_STATE].update_one(
        {"key": "hub_live"},
        {"$set": doc},
        upsert=True,
    )
    return doc


def _read_feed_tail(n: int = 5) -> list[dict[str, Any]]:
    if not HUB_FEED.is_file():
        return []
    lines = HUB_FEED.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def apply_file_changes(changes: list[str]) -> dict[str, Any]:
    """Llamar tras watcher cuando hay cambios en INBOX/OUTBOX/TASKS/etc."""
    if not changes:
        return {"ok": True, "applied": 0}
    summary = "; ".join(changes[:5])
    _patch_mapa_sync(summary[:120])
    hub = _hub_live_patch(changes)
    for ch in changes[:3]:
        _append_session_log(f"AUTO-SYNC · {ch}")
    mongo_store.log_coordination(
        agent="AUTO-SYNC",
        summary=f"Coordinación actualizada: {summary}",
        event="coordination_auto_sync",
        project="ralfia-coordination",
        metadata={"changes": changes[:10]},
    )
    return {"ok": True, "applied": len(changes), "hub_live": hub}
