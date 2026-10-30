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
from inneros_core_runtime.cursor_headless_policy import headless_denial
from raphiia_openai import mongo_store


def _host() -> str:
    return socket.gethostname().lower()



def _reload_task(tid: str) -> dict:
    return mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}


def _complete_with_live_token(
    tid: str,
    *,
    status: str,
    evidence: dict | None = None,
    commit_sha: str | None = None,
) -> dict:
    task = _reload_task(tid)
    token = str(task.get("claim_token") or "").strip()
    if not token:
        return {"ok": False, "error": "claim_token_missing_for_complete", "task_id": tid}
    cor.renew_ops_lease(tid, token)
    return cor.complete_ops_task(
        tid,
        claim_token=token,
        status=status,
        evidence=evidence,
        commit_sha=commit_sha,
    )

def _completion_policy_gate_error(message: str) -> bool:
    from inneros_core_runtime import ops_deploy_execution_pause as odep

    return odep.completion_policy_blocked_message(message)


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

    denied = headless_denial(task, check_budget=False)
    if denied:
        print(json.dumps({"ok": False, "task_id": tid, "error": denied}))
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
    worktree = Path(str(claim.get("worktree") or "")).expanduser()
    if not worktree.is_dir() or not (worktree / ".git").exists():
        err = f"worktree_missing_or_invalid:{worktree}"
        _notify(f"Cursor {tid} abort: {err}")
        print(json.dumps({"ok": False, "error": err}))
        return 2
    before_sha = receipts.git_head(worktree)
    token = str(claim.get("claim_token") or task.get("claim_token") or "")
    if token:
        cor.renew_ops_lease(tid, token)
        cor.heartbeat_ops_task(tid, actor="cursor", phase="headless_worker_start", last_progress="headless execute_one started")
    _notify(
        f"Cursor [{_host()}] starting {tid}: "
        f"{str(claim.get('title') or '')[:80]}"
    )

    result: dict = {}
    complete: dict | None = None
    reason = ""
    proof: dict = {}
    submitted_status = "failed"
    # Cancellation may arrive after spawn; reject before any paid invocation.
    denied = headless_denial(_reload_task(tid), check_budget=False)
    if denied:
        print(json.dumps({"ok": False, "task_id": tid, "error": denied}))
        return 2
    try:
        if plhe.offers_local_execution(task):
            result = plhe.run_platform_work(
                task,
                worktree=worktree,
                platform_root=ROOT,
            )
        else:
            raw_timeout = os.getenv("INNEROS_CURSOR_SDK_TIMEOUT_SECONDS", "900")
            try:
                timeout = int(raw_timeout)
            except ValueError:
                timeout = 900
            try:
                with _bounded_sdk_run(timeout):
                    result = che.execute_claimed_task(claim)
            except TimeoutError:
                result = {"ok": False, "error": "cursor_headless_sdk_deadline_exceeded", "primary": "local_sdk"}
            except Exception as exc:
                result = {"ok": False, "error": "cursor_sdk_exception_" + type(exc).__name__}

        if result.get("ok") and result.get("primary") == "platform_local_pytest":
            proof = dict(result.get("test_results") or {})
            main_sha = receipts.git_head(ROOT)
            evidence = receipts.attach_runner_test_results(
                {
                    "test_results": proof,
                    "notes": str(result.get("pytest_tail") or "")[:2000],
                    "headless_primary": "platform_local_pytest",
                    "execution_host": _host(),
                    "git_head_sha": receipts.git_head(worktree),
                    "runtime_main_sha": main_sha,
                    "commit_sha": main_sha,
                },
                result,
            )
            token = str(claim.get("claim_token") or "")
            if token:
                complete = _complete_with_live_token(
                    tid,
                    status="completed",
                    evidence=evidence,
                    commit_sha=main_sha,
                )
            if complete and complete.get("ok"):
                submitted_status = "verification"
            else:
                reason = str((complete or {}).get("error") or "completion_signal_missing")
        elif result.get("ok") and result.get("primary") == "local_sdk":
            from inneros_core_runtime import ops_completion_policy as ocp
            from inneros_core_runtime import ops_execution_state as oes

            proof = receipts.committed_objective_receipt(worktree, before_sha)
            notes = str(result.get("local", {}).get("result") or "")[:2000]
            evidence = {}
            if proof.get("ok"):
                evidence = receipts.attach_runner_test_results(
                    {
                        **proof,
                        "notes": notes,
                        "headless_primary": "local_sdk",
                        "execution_host": _host(),
                    },
                    result,
                )
            elif ocp.allows_non_commit_completion(task, {"notes": notes}):
                evidence = {
                    "read_only_completion": True,
                    "completion_mode": "read_only_evidence",
                    "git_before_sha": before_sha,
                    "commit_sha": receipts.git_head(worktree) or before_sha,
                    "notes": notes,
                    "summary": notes[:800],
                    "headless_primary": "local_sdk",
                    "execution_host": _host(),
                }
                proof = {"ok": True, "read_only": True}
            else:
                reason = str(proof.get("error") or "no_objective_evidence")
            if evidence:
                token = str(claim.get("claim_token") or "")
                if token:
                    complete = _complete_with_live_token(
                    tid,
                    status="completed",
                        evidence=evidence,
                        commit_sha=str(evidence.get("commit_sha") or "") or None,
                    )
                if complete and complete.get("ok"):
                    submitted_status = "verification"
                    oes.refresh_current_execution_state(
                        {**task, "status": "verification"},
                        event="headless_complete",
                        actor="cursor",
                    )
                else:
                    reason = str((complete or {}).get("error") or "completion_signal_missing")
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
                gate_msg = reason or str((complete or {}).get("error") or "")
                terminal_status = "blocked" if _completion_policy_gate_error(gate_msg) else "failed"
                fail_evidence = {
                    "notes": gate_msg or reason,
                    "execution_host": _host(),
                    "headless_primary": result.get("primary"),
                    "git_before_sha": before_sha,
                }
                tr = (complete or {}).get("evidence") or {}
                if isinstance(tr, dict) and isinstance(tr.get("test_results"), dict):
                    fail_evidence["test_results"] = tr["test_results"]
                else:
                    runner_tr = receipts.runner_test_results_payload(result)
                    if runner_tr:
                        fail_evidence["test_results"] = runner_tr
                failed = _complete_with_live_token(
                    tid,
                    status=terminal_status,
                    evidence=fail_evidence,
                )
                if failed.get("ok"):
                    complete = failed
                elif complete is None:
                    complete = failed
            _notify(f"Cursor {tid} could not verify completion: {reason[:120]}")
        else:
            _notify(f"Cursor {tid} submitted verified file evidence to Temporal")
            try:
                from inneros_core_runtime.notifications.ops_task_alerts import notify_ops_transition
                task_done = _reload_task(tid)
                notify_ops_transition(task_done, previous_status=str(task.get("status") or ""), actor="cursor_headless")
            except Exception:
                pass
        if submitted_status != "verification":
            fail_msg = reason or str((complete or {}).get("error") or "headless_not_verified")
            _notify(f"Cursor [{_host()}] {tid} sin cierre OK: {fail_msg[:180]}")

    finally:
        finished_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        successful_submission = bool(
            submitted_status == "verification" and complete and complete.get("ok")
        )
        test_results_summary: dict = {}
        if isinstance(complete, dict):
            ev_done = complete.get("evidence") if isinstance(complete.get("evidence"), dict) else {}
            if isinstance(ev_done.get("test_results"), dict):
                test_results_summary = ev_done["test_results"]
        if not test_results_summary and isinstance(proof, dict):
            if isinstance(proof.get("test_results"), dict):
                test_results_summary = proof["test_results"]
        if not test_results_summary:
            runner_tr = receipts.runner_test_results_payload(result)
            if runner_tr:
                test_results_summary = runner_tr
        gate_error = None if successful_submission else (reason or (complete or {}).get("error"))
        summary = {
            "ok": successful_submission,
            "sdk_ok": bool(result.get("ok")),
            "primary": result.get("primary"),
            "evidence_ok": bool(proof.get("ok")),
            "completion_submitted": successful_submission,
            "completion_status": (complete or {}).get("status"),
            "error": gate_error,
            "test_results": test_results_summary,
        }
        if gate_error and _completion_policy_gate_error(str(gate_error)):
            summary["completion_policy_blocked"] = True
        mongo_set: dict = {
            "headless_execution_finished_at": finished_at,
            "headless_last_result": summary,
            "headless_evidence_receipt": proof,
        }
        if summary.get("completion_policy_blocked"):
            mongo_set["do_not_auto_dispatch"] = True
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {
                "$set": mongo_set,
                "$inc": {"revision": 1},
            },
        )
    out = {"ok": submitted_status == "verification", "result": result,
           "receipt": proof, "complete": complete, "error": reason or None}
    print(json.dumps(out, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
