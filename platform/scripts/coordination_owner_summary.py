#!/usr/bin/env python3
"""Resumen operativo periódico: OPS, Dev Swarm, último ciclo de coordinación."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORE = Path(os.environ.get("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core"))
LAST_CYCLE = CORE / "var" / "inneros_autopilot" / "last-coordination-cycle.json"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ops_snapshot(limit: int = 12) -> list[dict]:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    active = {"queued", "in_progress", "awaiting_owner_authorization", "verification", "proposed"}
    rows = list(
        db["ralfia_ops_tasks"]
        .find({"status": {"$in": list(active)}}, {"_id": 0, "task_id": 1, "title": 1, "status": 1, "assignee": 1})
        .sort("updated_at", -1)
        .limit(limit)
    )
    return rows


def _recent_terminal(limit: int = 8) -> list[dict]:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = list(
        db["ralfia_ops_tasks"]
        .find(
            {"status": {"$in": ["completed", "failed", "blocked"]}, "updated_at": {"$gte": since}},
            {"_id": 0, "task_id": 1, "title": 1, "status": 1},
        )
        .sort("updated_at", -1)
        .limit(limit)
    )
    return rows


def build_summary() -> str:
    lines = [f"# Resumen InnerOS — {_utc()}", ""]

    if LAST_CYCLE.is_file():
        try:
            cycle = json.loads(LAST_CYCLE.read_text(encoding="utf-8"))
            tick = (cycle.get("dev_swarm_tick") or {})
            lines.append("## Coordinación (último ciclo)")
            lines.append(f"- Dev Swarm ejecutados: {tick.get('executed', '?')}")
            lines.append(f"- Workers activos: {tick.get('active_worker_count', '?')}")
            lines.append(f"- Hygiene acciones: {(cycle.get('hygiene') or {}).get('action_count', '?')}")
            lines.append("")
        except Exception:
            pass

    active = _ops_snapshot()
    lines.append(f"## OPS activas ({len(active)})")
    for row in active[:10]:
        lines.append(
            f"- [{row.get('status')}] {str(row.get('task_id') or '')[:20]} · "
            f"{str(row.get('title') or '')[:70]}"
        )
    if not active:
        lines.append("- (ninguna en cola/progreso)")
    lines.append("")

    done = _recent_terminal()
    lines.append(f"## Hoy terminadas / fallidas ({len(done)})")
    for row in done[:8]:
        lines.append(f"- {row.get('status')}: {str(row.get('title') or '')[:72]}")
    lines.append("")
    lines.append("Chat voz: https://voz.pcdoctor.ai/")
    lines.append("Telegram: /start al bot OPS cuando el poll esté activo.")
    return "\n".join(lines)


def main() -> int:
    text = build_summary()
    from inneros_core_runtime.notifications.owner_notify_fanout import notify_owner

    result = notify_owner(title="Resumen operativo", body=text, kind="coordination_summary")
    print(text[:6000])
    print(json.dumps({"deliver": result}, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
