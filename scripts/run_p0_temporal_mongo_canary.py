#!/usr/bin/env python3
"""Run one isolated fail-closed Temporal workflow and durable-message canary."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
from typing import Any

# Fail closed before importing modules that read configuration at import time.
EXPECTED_ACK = "I_UNDERSTAND_ISOLATED_TEMPORAL_CANARY"
if os.environ.get("INNEROS_P0_TEMPORAL_CANARY_ACK") != EXPECTED_ACK:
    raise SystemExit(f"REFUSED: set INNEROS_P0_TEMPORAL_CANARY_ACK={EXPECTED_ACK}")

EXPECTED_DB = "pcdoctor_swarm_canary"
EXPECTED_QUEUE = "inneros-p0-canary"
EXPECTED_WORKTREE_FRAGMENT = "/.canary/worktrees"

if os.environ.get("INNEROS_MONGO_DB") != EXPECTED_DB:
    raise SystemExit(f"REFUSED: INNEROS_MONGO_DB must equal {EXPECTED_DB}")
if os.environ.get("INNEROS_TEMPORAL_TASK_QUEUE") != EXPECTED_QUEUE:
    raise SystemExit(f"REFUSED: INNEROS_TEMPORAL_TASK_QUEUE must equal {EXPECTED_QUEUE}")
if EXPECTED_WORKTREE_FRAGMENT not in os.environ.get("INNEROS_WORKTREE_BASE", ""):
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

MONGO_URI = "mongodb://127.0.0.1:27017"
TEMPORAL_ADDRESS = "127.0.0.1:7233"
CANARY_DB = "pcdoctor_swarm_canary"
PRODUCTION_DB = "pcdoctor_swarm"
TASK_QUEUE = "inneros-p0-canary"


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def count_task_records(db: Any, task_id: str) -> dict[str, int]:
    return {
        "tasks": db["ralfia_ops_tasks"].count_documents({"task_id": task_id}),
        "events": db["coordination_events"].count_documents({"task_id": task_id}),
        "messages": db["ralfia_agent_messages"].count_documents({"task_id": task_id}),
    }


async def run() -> dict[str, Any]:
    require(listening(7233), "Temporal port 7233 is not listening")
    require(listening(27017), "MongoDB port 27017 is not listening")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    task_id = f"p0_canary_{timestamp}"
    workflow_id = f"ops_task:{task_id}"
    correlation_id = task_id

    with MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000) as mongo:
        mongo.admin.command("ping")
        before_prod = count_task_records(mongo[PRODUCTION_DB], task_id)
        before_canary = count_task_records(mongo[CANARY_DB], task_id)

    require(before_prod == {"tasks": 0, "events": 0, "messages": 0}, f"production collision before start: {before_prod}")
    require(before_canary == {"tasks": 0, "events": 0, "messages": 0}, f"canary collision before start: {before_canary}")

    envelope = {
        "task_id": task_id,
        "workflow_id": workflow_id,
        "correlation_id": correlation_id,
        "project_id": "p0-coordination-recovery",
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "task_class": "coding",
        "execution_lane": "canary",
        "objective": "Prove fail-closed completion when execution evidence is empty.",
        "title": "P0 isolated Temporal empty-diff canary",
        "execution_policy": "local_only",
        "mutation_policy": "canary_only",
        "approval_policy": "auto",
        "preferred_provider": "p0_canary_worker",
        "preferred_model": "none",
        "fallback_policy": "fail_closed",
        "evidence_required": ["temporal_history", "mongo_projection"],
        "verification_policy": "automated_gate",
        "idempotency_key": task_id,
        "assignee": "p0_canary_worker",
        "revision": 1,
        "canary_test_type": "empty_diff",
    }

    temporal = await Client.connect(TEMPORAL_ADDRESS, namespace="default")
    handle = await temporal.start_workflow(
        OpsTaskWorkflow.run,
        envelope,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    result = await asyncio.wait_for(handle.result(), timeout=120)

    require(result.get("status") == "failed", f"workflow did not fail closed: {result}")
    require(result.get("status") != "completed", "workflow incorrectly reported completed")
    verification_error = result.get("evidence", {}).get("verification_error", "")
    require("non-empty diff" in verification_error, f"unexpected completion gate evidence: {verification_error}")

    message = create_durable_message(
        task_id=task_id,
        workflow_id=workflow_id,
        run_id=handle.first_execution_run_id,
        correlation_id=correlation_id,
        sender="p0_canary_worker",
        recipient="p0_canary_observer",
        subject="P0 durable message canary",
        content="This message must remain unread until explicitly acknowledged.",
        metadata={"canary": True},
        idempotency_key=f"{task_id}:message",
        mongo_uri=MONGO_URI,
    )
    require(message.get("ok") and message.get("persisted"), f"message persistence failed: {message}")

    unread = query_durable_messages(
        task_id=task_id,
        recipient="p0_canary_observer",
        status="unread",
        mongo_uri=MONGO_URI,
    )
    require(len(unread) == 1, f"message was lost or auto-acknowledged: {unread}")

    acked = ack_durable_message(
        message["message_id"],
        actor="p0_canary_observer",
        mongo_uri=MONGO_URI,
    )
    require(acked.get("ok") and acked.get("status") == "consumed", f"explicit ACK failed: {acked}")

    consumed = query_durable_messages(
        message_id=message["message_id"],
        status="consumed",
        mongo_uri=MONGO_URI,
    )
    require(len(consumed) == 1, f"consumed message projection missing: {consumed}")

    with MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000) as mongo:
        canary_db = mongo[CANARY_DB]
        production_db = mongo[PRODUCTION_DB]
        canary_counts = count_task_records(canary_db, task_id)
        production_counts = count_task_records(production_db, task_id)
        task_projection = canary_db["ralfia_ops_tasks"].find_one({"task_id": task_id}, {"_id": 0}) or {}
        event_types = sorted({
            row.get("event_type", "")
            for row in canary_db["coordination_events"].find({"task_id": task_id}, {"event_type": 1})
            if row.get("event_type")
        })

    require(task_projection.get("status") == "failed", f"Mongo task projection not failed: {task_projection}")
    require(canary_counts["tasks"] == 1, f"unexpected canary task count: {canary_counts}")
    require(canary_counts["events"] >= 5, f"insufficient durable events: {canary_counts}")
    require(canary_counts["messages"] == 1, f"unexpected durable message count: {canary_counts}")
    require(production_counts == {"tasks": 0, "events": 0, "messages": 0}, f"production database was mutated: {production_counts}")

    worktree = Path(os.environ["INNEROS_WORKTREE_BASE"]) / f"temporal-{task_id}"
    require(worktree.is_dir(), f"isolated worktree was not created: {worktree}")

    return {
        "ok": True,
        "mode": "isolated_temporal_mongo_fail_closed_canary",
        "task_id": task_id,
        "workflow_id": workflow_id,
        "run_id": handle.first_execution_run_id,
        "task_queue": TASK_QUEUE,
        "mongo_db": CANARY_DB,
        "worktree": str(worktree),
        "workflow_result": result,
        "task_projection_status": task_projection.get("status"),
        "durable_event_types": event_types,
        "durable_message_lifecycle": ["unread", "consumed_after_explicit_ack"],
        "canary_counts": canary_counts,
        "production_counts_for_task": production_counts,
        "nats_enabled": False,
        "production_mutated": False,
        "production_deploy": False,
        "production_restart": False,
    }


def main() -> None:
    print(json.dumps(asyncio.run(run()), indent=2, default=str))


if __name__ == "__main__":
    main()
