#!/usr/bin/env python3
"""AMD-primary Cursor ops autopilot: delivery truth, auto-claim, SDK/cloud execution, WhatsApp."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_api_credentials as cac
from inneros_core_runtime import cursor_execution_plane as cep
from inneros_core_runtime import cursor_headless_executor as che
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime.memory import agent_messages as am
from raphiia_openai import mongo_store


def _hostname() -> str:
    return socket.gethostname().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_primary_execution_node() -> bool:
    role = (os.getenv("INNEROS_NODE_ROLE") or "").strip().lower()
    if role in {"amd", "gpu_worker", "primary"}:
        return True
    if role in {"intel", "secondary", "standby"}:
        return False
    forced = (os.getenv("INNEROS_CURSOR_EXECUTION_PRIMARY") or "").strip().lower()
    if forced in {"1", "true", "yes", "amd"}:
        return True
    if forced in {"0", "false", "intel", "secondary"}:
        return False
    return "amd" in _hostname() or "ralfiia-amd" in _hostname()


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
            from datetime import datetime, timezone

            ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - ts).total_seconds() < 86400:
                return {"ok": True, "skipped": "cooldown"}
    except Exception:
        pass
    msg = (
        "🔑 InnerOS Cursor: falta CURSOR_API_KEY para ejecución automática.\n"
        "1) cursor.com/dashboard → API Keys → crear User API Key (copia el secreto completo).\n"
        "2) En AMD: echo 'TU_KEY' | platform/venv/bin/python3 platform/scripts/inneros_store_cursor_api_key.py\n"
        "Autopilot ya está activo; cuando guardes la key, ejecutará ops Cursor autorizadas solas."
    )
    wa = _notify(msg)
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
    if bool(task.get("owner_authorized_at")):
        assignee = str(task.get("assignee") or task.get("assigned_to") or "").lower()
        if assignee == "cursor":
            return True
    return False


def _find_in_progress_pending() -> dict[str, Any] | None:
    db = mongo_store.get_db()
    filt = {
        "status": "in_progress",
        "assignee": "cursor",
        "claim_token": {"$exists": True},
        "$or": [
            {"headless_execution_started_at": {"$exists": False}},
            {"headless_execution_finished_at": {"$exists": False}, "headless_execution_started_at": {"$exists": True}},
        ],
    }
    return db[OPS_TASKS_COL].find_one(filt, sort=[("updated_at", -1)])


def _mark_execution_started(tid: str) -> None:
    db = mongo_store.get_db()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {"$set": {"headless_execution_started_at": _now(), "updated_at": _now()}, "$inc": {"revision": 1}},
    )


def _mark_execution_finished(tid: str, *, result: dict[str, Any]) -> None:
    db = mongo_store.get_db()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "headless_execution_finished_at": _now(),
                "headless_last_result": {k: result.get(k) for k in ("ok", "primary", "error", "mode")},
                "updated_at": _now(),
            },
            "$inc": {"revision": 1},
        },
    )


def _claim_from_task_doc(task: dict[str, Any]) -> dict[str, Any]:
    tid = str(task.get("task_id") or "")
    return cor.claim_ops_task(task_id=tid, owner_approved=True, owner_actor="INNEROS_HEADLESS_AUTOPILOT")


def _run_execution(claim: dict[str, Any]) -> dict[str, Any]:
    tid = str(claim.get("task_id") or "")
    _mark_execution_started(tid)
    _notify(
        f"▶️ Cursor auto-ejecución\n{tid}\n{str(claim.get('title') or '')[:80]}\n"
        f"Modelo: {claim.get('pinned_model')}"
    )
    result = che.execute_claimed_task(claim)
    _mark_execution_finished(tid, result=result)
    complete = None
    if result.get("ok"):
        sha = str(result.get("sha") or che.git_head_sha(Path(str(claim.get("worktree") or ROOT))))
        evidence = {
            "commit_sha": sha or None,
            "notes": str(result.get("local", {}).get("result") or result.get("cloud", {}))[:2000],
            "headless_primary": result.get("primary"),
        }
        tok = str(claim.get("claim_token") or "")
        if tok and sha:
            complete = cor.complete_ops_task(
                tid,
                claim_token=tok,
                status="completed",
                evidence=evidence,
                commit_sha=sha,
            )
        elif tok:
            complete = {
                "ok": False,
                "error": "evidence_incomplete",
                "hint": "Ejecución OK pero sin commit_sha; revisar worktree o completar manual.",
            }
        _notify(
            f"{'✅' if complete and complete.get('ok') else '⚠️'} Cursor ops {tid}\n"
            f"Modo: {result.get('primary')}\n"
            f"SHA: {sha or '(sin commit)'}"
        )
    else:
        _notify(f"❌ Cursor auto-ejecución falló\n{tid}\n{str(result.get('error') or '')[:200]}")
    result["complete"] = complete
    return result


def run(*, auto_claim: bool | None = None, execute: bool | None = None, limit: int = 5) -> dict:
    if auto_claim is None:
        auto_claim = _auto_claim_enabled()
    if execute is None:
        execute = _execute_enabled()

    if not _is_primary_execution_node():
        return {
            "ok": True,
            "skipped": "not_primary_execution_node",
            "host": _hostname(),
        }

    cep.register_cursor_ide_session(
        host=_hostname(),
        source="cursor_private_worker",
        identity={"mailbox": "cursor", "role": "headless_autopilot", "host": _hostname()},
    )
    cep.register_cursor_consumer_heartbeat(
        identity={"mailbox": "cursor", "host": _hostname(), "role": "inbox_consumer"},
    )
    classified = cep.classify_cursor_execution()
    key_status = cac.cursor_api_key_status()

    out: dict[str, Any] = {
        "ok": True,
        "host": _hostname(),
        "classification": classified,
        "api_key": {"present": key_status.get("present"), "source": key_status.get("source")},
        "auto_claim": auto_claim,
        "execute": execute,
        "pinned_model": cor.CURSOR_PINNED_MODEL,
    }

    if execute and not key_status.get("present"):
        out["missing_key"] = _missing_key_alert_once()
        execute = False
        out["execute"] = False

    pending = _find_in_progress_pending()
    if pending and execute:
        claim = {
            "ok": True,
            "task_id": pending.get("task_id"),
            "claim_token": pending.get("claim_token"),
            "worktree": pending.get("worktree") or pending.get("local_worktree"),
            "repo": pending.get("repo"),
            "work_branch": pending.get("work_branch"),
            "title": pending.get("title"),
            "objective": pending.get("objective") or pending.get("title"),
            "pinned_model": pending.get("effective_model") or cor.CURSOR_PINNED_MODEL,
        }
        out["execution"] = _run_execution(claim)
        return out

    if not auto_claim:
        return out

    listed = cor.list_claimable_ops_tasks(limit=limit)
    tasks = [t for t in (listed.get("tasks") or []) if _task_auto_ok(t)]
    if not tasks:
        out["claim"] = {"ok": True, "claimed": False, "reason": "no_auto_eligible_tasks"}
        return out

    full = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tasks[0].get("task_id")}, {"_id": 0})
    if not full:
        out["claim"] = {"ok": False, "error": "task_doc_missing"}
        return out

    claim = _claim_from_task_doc(full)
    out["claim"] = claim
    if not claim.get("ok"):
        return out

    am.create_agent_message(
        from_agent="inneros",
        target_agent="cursor",
        title=f"Autopilot claim · {claim.get('task_id')}",
        body=f"Auto-claim headless\n{claim.get('task_id')}\n{(claim.get('objective') or '')[:3000]}",
        correlation_id=str(claim.get("correlation_id") or ""),
        message_type="task",
        payload={"task_id": claim.get("task_id"), "claim_token": claim.get("claim_token"), "headless_autopilot": True},
        idempotency_key=f"headless-autopilot-{claim.get('task_id')}-{claim.get('claim_token')}",
    )

    if execute:
        out["execution"] = _run_execution(claim)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor ops headless autopilot (AMD primary)")
    parser.add_argument("--no-claim", action="store_true")
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    out = run(
        auto_claim=not args.no_claim,
        execute=False if args.no_execute else None,
        limit=max(1, min(args.limit, 20)),
    )
    print(json.dumps(out, indent=2, default=str))
    if out.get("skipped") == "not_primary_execution_node":
        return 0
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
