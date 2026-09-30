#!/usr/bin/env python3
"""Run an isolated successful Temporal workflow and verify restart durability."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any

EXPECTED_ACK = "I_UNDERSTAND_ISOLATED_TEMPORAL_SUCCESS_RESTART_CANARY"
EXPECTED_DB = "pcdoctor_swarm_canary"
EXPECTED_QUEUE = "inneros-p0-canary"

if os.environ.get("INNEROS_P0_TEMPORAL_SUCCESS_ACK") != EXPECTED_ACK:
    raise SystemExit(f"REFUSED: set INNEROS_P0_TEMPORAL_SUCCESS_ACK={EXPECTED_ACK}")
if os.environ.get("INNEROS_MONGO_DB") != EXPECTED_DB:
    raise SystemExit(f"REFUSED: INNEROS_MONGO_DB must equal {EXPECTED_DB}")
if os.environ.get("INNEROS_TEMPORAL_TASK_QUEUE") != EXPECTED_QUEUE:
    raise SystemExit(f"REFUSED: INNEROS_TEMPORAL_TASK_QUEUE must equal {EXPECTED_QUEUE}")
if "/.canary/worktrees" not in os.environ.get("INNEROS_WORKTREE_BASE", ""):
    raise SystemExit("REFUSED: INNEROS_WORKTREE_BASE must be under .canary/worktrees")
if os.environ.get("INNEROS_NATS_ENABLED", "").lower() not in {"false", "0", "no", "off"}:
    raise SystemExit("REFUSED: INNEROS_NATS_ENABLED must be false")

from pymongo import MongoClient
from temporalio.client import Client

from inneros_core_runtime.durable_coordination_spine import (
    ack_durable_message,
    create_durable_message,
    query_durable_messages,
)
from inneros_core_runtime.temporal_workflows import OpsTaskWorkflow

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/rlopez/inneros/inneros_core/platform/venv/bin/python")
MONGO_URI = "mongodb://127.0.0.1:27017"
CANARY_DB = "pcdoctor_swarm_canary"
PRODUCTION_DB = "pcdoctor_swarm"
TASK_QUEUE = "inneros-p0-canary"
WORKTREE_BASE = Path(os.environ["INNEROS_WORKTREE_BASE"])
LOG_DIR = ROOT / ".canary"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def count_task_records(db: Any, task_id: str) -> dict[str, int]:
    return {
        "tasks": db["ralfia_ops_tasks"].count_documents({"task_id": task_id}),
        "events": db["coordination_events"].count_documents({"task_id": task_id}),
        "messages": db["ralfia_agent_messages"].count_documents({"task_id": task_id}),
    }


def active_canary_workers() -> list[str]:
    probe = subprocess.run(
        ["pgrep", "-af", "temporal_worker.*inneros-p0-canary"],
        text=True,
        capture_output=True,
        check=False,
    )
    return [line for line in probe.stdout.splitlines() if "pgrep -af" not in line]


def start_worker(label: str) -> tuple[subprocess.Popen[Any], Any, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"temporal-success-{label}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT / "platform"),
        "TEMPORAL_HOST": "127.0.0.1:7233",
        "TEMPORAL_NAMESPACE": "default",
        "INNEROS_TEMPORAL_ADDRESS": "127.0.0.1:7233",
        "INNEROS_TEMPORAL_NAMESPACE": "default",
        "INNEROS_TEMPORAL_TASK_QUEUE": TASK_QUEUE,
        "MONGODB_URI": MONGO_URI,
        "MONGO_URI": MONGO_URI,
        "INNEROS_MONGO_DB": CANARY_DB,
        "INNEROS_WORKTREE_BASE": str(WORKTREE_BASE),
        "INNEROS_NATS_ENABLED": "false",
        "INNEROS_OTEL_ENABLED": "false",
    })
    process = subprocess.Popen(
        [str(PYTHON), "-m", "inneros_core_runtime.temporal_worker", "--queues", TASK_QUEUE],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_handle.flush()
            raise RuntimeError(f"canary worker exited early: {log_path.read_text(errors='replace')[-2000:]}")
        log_handle.flush()
        if "InnerOS Temporal Workers started" in log_path.read_text(errors="replace"):
            return process, log_handle, log_path
        time.sleep(0.25)
    process.terminate()
    process.wait(timeout=10)
    log_handle.close()
    raise RuntimeError(f"canary worker did not become ready: {log_path}")


def stop_worker(process: subprocess.Popen[Any] | None, log_handle: Any | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log_handle is not None and not log_handle.closed:
        log_handle.close()


async def run() -> dict[str, Any]:
    require(listening(7233), "Temporal port 7233 is not listening")
    require(listening(27017), "MongoDB port 27017 is not listening")
    require(PYTHON.is_file(), f"missing Python runtime: {PYTHON}")
    require(not active_canary_workers(), f"another canary worker is active: {active_canary_workers()}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    task_id = f"p0_success_restart_{timestamp}"
    workflow_id = f"ops_task:{task_id}"
    correlation_id = task_id
    worker_one = worker_two = None
    log_one = log_two = None
    log_path_one = log_path_two = None

    with MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000) as mongo:
        mongo.admin.command("ping")
        before_prod = count_task_records(mongo[PRODUCTION_DB], task_id)
        before_canary = count_task_records(mongo[CANARY_DB], task_id)
    require(before_prod == {"tasks": 0, "events": 0, "messages": 0}, f"production collision: {before_prod}")
    require(before_canary == {"tasks": 0, "events": 0, "messages": 0}, f"canary collision: {before_canary}")

    try:
        worker_one, log_one, log_path_one = start_worker("worker-1")
        temporal = await Client.connect("127.0.0.1:7233", namespace="default")
        envelope = {
            "task_id": task_id,
            "workflow_id": workflow_id,
            "correlation_id": correlation_id,
            "project_id": "p0-coordination-recovery",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "task_class": "coding",
            "execution_lane": "canary",
            "objective": "Create real isolated evidence and complete through the Temporal gate.",
            "title": "P0 successful Temporal restart canary",
            "execution_policy": "local_only",
            "mutation_policy": "canary_only",
            "approval_policy": "auto",
            "preferred_provider": "p0_canary_worker",
            "preferred_model": "none",
            "fallback_policy": "fail_closed",
            "evidence_required": ["temporal_history", "mongo_projection", "artifact"],
            "verification_policy": "automated_gate",
            "idempotency_key": task_id,
            "assignee": "p0_canary_worker",
            "revision": 1,
            "canary_test_type": "successful_diff",
        }
        handle = await temporal.start_workflow(
            OpsTaskWorkflow.run,
            envelope,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
        first_result = await asyncio.wait_for(handle.result(), timeout=120)
        require(first_result.get("status") == "completed", f"workflow did not complete: {first_result}")

        message = create_durable_message(
            task_id=task_id,
            workflow_id=workflow_id,
            run_id=handle.first_execution_run_id,
            correlation_id=correlation_id,
            sender="p0_canary_worker",
            recipient="p0_canary_observer",
            subject="P0 restart durability canary",
            content="This message must remain unread across the canary worker restart.",
            metadata={"canary": True, "restart_test": True},
            idempotency_key=f"{task_id}:restart-message",
            mongo_uri=MONGO_URI,
        )
        require(bool(message.get("message_id")), f"message persistence failed: {message}")
        before_restart = query_durable_messages(
            message_id=message["message_id"], status="unread", mongo_uri=MONGO_URI
        )
        require(len(before_restart) == 1, f"message missing before restart: {before_restart}")

        first_pid = worker_one.pid
        stop_worker(worker_one, log_one)
        worker_one = log_one = None
        require(not active_canary_workers(), f"worker did not stop cleanly: {active_canary_workers()}")

        during_restart = query_durable_messages(
            message_id=message["message_id"], status="unread", mongo_uri=MONGO_URI
        )
        require(len(during_restart) == 1, f"message lost while worker stopped: {during_restart}")

        worker_two, log_two, log_path_two = start_worker("worker-2")
        restarted_handle = temporal.get_workflow_handle(workflow_id)
        replayed_result = await asyncio.wait_for(restarted_handle.result(), timeout=30)
        require(replayed_result == first_result, "Temporal result changed after worker restart")
        after_restart = query_durable_messages(
            message_id=message["message_id"], status="unread", mongo_uri=MONGO_URI
        )
        require(len(after_restart) == 1, f"message lost or auto-acked after restart: {after_restart}")

        acked = ack_durable_message(message["message_id"], actor="p0_canary_observer", mongo_uri=MONGO_URI)
        require(acked.get("status") == "consumed", f"explicit ACK failed: {acked}")

        worktree = WORKTREE_BASE / f"temporal-{task_id}"
        artifact = worktree / "p0-success-evidence.txt"
        require(artifact.is_file(), f"execution artifact missing: {artifact}")

        with MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000) as mongo:
            canary_db = mongo[CANARY_DB]
            task_projection = canary_db["ralfia_ops_tasks"].find_one({"task_id": task_id}, {"_id": 0}) or {}
            canary_counts = count_task_records(canary_db, task_id)
            production_counts = count_task_records(mongo[PRODUCTION_DB], task_id)
            event_types = sorted({
                row.get("event_type", "")
                for row in canary_db["coordination_events"].find({"task_id": task_id}, {"event_type": 1})
                if row.get("event_type")
            })
        require(task_projection.get("status") == "completed", f"task projection not completed: {task_projection}")
        require(production_counts == {"tasks": 0, "events": 0, "messages": 0}, f"production mutated: {production_counts}")

        return {
            "ok": True,
            "mode": "isolated_temporal_success_restart_canary",
            "task_id": task_id,
            "workflow_id": workflow_id,
            "run_id": handle.first_execution_run_id,
            "workflow_status": first_result.get("status"),
            "task_projection_status": task_projection.get("status"),
            "worker_restart": {"first_pid": first_pid, "second_pid": worker_two.pid, "result_replayed": True},
            "durable_message_lifecycle": ["unread_before_restart", "unread_during_restart", "unread_after_restart", "consumed_after_explicit_ack"],
            "artifact": str(artifact),
            "artifact_persisted": True,
            "event_types": event_types,
            "canary_counts": canary_counts,
            "production_counts_for_task": production_counts,
            "production_mutated": False,
            "production_deploy": False,
            "production_restart": False,
            "logs": [str(log_path_one), str(log_path_two)],
        }
    finally:
        stop_worker(worker_two, log_two)
        stop_worker(worker_one, log_one)


def main() -> None:
    print(json.dumps(asyncio.run(run()), indent=2, default=str))


if __name__ == "__main__":
    main()
