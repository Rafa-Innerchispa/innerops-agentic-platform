#!/usr/bin/env python3
"""HA Cursor headless autopilot: AMD + Intel, concurrent lanes, vault API key."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_api_credentials as cac
from inneros_core_runtime import cursor_execution_plane as cep
from inneros_core_runtime import cursor_headless_lanes as lanes
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime.ops_auto_claim_admission import (
    claim_admission,
    maybe_record_autopilot_owner_auth,
    pending_admission_summary,
)
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime.memory import agent_messages as am
from raphiia_openai import mongo_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_claim_enabled() -> bool:
    return os.getenv("INNEROS_CURSOR_AUTO_CLAIM", "1").strip().lower() in {"1", "true", "yes"}


def _execute_enabled() -> bool:
    return os.getenv("INNEROS_CURSOR_HEADLESS_EXECUTE", "1").strip().lower() in {"1", "true", "yes"}


def _notify(text: str) -> dict[str, Any]:
    if os.getenv("CURSOR_OPS_NOTIFY_WHATSAPP", "1") != "1":
        return {"ok": False, "skipped": "disabled"}
    try:
        from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

        return send_alert_whatsapp(text, prefix_node=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _missing_key_alert_once() -> dict[str, Any]:
    if cac.cursor_api_key_status().get("present"):
        return {"ok": True, "skipped": "key_present"}
    try:
        row = mongo_store.get_coordination_state("cursor_api_key_missing_alert")
        last = (row.get("state") or {}).get("last_sent_at") or ""
        if last:
            ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - ts).total_seconds() < 86400:
                return {"ok": True, "skipped": "cooldown"}
    except Exception:
        pass
    wa = _notify(
        "🔑 InnerOS Cursor: falta CURSOR_API_KEY (vault). "
        "Guarda con inneros_store_cursor_api_key.py en cualquier nodo."
    )
    try:
        mongo_store.upsert_coordination_state(
            key="cursor_api_key_missing_alert",
            data={"last_sent_at": _now(), "whatsapp": wa},
        )
    except Exception:
        pass
    return wa


def _task_auto_ok(task: dict[str, Any]) -> bool:
    payload = dict(task.get("payload") or {})
    if payload.get("do_not_auto_dispatch"):
        return False
    if payload.get("cursor_auto_execute") or payload.get("headless_auto"):
        return True
    return bool(task.get("owner_authorized_at")) and str(task.get("assignee") or task.get("assigned_to") or "").lower() == "cursor"


def _host_owns_task(task: dict[str, Any]) -> bool:
    owner = str(task.get("cursor_execution_host") or task.get("headless_execution_host") or "").lower()
    if not owner:
        return True
    h = lanes.hostname()
    return owner in h or h in owner or lanes.node_role() in owner


def _headless_max_reaps() -> int:
    try:
        return max(1, int(os.getenv("INNEROS_CURSOR_HEADLESS_MAX_REAPS", "3")))
    except Exception:
        return 3


def _reap_stale_headless_lanes() -> list[dict[str, Any]]:
    """Recover a claimed lane when its background worker vanished.

    A dead worker must not leave the task permanently stuck with
    headless_execution_started_at set. For bounded retries we clear the active
    attempt markers so the same claim/worktree can be resumed by this host.
    After the retry budget is exhausted, release the claim and block the task
    with explicit evidence instead of respawning forever.
    """
    import os as _os

    db = mongo_store.get_db()
    h = lanes.hostname()
    filt = {
        "assignee": "cursor",
        "headless_execution_started_at": {"$exists": True},
        "headless_execution_finished_at": {"$exists": False},
        "$or": [
            {"headless_execution_host": h},
            {"headless_execution_host": {"$regex": h.split(".")[0], "$options": "i"}},
        ],
    }
    reaped: list[dict[str, Any]] = []
    projection = {
        "_id": 0,
        "task_id": 1,
        "headless_execution_pid": 1,
        "headless_reap_count": 1,
        "claim_token": 1,
        "status": 1,
    }
    for row in db[OPS_TASKS_COL].find(filt, projection):
        pid = int(row.get("headless_execution_pid") or 0)
        if pid > 0 and _os.path.exists(f"/proc/{pid}"):
            continue

        tid = str(row.get("task_id") or "")
        now = _now()
        reap_count = int(row.get("headless_reap_count") or 0) + 1
        exhausted = reap_count >= _headless_max_reaps()

        if exhausted:
            full = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
            wt = full.get("worktree") or full.get("local_worktree")
            release_instead = bool(wt) or full.get("do_not_auto_dispatch") is True
            if release_instead:
                from inneros_core_runtime.cursor_ops_runner import _release_claim

                _release_claim(db, tid, reason="stale_headless_retry_exhausted")
                db[OPS_TASKS_COL].update_one(
                    {"task_id": tid},
                    {
                        "$set": {
                            "headless_execution_finished_at": now,
                            "headless_last_result": {
                                "ok": False,
                                "error": "stale_headless_retry_exhausted_released",
                                "reaped_at": now,
                                "reap_count": reap_count,
                            },
                            "headless_reap_count": reap_count,
                            "updated_at": now,
                        },
                        "$unset": {
                            "headless_execution_started_at": "",
                            "headless_execution_pid": "",
                            "headless_execution_unit": "",
                            "headless_execution_host": "",
                        },
                        "$inc": {"revision": 1},
                    },
                )
                reaped.append(
                    {
                        "task_id": tid,
                        "reaped": True,
                        "pid": pid,
                        "reap_count": reap_count,
                        "retry_exhausted": True,
                        "released_claim": True,
                    }
                )
                continue
            update = {
                "$set": {
                    "status": "blocked",
                    "headless_execution_finished_at": now,
                    "headless_last_result": {
                        "ok": False,
                        "error": "stale_headless_retry_exhausted",
                        "reaped_at": now,
                        "reap_count": reap_count,
                    },
                    "claim_error": "stale_headless_retry_exhausted",
                    "headless_reap_count": reap_count,
                    "updated_at": now,
                },
                "$unset": {
                    "claim_token": "",
                    "claimed_at": "",
                    "lease_until": "",
                    "headless_execution_started_at": "",
                    "headless_execution_pid": "",
                    "headless_execution_unit": "",
                    "headless_execution_host": "",
                },
                "$inc": {"revision": 1},
            }
        else:
            update = {
                "$set": {
                    "headless_last_result": {
                        "ok": False,
                        "error": "stale_headless_pid_reaped",
                        "reaped_at": now,
                        "reap_count": reap_count,
                    },
                    "headless_reap_count": reap_count,
                    "headless_last_reaped_at": now,
                    "updated_at": now,
                },
                "$unset": {
                    "headless_execution_started_at": "",
                    "headless_execution_finished_at": "",
                    "headless_execution_pid": "",
                    "headless_execution_unit": "",
                    "headless_execution_host": "",
                },
                "$inc": {"revision": 1},
            }

        db[OPS_TASKS_COL].update_one({"task_id": tid}, update)
        reaped.append(
            {
                "task_id": tid,
                "reaped": True,
                "pid": pid,
                "reap_count": reap_count,
                "retry_exhausted": exhausted,
            }
        )
    return reaped

def _find_resume_on_host(limit: int) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    h = lanes.hostname()
    filt = {
        "status": {"$in": ["in_progress", "claimed", "failed", "verification"]},
        "assignee": "cursor",
        "claim_token": {"$exists": True},
        "headless_execution_started_at": {"$exists": False},
    }
    rows = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("updated_at", 1).limit(max(limit, 1) * 3))
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("do_not_auto_dispatch") is True:
            continue
        hl = row.get("headless_last_result") or {}
        if hl.get("completion_policy_blocked") is True:
            continue
        claim_host = str(row.get("claim_host") or "").lower()
        if claim_host and claim_host not in h and h not in claim_host:
            allowed, _ = lanes.should_this_node_run_task(row)
            if not allowed:
                continue
        elif not _host_owns_task(row):
            allowed, _ = lanes.should_this_node_run_task(row)
            if not allowed:
                continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _spawn_background_execution(task_id: str) -> dict[str, Any]:
    from inneros_core_runtime.cursor_headless_dispatch import spawn_headless_execute

    return spawn_headless_execute(task_id)


def _claim_from_task_doc(task: dict[str, Any]) -> dict[str, Any]:
    allowed, reason = lanes.should_this_node_run_task(task)
    if not allowed:
        return {"ok": False, "error": "routing_skip", "reason": reason, "task_id": task.get("task_id")}
    tid = str(task.get("task_id") or "")
    claim = cor.claim_ops_task(task_id=tid, owner_approved=True, owner_actor="INNEROS_HEADLESS_AUTOPILOT")
    if claim.get("ok"):
        mongo_store.get_db()[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {
                "$set": {
                    "cursor_execution_host": lanes.hostname(),
                    "cursor_execution_role": lanes.node_role(),
                    "updated_at": _now(),
                },
                "$inc": {"revision": 1},
            },
        )
    return claim


def run(*, auto_claim: bool | None = None, execute: bool | None = None, limit: int = 8) -> dict:
    if auto_claim is None:
        auto_claim = _auto_claim_enabled()
    if execute is None:
        execute = _execute_enabled()

    if not lanes.is_ha_execution_node():
        return {"ok": True, "skipped": "not_ha_execution_node", "host": lanes.hostname()}

    # The autopilot timer is a dispatcher, not an authenticated Cursor IDE
    # session or an inbox consumer. It must not create either heartbeat.
    lanes.touch_node_liveness()
    reaped_lanes = _reap_stale_headless_lanes()

    status = lanes.lane_status()
    key_status = cac.cursor_api_key_status()
    out: dict[str, Any] = {
        "ok": True,
        "lanes": status,
        "reaped_lanes": reaped_lanes,
        "api_key": {"present": key_status.get("present"), "source": key_status.get("source")},
        "auto_claim": auto_claim,
        "execute": execute,
        "pinned_model": cor.CURSOR_PINNED_MODEL,
        "spawned": [],
        "claims": [],
    }

    if execute and not key_status.get("present"):
        out["missing_key"] = _missing_key_alert_once()
        execute = False
        out["execute"] = False
        out["execution_blocker"] = "cursor_api_key_missing"

    slots = status.get("available_slots") or 0
    if execute and slots > 0:
        for task in _find_resume_on_host(slots):
            if lanes.available_slots() <= 0:
                break
            sp = _spawn_background_execution(str(task.get("task_id")))
            out["spawned"].append(sp)

    slots = lanes.available_slots()
    if auto_claim:
        listed = cor.list_claimable_ops_tasks(limit=limit)
        full_tasks = [mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": stub.get("task_id")}, {"_id": 0}) for stub in (listed.get("tasks") or [])]
        full_tasks = [task for task in full_tasks if task]
        out["admission"] = pending_admission_summary(full_tasks, provider="cursor", ready=bool(execute and slots > 0), not_ready_reason="cursor_api_key_missing" if not key_status.get("present") else "no_available_execution_slots")
    if auto_claim and execute and slots > 0:
        for stub in listed.get("tasks") or []:
            if lanes.available_slots() <= 0:
                break
            full = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": stub.get("task_id")}, {"_id": 0})
            if not full or not _task_auto_ok(full):
                continue
            maybe_record_autopilot_owner_auth(full, provider="cursor")
            full = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": stub.get("task_id")}, {"_id": 0}) or full
            if not claim_admission(full, provider="cursor", ready=True).get("eligible"):
                continue
            claim = _claim_from_task_doc(full)
            out["claims"].append(claim)
            if not claim.get("ok"):
                continue
            am.create_agent_message(
                from_agent="inneros",
                target_agent="cursor",
                title=f"HA claim · {claim.get('task_id')} @ {lanes.node_role()}",
                body=f"Auto-claim\n{claim.get('task_id')}\nhost={lanes.hostname()}",
                correlation_id=str(claim.get("correlation_id") or ""),
                message_type="task",
                payload={
                    "task_id": claim.get("task_id"),
                    "claim_token": claim.get("claim_token"),
                    "headless_autopilot": True,
                    "execution_role": lanes.node_role(),
                },
                idempotency_key=f"ha-autopilot-{claim.get('task_id')}-{claim.get('claim_token')}",
            )
            if lanes.available_slots() > 0:
                sp = _spawn_background_execution(str(claim.get("task_id")))
                out["spawned"].append(sp)

    if not out["spawned"] and not out["claims"]:
        out["idle"] = True
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor HA headless autopilot")
    parser.add_argument("--no-claim", action="store_true")
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    out = run(
        auto_claim=not args.no_claim,
        execute=False if args.no_execute else None,
        limit=max(1, min(args.limit, 20)),
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
