"""Temporal Activities for InnerOS Task Execution and Completion Gating.

Implements:
- Envelope validation.
- Worktree hydration.
- LangGraph Actor-Critic in Docker sandbox.
- Completion Gating (Exit code 0, non-empty diff, files count, evidence checks).
- NATS JetStream durable event publication.
- MongoDB projection synchronization.
"""
from __future__ import annotations

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
async def activity_resolve_execution_binding(envelope_dict: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat("resolving_execution_binding")
    from inneros_core_runtime import execution_binding

    binding = execution_binding.resolve_execution_binding(envelope_dict)
    return binding


@activity.defn
async def activity_hydrate_worktree(envelope_dict: Dict[str, Any]) -> Dict[str, Any]:
    _safe_heartbeat("hydrating_worktree")
    envelope = TaskEnvelopeV1.from_dict(envelope_dict)
    repo = str(envelope_dict.get("repo") or envelope_dict.get("related_project") or "").strip()
    if repo:
        from inneros_core_runtime import local_execution_plane as lep

        wt = lep.create_worktree(
            repo=repo,
            base_branch=str(envelope_dict.get("base_ref") or "main"),
            work_branch=str(envelope_dict.get("work_branch") or f"dev-swarm/{envelope.task_id.replace('ops_', '')}"),
            actor=str(envelope_dict.get("assignee") or "dev_swarm"),
            task_id=envelope.task_id,
            correlation_id=str(envelope_dict.get("correlation_id") or envelope.task_id),
            idempotency_key=f"temporal-hydrate-{envelope.task_id}",
        )
        if wt.get("ok") and wt.get("worktree"):
            return {"ok": True, "worktree": str(wt.get("worktree")), "source": "local_execution_plane"}
    worktree_path = WORKTREE_BASE / f"temporal-{envelope.task_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "worktree": str(worktree_path), "source": "temporal_stub"}


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

    if agent_result.get("blocked"):
        binding = agent_result.get("execution_binding") or {}
        return {
            "passed": False,
            "error": binding.get("message") or agent_result.get("response") or "execution_binding_blocked",
            "execution_binding": binding,
        }

    # Fail closed on execution failures before evaluating any positive gate.
    # A task must never become completed when the executor itself reports failure,
    # policy denial, allowlist rejection, or a failed bounded command.
    if agent_result.get("ok") is False:
        bounded = agent_result.get("bounded_executor") or {}
        command_audit = bounded.get("command_audit") or {}
        tests = agent_result.get("test_results") or {}
        reason = (
            command_audit.get("error")
            or tests.get("reason")
            or agent_result.get("error")
            or agent_result.get("response")
            or "agent_execution_failed"
        )
        return {
            "passed": False,
            "error": f"Completion prohibited: executor reported failure ({reason})",
            "agent_ok": False,
            "command_audit": command_audit,
            "test_results": tests,
        }

    lane = str(envelope_dict.get("execution_lane") or "").lower()
    if lane in {"local_dev_swarm", "dev_swarm", "internal"}:
        tests = agent_result.get("test_results") or {}
        exit_code = tests.get("exit_code")
        objective_files = int(agent_result.get("objective_files_count") or 0)
        objective_paths = list(agent_result.get("objective_paths") or [])
        mutating_class = task_class in {"coding", "platform"}
        if (
            exit_code is not None
            and int(exit_code) == 0
            and tests.get("ok", True)
            and (not mutating_class or (objective_files > 0 and objective_paths))
        ):
            return {
                "passed": True,
                "mode": "dev_swarm_pytest_pass",
                "test_results": tests,
                "objective_files_count": objective_files,
            }

    if agent_result.get("completion_channel") in {"cursor_interactive", "codex_interactive"}:
        sha = str(agent_result.get("commit_sha") or "").strip()
        objective_files = int(agent_result.get("objective_files_count") or 0)
        objective_paths = list(agent_result.get("objective_paths") or [])
        tests = agent_result.get("test_results") or {}
        exit_code = tests.get("exit_code")
        if sha and objective_files > 0 and objective_paths:
            return {"passed": True, "mode": "cursor_interactive_sha_and_paths", "commit_sha": sha}
        if exit_code is not None and int(exit_code) == 0 and tests.get("ok", True):
            return {"passed": True, "mode": "cursor_interactive_tests", "test_results": tests}
        return {
            "passed": False,
            "error": (
                "Cursor completion prohibited: require commit_sha + objective_paths "
                "or test_results.exit_code=0"
            ),
            "commit_sha": sha,
            "objective_files_count": objective_files,
        }

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
        objective_files = int(agent_result.get("objective_files_count") or 0)
        objective_paths = list(agent_result.get("objective_paths") or [])
        if any(str(path).endswith("/") for path in objective_paths):
            return {
                "passed": False,
                "error": "Completion prohibited: objective_paths must list concrete files, not directories",
                "objective_paths": objective_paths,
            }
        if any("__pycache__" in str(path) for path in objective_paths):
            return {
                "passed": False,
                "error": "Completion prohibited: generated cache paths cannot count as objective fulfillment",
                "objective_paths": objective_paths,
            }
        missing_required = list(agent_result.get("missing_required_objective_paths") or [])
        if missing_required:
            return {
                "passed": False,
                "error": "Completion prohibited: required objective paths missing on disk",
                "missing_required_objective_paths": missing_required,
            }
        if objective_files == 0:
            bridge_paths = agent_result.get("bridge_artifact_paths") or []
            return {
                "passed": False,
                "error": (
                    "Completion prohibited: diff is empty or only Temporal bridge artifacts "
                    "(sync_bridge_artifacts is not task objective fulfillment)"
                ),
                "files_count": files_count,
                "objective_files_count": objective_files,
                "bridge_artifact_paths": bridge_paths,
            }
        if files_count == 0 and not code_diff and objective_files == 0:
            return {
                "passed": False,
                "error": "Completion prohibited: Coding task requires non-empty diff and files_count > 0",
                "files_count": files_count,
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

    if task_class == "platform":
        objective_files = int(agent_result.get("objective_files_count") or 0)
        objective_paths = list(agent_result.get("objective_paths") or [])
        if objective_files <= 0 or not objective_paths:
            return {
                "passed": False,
                "error": "Completion prohibited: platform mutation requires objective file evidence",
                "objective_files_count": objective_files,
                "objective_paths": objective_paths,
                "test_results": test_results,
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

    from inneros_core_runtime import execution_binding

    binding = execution_binding.resolve_execution_binding(envelope_dict)
    if not binding.get("allowed"):
        return {
            "ok": False,
            "blocked": True,
            "execution_binding": binding,
            "files_count": 0,
            "objective_files_count": 0,
            "objective_paths": [],
            "code_diff": "",
            "response": binding.get("message") or binding.get("error") or "execution_binding_blocked",
            "test_results": {
                "exit_code": None,
                "ok": False,
                "reason": binding.get("error") or "execution_binding_blocked",
            },
            "candidate_only": False,
            "requires_bounded_executor": False,
        }

    # If mock/canary test execution:
    if envelope_dict.get("canary_test_type") == "failed_test":
        return {
            "ok": False,
            "files_count": 1,
            "code_diff": "+ failed code",
            "test_results": {"exit_code": 1, "ok": False, "stderr": "AssertionError: test failed"},
            "error_count": 1
        }
    if envelope_dict.get("canary_test_type") == "git_head_only" or (
        isinstance(envelope_dict.get("payload"), dict)
        and envelope_dict["payload"].get("canary_test_type") == "git_head_only"
    ):
        import subprocess

        wt = worktree or worktree_info.get("worktree") or ""
        if not wt:
            return {"ok": False, "test_results": {"exit_code": 1, "ok": False}, "files_count": 0}
        proc = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        sha = proc.stdout.strip() if proc.returncode == 0 else ""
        ok = bool(sha)
        return {
            "ok": ok,
            "files_count": 0,
            "objective_files_count": 0,
            "objective_paths": [],
            "code_diff": "",
            "response": "git_head_only canary",
            "test_results": {"exit_code": 0 if ok else 1, "ok": ok},
            "commit_sha": sha,
            "evidence": {"commit_sha": sha},
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