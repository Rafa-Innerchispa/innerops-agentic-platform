from __future__ import annotations
class AgentState:
    pass

"""Temporal Activities for InnerOS Task Execution and Completion Gating.

Implements:
- Envelope validation.
- Worktree hydration.
- LangGraph Actor-Critic in Docker sandbox.
- Completion Gating (Exit code 0, non-empty diff, files count, evidence checks).
- NATS JetStream durable event publication.
- MongoDB projection synchronization.
"""

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Dict, Literal, TypedDict

from temporalio import activity
from temporalio.exceptions import ApplicationError

from inneros_core_runtime.module_contract import TaskEnvelopeV1, ProtocolMutationGuard
from inneros_core_runtime import local_model_router
from inneros_core_runtime import durable_coordination_spine

try:
    from inneros_core_runtime.docker_sandbox_executor import DockerSandboxExecutor
    DOCKER_SANDBOX_AVAILABLE = True
except ImportError:
    DOCKER_SANDBOX_AVAILABLE = False

logger = logging.getLogger("temporal_activities")
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
MONGODB_DB = os.environ.get("INNEROS_MONGO_DB", "pcdoctor_swarm")
WORKTREE_BASE = Path(
    os.environ.get(
        "INNEROS_WORKTREE_BASE",
        "/home/rlopez/inneros/inneros_core/worktrees",
    )
)


def _safe_heartbeat(details: str):
    try:
        activity.heartbeat(details)
    except Exception:
        pass


@activity.defn
async def activity_validate_envelope(envelope_dict: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat("validating_envelope")
    envelope = TaskEnvelopeV1.from_dict(envelope_dict)
    guard = ProtocolMutationGuard.validate_mutation(
        envelope=envelope,
        caller_agent=envelope.assignee,
        acknowledged_revision=envelope.revision,
    )
    if not guard["allowed"]:
        raise ApplicationError(guard["message"], type=guard["reason"])
    return {"ok": True, "task_id": envelope.task_id, "revision": envelope.revision}


@activity.defn
async def activity_hydrate_worktree(envelope_dict: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat("hydrating_worktree")
    envelope = TaskEnvelopeV1.from_dict(envelope_dict)
    worktree_path = WORKTREE_BASE / f"temporal-{envelope.task_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "worktree": str(worktree_path)}


@activity.defn
async def activity_publish_nats_event(event_type: str, envelope_dict: Dict[str, Any], status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat(f"publishing_nats_{event_type}")
    try:
        res = durable_coordination_spine.publish_event(
            event_type=event_type,
            actor=envelope_dict.get("assignee") or "temporal_engine",
            task_id=envelope_dict.get("task_id", ""),
            correlation_id=envelope_dict.get("correlation_id", ""),
            repo=envelope_dict.get("repo", ""),
            provider=envelope_dict.get("preferred_provider", ""),
            model=envelope_dict.get("preferred_model", ""),
            status=status,
            payload=payload,
            envelope=envelope_dict,
        )
        if not res.get("ok"):
            raise ApplicationError(
                f"Durable event publication failed: {res.get('reason') or res}",
                type="DURABLE_EVENT_PUBLICATION_FAILED",
                non_retryable=False,
            )
        return {"ok": True, "event_id": res.get("event_id"), "backend": res.get("backend")}
    except Exception as exc:
        if isinstance(exc, ApplicationError):
            raise
        logger.exception("Durable event publication failed")
        raise ApplicationError(
            f"Durable event publication failed: {exc}",
            type="DURABLE_EVENT_PUBLICATION_FAILED",
            non_retryable=False,
        ) from exc


@activity.defn
async def activity_validate_completion_gate(envelope_dict: Dict[str, Any], agent_result: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat("validating_completion_gate")
    task_class = (envelope_dict.get("task_class") or "coding").lower()
    files_count = agent_result.get("files_count", 0)
    code_diff = agent_result.get("code_diff", "")
    test_results = agent_result.get("test_results") or {}
    test_exit_code = test_results.get("exit_code", 0)
    test_ok = test_results.get("ok", True)

    if agent_result.get("candidate_only") and agent_result.get("requires_bounded_executor"):
        return {
            "passed": False,
            "error": (
                "Completion prohibited: Temporal stopped at candidate_only; "
                "bounded executor did not produce test/diff evidence"
            ),
            "agent_flags": {
                "candidate_only": True,
                "requires_bounded_executor": True,
            },
        }

    # 1. Coding Tasks Validation Gate
    if task_class == "coding":
        if test_exit_code is None:
            return {
                "passed": False,
                "error": (
                    "Completion prohibited: Unit tests failed with exit_code=None "
                    "(bounded executor did not run or did not report results)"
                ),
                "test_results": test_results,
            }
        if test_exit_code != 0 or not test_ok:
            return {
                "passed": False,
                "error": f"Completion prohibited: Unit tests failed with exit_code={test_exit_code}",
                "test_results": test_results
            }
        if files_count == 0 and not code_diff:
            return {
                "passed": False,
                "error": "Completion prohibited: Coding task requires non-empty diff and files_count > 0",
                "files_count": files_count
            }

    # 2. Ops / Network / Read-Only Validation Gate
    evidence_req = envelope_dict.get("evidence_required") or []
    if evidence_req:
        evidence = agent_result.get("evidence") or {}
        if not evidence and not agent_result.get("ok"):
            return {
                "passed": False,
                "error": f"Completion prohibited: Required evidence missing for task {envelope_dict.get('task_id')}",
            }

    return {
        "passed": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "task_class": task_class,
        "tests_passed": bool(test_ok and test_exit_code == 0),
        "files_count": files_count,
    }


@activity.defn
async def activity_execute_agent_graph(envelope_dict: Dict[str, Any], worktree_info: Dict[str, Any]) -> Dict[str, Any]:
    envelope = TaskEnvelopeV1.from_dict(envelope_dict)
    worktree = worktree_info.get("worktree", "")
    _safe_heartbeat("running_agent_execution")

    # If mock/canary test execution:
    if envelope_dict.get("canary_test_type") == "failed_test":
        return {
            "ok": False,
            "files_count": 1,
            "code_diff": "+ failed code",
            "test_results": {"exit_code": 1, "ok": False, "stderr": "AssertionError: test failed"},
            "error_count": 1
        }
    if envelope_dict.get("canary_test_type") == "empty_diff":
        return {
            "ok": True,
            "files_count": 0,
            "code_diff": "",
            "test_results": {"exit_code": 0, "ok": True},
            "error_count": 0
        }
    if envelope_dict.get("canary_test_type") == "successful_diff":
        if (
            envelope.execution_lane != "canary"
            or MONGODB_DB != "pcdoctor_swarm_canary"
            or "/.canary/worktrees" not in worktree
        ):
            raise ApplicationError(
                "successful_diff fixture is restricted to the isolated P0 canary",
                type="CANARY_ISOLATION_VIOLATION",
                non_retryable=True,
            )
        artifact = Path(worktree) / "p0-success-evidence.txt"
        artifact.write_text(
            f"task_id={envelope.task_id}\nverified_by=isolated_temporal_canary\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "files_count": 1,
            "code_diff": "+ p0-success-evidence.txt",
            "test_results": {"exit_code": 0, "ok": True},
            "error_count": 0,
            "evidence": {"artifact": str(artifact), "persisted": artifact.is_file()},
        }

    # Local models produce a candidate only; bounded execution supplies evidence.
    res = local_model_router.run_local_model(
        task_type=envelope.task_class or "coding",
        prompt=f"Task {envelope.task_id}: {envelope.objective or envelope.title}",
    )
    candidate = {
        "ok": bool(res.get("ok")),
        "response": res.get("response") or res.get("text") or "",
        "candidate_only": True,
        "requires_bounded_executor": True,
    }
    from inneros_core_runtime import temporal_bounded_executor

    return temporal_bounded_executor.run_bounded_executor(
        envelope_dict,
        worktree,
        candidate,
    )


@activity.defn
async def activity_sync_mongo_mirror(envelope_dict: Dict[str, Any], status: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat("syncing_mongo_mirror")
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2000)
        db = client[MONGODB_DB]
        col = db["ralfia_ops_tasks"]
        task_id = envelope_dict.get("task_id")
        now = datetime.now(timezone.utc).isoformat()
        
        # Mirror projection update
        mirror_fields = {
            "status": status,
            "updated_at": now,
            "evidence": evidence,
            "workflow_id": f"ops_task:{task_id}",
        }
        correlation_id = str(envelope_dict.get("correlation_id") or "").strip()
        if correlation_id:
            mirror_fields["correlation_id"] = correlation_id
        col.update_one(
            {"task_id": task_id},
            {
                "$set": mirror_fields,
                "$inc": {"revision": 1},
            },
            upsert=True,
        )
        return {"ok": True, "mirrored": True}
    except Exception as e:
        logger.exception("Mongo projection update failed")
        raise ApplicationError(
            f"Mongo projection update failed: {e}",
            type="MONGO_PROJECTION_FAILED",
            non_retryable=False,
        ) from e
