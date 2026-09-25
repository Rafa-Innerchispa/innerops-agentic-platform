"""Pure Temporal Workflow Definition for InnerOS Tasks.

Deterministic workflow code: coordinates validation, worktree, LangGraph
agent execution, and completion evidence.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from inneros_core_runtime.temporal_activities import (
        activity_validate_envelope,
        activity_hydrate_worktree,
        activity_execute_agent_graph,
        activity_sync_mongo_mirror,
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
        val = await workflow.execute_activity(
            activity_validate_envelope,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 2. Mirror in-progress to Mongo
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "in_progress", {"phase": "hydrating"}],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 3. Hydrate worktree
        self.phase = "worktree_hydration"
        wt = await workflow.execute_activity(
            activity_hydrate_worktree,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=60),
        )

        # 4. Check for cancellation
        if self.cancelled:
            self.status = "cancelled"
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "cancelled", {"reason": self.cancel_reason}],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"status": "cancelled", "reason": self.cancel_reason}

        # 5. Run LangGraph agent execution graph
        self.phase = "agent_execution"
        agent_res = await workflow.execute_activity(
            activity_execute_agent_graph,
            args=[envelope_dict, wt],
            start_to_close_timeout=timedelta(seconds=300),
            heartbeat_timeout=timedelta(seconds=60),
        )

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
