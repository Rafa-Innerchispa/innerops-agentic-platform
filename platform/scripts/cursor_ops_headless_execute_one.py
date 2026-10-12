#!/usr/bin/env python3
"""Run headless SDK execution for one claimed Cursor ops task (background worker)."""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_headless_executor as che
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store


def _host() -> str:
    return socket.gethostname().lower()


def _notify(text: str) -> None:
    if __import__("os").getenv("CURSOR_OPS_NOTIFY_WHATSAPP", "1") != "1":
        return
    try:
        from raphiia_openai.notifications.evolution_client import send_alert_whatsapp

        send_alert_whatsapp(text, prefix_node=True)
    except Exception:
        pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    args = p.parse_args()
    tid = args.task_id.strip()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        print(json.dumps({"ok": False, "error": "task_not_found"}))
        return 2
    claim = {
        "ok": True,
        "task_id": tid,
        "claim_token": task.get("claim_token"),
        "worktree": task.get("worktree") or task.get("local_worktree"),
        "repo": task.get("repo"),
        "work_branch": task.get("work_branch"),
        "title": task.get("title"),
        "objective": task.get("objective") or task.get("title"),
        "pinned_model": task.get("effective_model") or cor.CURSOR_PINNED_MODEL,
    }
    _notify(
        f"▶️ Cursor [{_host()}]\n{tid}\n{str(claim.get('title') or '')[:80]}\n"
        f"Modelo: {claim.get('pinned_model')}"
    )
    result = che.execute_claimed_task(claim)
    complete = None
    if result.get("ok"):
        cwd = Path(str(claim.get("worktree") or ROOT))
        sha = str(result.get("sha") or che.git_head_sha(cwd))
        tok = str(claim.get("claim_token") or "")
        evidence = {
            "commit_sha": sha or None,
            "notes": str(result.get("local", {}).get("result") or result.get("cloud", {}))[:2000],
            "headless_primary": result.get("primary"),
            "execution_host": _host(),
        }
        if tok and sha:
            complete = cor.complete_ops_task(
                tid, claim_token=tok, status="completed", evidence=evidence, commit_sha=sha
            )
        _notify(
            f"{'✅' if complete and complete.get('ok') else '⚠️'} Cursor [{_host()}] {tid}\n"
            f"SHA: {sha or '(sin commit)'}"
        )
    else:
        _notify(f"❌ Cursor [{_host()}] {tid}\n{str(result.get('error') or '')[:200]}")
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "headless_execution_finished_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "headless_last_result": {k: result.get(k) for k in ("ok", "primary", "error", "mode")},
            },
            "$inc": {"revision": 1},
        },
    )
    out = {"ok": bool(result.get("ok")), "result": result, "complete": complete}
    print(json.dumps(out, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
