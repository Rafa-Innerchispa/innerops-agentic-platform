"""Pure Temporal Workflow Definition for InnerOS Tasks.

Deterministic workflow code: coordinates validation, worktree, LangGraph
Actor-Critic agent execution in Docker sandbox, and completion evidence or
Circuit Breaker transitions to PENDING_HUMAN_REVIEW.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from inneros_core_runtime.temporal_activities import (
        activity_validate_envelope,
        activity_hydrate_worktree,
        activity_execute_agent_graph,
        activity_sync_mongo_mirror,
    )

STANDARD_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["CIRCUIT_BREAKER_PENDING_HUMAN_REVIEW", "TASK_TERMINAL", "TASK_NOT_ASSIGNED", "STALE_TASK_REVISION"],
)


@workflow.defn
class OpsTaskWorkflow:
    def __init__(self) -> None:
        self.status = "running"
        self.phase = "init"
        self.approved = True
        self.cancelled = False
        self.cancel_reason = ""
        self.evidence: Dict[str, Any] = {}

    @workflow.run
    async def run(self, envelope_dict: Dict[str, Any]) -> Dict[str, Any]:
        self.phase = "validation"

        # 1. Validate envelope and protocol
        await workflow.execute_activity(
            activity_validate_envelope,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        # 2. Mirror in-progress to Mongo
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "in_progress", {"phase": "hydrating"}],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        # 3. Hydrate worktree
        self.phase = "worktree_hydration"
        wt = await workflow.execute_activity(
            activity_hydrate_worktree,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        # 4. Check for cancellation
        if self.cancelled:
            self.status = "cancelled"
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "cancelled", {"reason": self.cancel_reason}],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "cancelled", "reason": self.cancel_reason}

        # 5. Run LangGraph agent execution graph in Docker sandbox
        self.phase = "agent_execution"
        try:
            agent_res = await workflow.execute_activity(
                activity_execute_agent_graph,
                args=[envelope_dict, wt],
                start_to_close_timeout=timedelta(seconds=300),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=STANDARD_RETRY_POLICY,
            )
        except ActivityError as ae:
            # Circuit breaker: 3 activity failures or explicit human intervention request
            self.status = "pending_human_review"
            self.phase = "circuit_breaker"
            self.evidence = {
                "failed_at": workflow.now().isoformat(),
                "workflow_id": workflow.info().workflow_id,
                "run_id": workflow.info().run_id,
                "circuit_breaker_reason": str(ae),
                "review_required": True,
            }
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "pending_human_review", self.evidence],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "pending_human_review", "evidence": self.evidence}

        # 6. Complete and mirror terminal state
        self.status = "completed"
        self.phase = "completed"
        self.evidence = {
            "completed_at": workflow.now().isoformat(),
            "workflow_id": workflow.info().workflow_id,
            "run_id": workflow.info().run_id,
            "agent_result": agent_res,
        }
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "completed", self.evidence],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        return {"status": "completed", "evidence": self.evidence}

    @workflow.signal
    def approve(self, approval_payload: Dict[str, Any]) -> None:
        self.approved = True

    @workflow.signal
    def cancel(self, reason: str) -> None:
        self.cancelled = True
        self.cancel_reason = reason

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "phase": self.phase,
            "approved": self.approved,
            "cancelled": self.cancelled,
            "evidence": self.evidence,
        }
