"""Deterministic resource audit; never invokes an LLM or repairs unrelated services."""
from __future__ import annotations

import hashlib
import ast
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from raphiia_openai import mongo_store
from inneros_core_runtime import execution_resource_guard as guard

KEY = "execution_resource_audit"
HOOKS = (
    ("cursor_headless_executor.py", "execute_claimed_task", "guard_execution"),
    ("interactive_provider_bounded_executor.py", "execute_claimed_task", "guard_execution"),
    ("dev_swarm_scheduler.py", "_execute_existing_worker_generic", "guard_execution"),
    ("temporal_activities.py", "_execute_budgeted_internal_graph", "guard_execution"),
    ("local_model_router.py", "run_local_model", "guard_local_inference"),
)


def source_findings(root=None):
    root = root or Path(__file__).resolve().parent
    notices = []
    for filename, name, decorator in HOOKS:
        try:
            tree = ast.parse((root / filename).read_text(encoding="utf-8"))
            fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
            decorators = [n.func if isinstance(n, ast.Call) else n for n in fn.decorator_list]
            if any(isinstance(n, ast.Name) and n.id == decorator for n in decorators):
                continue
        except (OSError, SyntaxError, StopIteration):
            pass
        notices.append({"task_id": f"runtime:{filename}:{name}", "reason": "resource_guard_hook_missing"})
    return notices


def findings(tasks, now):
    notices = []
    for task in tasks:
        tid = task.get("task_id")
        ledger = task.get("resource_guard") or {}
        reason = None
        if task.get("superseded_by"):
            reason = "active_task_superseded"
        elif ledger.get("active_token"):
            try:
                age = (now - datetime.fromisoformat(ledger["started_at"])).total_seconds()
                if age > guard.MAX_TASK_SECONDS:
                    reason = "execution_exceeded_wall_time"
            except (ValueError, TypeError, KeyError):
                reason = "execution_started_at_invalid"
        elif ledger.get("attempts", 0) >= guard.MAX_EXECUTIONS and ledger.get("last_outcome") != "success":
            reason = "execution_attempt_budget_exhausted"
        if reason:
            notices.append({"task_id": tid, "reason": reason})
    return sorted(notices, key=lambda row: str(row["task_id"]))


def run(*, notify=False):
    db = mongo_store.get_db()
    rows = list(db[guard.TASKS].find({"status": {"$in": ["claimed", "running", "in_progress", "proposed"]}}))
    missing_hooks = source_findings()
    notices = findings(rows, datetime.now(timezone.utc)) + missing_hooks
    if missing_hooks:
        # Latch closed until reviewed repair; source drift must not renew spend.
        mongo_store.upsert_coordination_state(key=guard.CONTROL_KEY, data={
            "block_new_work": True, "reason": "resource_guard_hook_missing",
        })
        subprocess.run([
            "systemctl", "--user", "stop", "inneros-cursor-headless-autopilot.timer",
            "inneros-ag25-project-cycle.timer", "ralfia-external-repair-agent.service",
        ], capture_output=True, timeout=15, check=False)
    fingerprint = hashlib.sha256(json.dumps(notices, sort_keys=True).encode()).hexdigest()
    old = mongo_store.get_coordination_state(KEY)
    previous = old.get("state") or {}
    attempts = int(previous.get("notification_attempts") or 0) if previous.get("fingerprint") == fingerprint else 0
    delivered = bool(previous.get("notification_delivered")) if previous.get("fingerprint") == fingerprint else False
    if notices and notify and not delivered and attempts < 3:
        from inneros_core_runtime import homeassistant_client as ha
        message = "InnerOS detuvo o detectó trabajo fuera de límites. " + "; ".join(
            f"{n['task_id']}: {n['reason']}" for n in notices[:5]
        )
        service = (os.getenv("OPS_HA_NOTIFY_SERVICE") or os.getenv("AMBIENT_GUARDIAN_MOBILE_NOTIFY_SERVICE") or "mobile_app_infinix_x6873").removeprefix("notify.")
        result = ha.call_service("notify", service, data={
            "title": "InnerOS: revisar límites de ejecución", "message": message,
            "data": {"tag": KEY, "priority": "high", "ttl": 3600},
        })
        delivered = bool(result.get("ok")); attempts += 1
    report = {"ok": not notices, "at": datetime.now(timezone.utc).isoformat(),
              "inspected_tasks": len(rows), "findings": notices,
              "fingerprint": fingerprint, "notification_attempts": attempts,
              "notification_delivered": delivered,
              "scope": "InnerOS guarded executors; direct IDE/API calls are outside this audit"}
    mongo_store.upsert_coordination_state(key=KEY, data=report)
    return report
