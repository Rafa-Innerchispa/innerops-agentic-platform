#!/usr/bin/env python3
"""Run headless SDK execution for one claimed Cursor ops task (background worker)."""
from __future__ import annotations

import argparse
import json
import os
import signal
from contextlib import contextmanager
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_headless_executor as che
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime import execution_receipts as receipts
from inneros_core_runtime import platform_local_headless_executor as plhe
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


@contextmanager
def _bounded_sdk_run(seconds: int):
    """Bound a headless Cursor SDK invocation on Linux AMD/Intel."""
    def deadline(_signum, _frame):
        raise TimeoutError("cursor_headless_sdk_deadline_exceeded")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, max(60, min(seconds, 1800)))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
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
    worktree = Path(str(claim.get("worktree") or ROOT))
    before_sha = receipts.git_head(worktree)
    _notify(
        f"Cursor [{_host()}] starting {tid}: "
        f"{str(claim.get('title') or '')[:80]}"
    )

    result: dict = {}
    complete: dict | None = None
    reason = ""
    proof: dict = {}
    submitted_status = "failed"
    try:
        if plhe.offers_local_execution(task):
            result = plhe.run_platform_work(
                task,
                worktree=worktree,
                platform_root=ROOT,
            )
        else:
            raw_timeout = os.getenv("INNEROS_CURSOR_SDK_TIMEOUT_SECONDS", "420")
            try:
                timeout = int(raw_timeout)
            except ValueError:
                timeout = 420
            try:
                with _bounded_sdk_run(timeout):
                    result = che.execute_claimed_task(claim)
            except TimeoutError:
                result = {"ok": False, "error": "cursor_sdk_timeout", "primary": "local_sdk"}
            except Exception as exc:
                result = {"ok": False, "error": "cursor_sdk_exception_" + type(exc).__name__}

        if result.get("ok") and result.get("primary") == "platform_local_pytest":
            proof = dict(result.get("test_results") or {})
            main_sha = receipts.git_head(ROOT)
            evidence = {
                "test_results": proof,
                "notes": str(result.get("pytest_tail") or "")[:2000],
                "headless_primary": "platform_local_pytest",
                "execution_host": _host(),
                "git_head_sha": receipts.git_head(worktree),
                "runtime_main_sha": main_sha,
                "commit_sha": main_sha,
            }
            token = str(claim.get("claim_token") or "")
            if token:
                complete = cor.complete_ops_task(
                    tid,
                    claim_token=token,
                    status="completed",
                    evidence=evidence,
                    commit_sha=main_sha,
                )
            if complete and complete.get("ok"):
                submitted_status = "verification"
            else:
                reason = str((complete or {}).get("error") or "completion_signal_missing")
        elif result.get("ok") and result.get("primary") == "local_sdk":
            proof = receipts.committed_objective_receipt(worktree, before_sha)
            if proof.get("ok"):
                evidence = {
                    **proof,
                    "notes": str(result.get("local", {}).get("result") or "")[:2000],
                    "headless_primary": "local_sdk",
                    "execution_host": _host(),
                }
                token = str(claim.get("claim_token") or "")
                if token:
                    complete = cor.complete_ops_task(
                        tid, claim_token=token, status="completed", evidence=evidence,
                        commit_sha=str(proof["commit_sha"]),
                    )
                if complete and complete.get("ok"):
                    submitted_status = "verification"
                else:
                    reason = str((complete or {}).get("error") or "completion_signal_missing")
            else:
                reason = str(proof.get("error") or "no_objective_evidence")
        elif result.get("ok") and result.get("primary") == "cloud_agent":
            # Cursor Cloud agent creation is asynchronous, not execution success.
            reason = "cloud_agent_async_submission_not_verified"
        else:
            reason = str(
                result.get("error")
                or result.get("pytest_tail")
                or "headless_dispatch_failed"
            )[:500]

        if submitted_status != "verification":
            # A real negative result, not an invented successful completion.
            token = str(claim.get("claim_token") or "")
            if token:
                failed = cor.complete_ops_task(
                    tid, claim_token=token, status="failed",
                    evidence={"notes": reason, "execution_host": _host(),
                              "headless_primary": result.get("primary"),
                              "git_before_sha": before_sha},
                )
                if failed.get("ok"):
                    complete = failed
                elif complete is None:
                    complete = failed
            _notify(f"Cursor {tid} could not verify completion: {reason[:120]}")
        else:
            _notify(f"Cursor {tid} submitted verified file evidence to Temporal")
    finally:
        finished_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        successful_submission = bool(
            submitted_status == "verification" and complete and complete.get("ok")
        )
        summary = {
            "ok": successful_submission,
            "sdk_ok": bool(result.get("ok")),
            "primary": result.get("primary"),
            "evidence_ok": bool(proof.get("ok")),
            "completion_submitted": successful_submission,
            "completion_status": (complete or {}).get("status"),
            "error": reason or (complete or {}).get("error"),
        }
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {
                "$set": {
                    "headless_execution_finished_at": finished_at,
                    "headless_last_result": summary,
                    "headless_evidence_receipt": proof,
                },
                "$inc": {"revision": 1},
            },
        )
    out = {"ok": submitted_status == "verification", "result": result,
           "receipt": proof, "complete": complete, "error": reason or None}
    print(json.dumps(out, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
