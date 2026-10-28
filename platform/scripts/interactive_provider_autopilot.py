#!/usr/bin/env python3
"""Autopilot: Codex + Antigravity — auto-claim eligible ops + competition dispatch."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import competition_lane_dispatch as cld
from inneros_core_runtime import interactive_ops_runner as ior
from inneros_core_runtime import interactive_provider_lanes as ipl
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime.ops_auto_claim_admission import (
    claim_admission,
    maybe_record_autopilot_owner_auth,
    pending_admission_summary,
)
from raphiia_openai import mongo_store

PROVIDERS = ("codex", "antigravity")


def _auto_claim_enabled() -> bool:
    return os.getenv("INNEROS_INTERACTIVE_AUTO_CLAIM", "1").strip().lower() in {"1", "true", "yes", "on"}


def _claimed_tasks(provider: str, limit: int = 5) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    filt = {
        "assignee": provider,
        "status": {"$in": ["claimed", "in_progress", "running"]},
        "claim_token": {"$exists": True},
        "owner_authorized_at": {"$exists": True},
        "provider_execution_started_at": {"$exists": False},
    }
    return list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("claimed_at", 1).limit(limit))


def _auto_claim_batch(provider: str, slots: int) -> dict[str, Any]:
    db = mongo_store.get_db()
    listed = ior.list_claimable_ops_tasks(provider=provider, limit=max(slots * 4, 8))
    stubs = listed.get("tasks") or []
    claims: list[dict[str, Any]] = []
    full_tasks: list[dict[str, Any]] = []
    for stub in stubs:
        tid = str(stub.get("task_id") or "")
        if not tid:
            continue
        full = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
        if full:
            full_tasks.append(full)
    admission = pending_admission_summary(full_tasks, provider=provider, ready=True)
    for full in full_tasks:
        if ipl.available_slots(provider) <= 0:
            break
        maybe_record_autopilot_owner_auth(full, provider=provider)
        full = db[OPS_TASKS_COL].find_one({"task_id": full.get("task_id")}, {"_id": 0}) or full
        decision = claim_admission(full, provider=provider, ready=True)
        if not decision.get("eligible"):
            continue
        tid = str(full.get("task_id") or "")
        claim = ior.claim_ops_task(
            provider,
            task_id=tid,
            owner_approved=True,
            owner_actor=str(os.getenv("RALFIA_OWNER_ID") or "INNEROS_AUTOPILOT"),
        )
        claims.append(claim)
    return {"claims": claims, "admission": admission}


def _tick_provider(provider: str) -> dict[str, Any]:
    ipl.touch_node_liveness(provider)
    slots = ipl.available_slots(provider)
    out: dict[str, Any] = {
        "ok": True,
        "provider": provider,
        "lanes": ipl.lane_status(provider),
        "auto_claim_enabled": _auto_claim_enabled(),
    }
    if slots <= 0:
        out.update({"idle": True, "reason": "no_slots", "started": [], "claims": []})
        return out

    claims_report: dict[str, Any] = {"claims": [], "admission": {}}
    if _auto_claim_enabled():
        claims_report = _auto_claim_batch(provider, slots)
        out["claims"] = claims_report.get("claims") or []
        out["admission"] = claims_report.get("admission") or {}

    started = []
    for task in _claimed_tasks(provider, limit=slots):
        ok, reason = ipl.should_this_node_run_task(provider, task)
        if not ok:
            continue
        tid = str(task.get("task_id") or "")
        if cld.is_competition_task(task):
            spawn = cld.spawn_competition_execute(tid)
        elif provider == "antigravity" and os.getenv(
            "INNEROS_ANTIGRAVITY_SPAWN_ON_CLAIM", "1"
        ).strip().lower() in {"1", "true", "yes", "on"}:
            from inneros_core_runtime import antigravity_headless_dispatch as agd

            spawn = agd.spawn_headless_execute(tid)
        else:
            continue
        started.append({"task_id": tid, "spawn": spawn})
        if len(started) >= slots:
            break
    out["started"] = started
    out["idle"] = not started and not (out.get("claims") or [])
    return out


def main() -> int:
    report = {p: _tick_provider(p) for p in PROVIDERS}
    print(json.dumps({"ok": True, "report": report}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
