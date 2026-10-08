"""Pure Temporal Workflow Definition for InnerOS Tasks.

Deterministic workflow code: coordinates validation, worktree, LangGraph
Actor-Critic agent execution in Docker sandbox, strict gated verification,
and completion evidence or Circuit Breaker transitions to PENDING_HUMAN_REVIEW.
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
        activity_resolve_execution_binding,
        activity_hydrate_worktree,
        activity_execute_agent_graph,
        activity_sync_mongo_mirror,
        activity_publish_nats_event,
        activity_validate_completion_gate,
    )

STANDARD_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=[
        "CIRCUIT_BREAKER_PENDING_HUMAN_REVIEW",
        "TASK_TERMINAL",
        "TASK_NOT_ASSIGNED",
        "STALE_TASK_REVISION",
        "VERIFICATION_FAILED_NO_COMPLETION",
    ],
)


@workflow.defn
class OpsTaskWorkflow:
    def __init__(self) -> None:
        self.status = "queued"
        self.phase = "init"
        self.approved = True
        self.cancelled = False
        self.cancel_reason = ""
        self.evidence: Dict[str, Any] = {}
        self.attempt = 1
        self.last_heartbeat: Dict[str, Any] = {}
        self.worker_id = ""
        self.provider = ""
        self.candidate_result = ""
        self.cursor_handoff: Dict[str, Any] = {}
        self.cursor_completion: Dict[str, Any] = {}

    async def _finalize_agent_result(
        self,
        envelope_dict: Dict[str, Any],
        agent_res: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.phase = "verification"
        self.status = "verification"
        gate_res = await workflow.execute_activity(
            activity_validate_completion_gate,
            args=[envelope_dict, agent_res],
            start_to_close_timeout=timedelta(seconds=45),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        if not gate_res.get("passed"):
            self.status = "failed"
            self.phase = "verification_failed"
            self.evidence = {
                "failed_at": workflow.now().isoformat(),
                "workflow_id": workflow.info().workflow_id,
                "run_id": workflow.info().run_id,
                "verification_error": gate_res.get("error", "Verification criteria not met"),
                "agent_result": agent_res,
            }
            await workflow.execute_activity(
                activity_publish_nats_event,
                args=["task.failed", envelope_dict, "failed", self.evidence],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "failed", self.evidence],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "failed", "evidence": self.evidence}

        self.status = "completed"
        self.phase = "completed"
        self.evidence = {
            "completed_at": workflow.now().isoformat(),
            "workflow_id": workflow.info().workflow_id,
            "run_id": workflow.info().run_id,
            "agent_result": agent_res,
            "gate_verification": gate_res,
        }
        await workflow.execute_activity(
            activity_publish_nats_event,
            args=["task.completed", envelope_dict, "completed", self.evidence],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=STANDARD_RETRY_POLICY,
        )
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "completed", self.evidence],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )
        return {"status": "completed", "evidence": self.evidence}

    async def _run_cursor_interactive_path(
        self,
        envelope_dict: Dict[str, Any],
        binding_res: Dict[str, Any],
        val_res: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.phase = "awaiting_cursor_handoff"
        self.status = str(binding_res.get("status") or "awaiting_cursor_claim")
        self.evidence = {"execution_binding": binding_res, "validated": val_res}
        await workflow.wait_condition(
            lambda: bool(self.cursor_handoff.get("claim_token")),
            timeout=timedelta(days=7),
        )
        if not self.cursor_handoff.get("claim_token"):
            self.status = "failed"
            self.phase = "cursor_handoff_timeout"
            timeout_evidence = {**self.evidence, "error": "cursor_handoff_timeout"}
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "failed", timeout_evidence],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "failed", "error": "cursor_handoff_timeout", "evidence": timeout_evidence}

        envelope_dict = {**envelope_dict, **self.cursor_handoff}
        self.status = "claimed"
        self.phase = "cursor_interactive"
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "claimed", {"cursor_handoff": self.cursor_handoff}],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        await workflow.wait_condition(
            lambda: bool(self.cursor_completion.get("submitted")),
            timeout=timedelta(days=7),
        )
        if not self.cursor_completion.get("submitted"):
            self.status = "failed"
            self.phase = "cursor_completion_timeout"
            timeout_evidence = {**self.evidence, "error": "cursor_completion_timeout"}
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "failed", timeout_evidence],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "failed", "error": "cursor_completion_timeout", "evidence": timeout_evidence}

        agent_res = dict(self.cursor_completion.get("agent_result") or {})
        if self.cursor_completion.get("status") in {"failed", "blocked"}:
            agent_res.setdefault("blocked", True)
        return await self._finalize_agent_result(envelope_dict, agent_res)

    @workflow.run
    async def run(self, envelope_dict: Dict[str, Any]) -> Dict[str, Any]:
        self.phase = "validation"
        self.status = "dispatched"
        self.attempt = 1

        # 1. Validate envelope and protocol
        val_res = await workflow.execute_activity(
            activity_validate_envelope,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        binding_res = await workflow.execute_activity(
            activity_resolve_execution_binding,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )
        if not binding_res.get("allowed"):
            blocked_status = str(binding_res.get("status") or "waiting_for_binding")
            self.status = blocked_status
            self.phase = "execution_binding_blocked"
            self.evidence = {"execution_binding": binding_res, "validated": val_res}
            await workflow.execute_activity(
                activity_publish_nats_event,
                args=["task.blocked", envelope_dict, blocked_status, self.evidence],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, blocked_status, self.evidence],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            handoff_errors = {
                "cursor_claim_required",
                "codex_claim_required",
                "interactive_handoff_pending",
            }
            handoff_errors |= {f"{p}_claim_required" for p in ("antigravity", "gemini", "chatgpt")}
            handoff_statuses = {
                "awaiting_cursor_claim",
                "awaiting_codex_claim",
                "awaiting_antigravity_claim",
                "awaiting_gemini_claim",
                "awaiting_chatgpt_claim",
                "awaiting_ide_claim",
                "waiting_for_binding",
            }
            if blocked_status in handoff_statuses or binding_res.get("error") in handoff_errors:
                return await self._run_cursor_interactive_path(envelope_dict, binding_res, val_res)
            return {"status": blocked_status, "execution_binding": binding_res, "validated": val_res}

        # 2. Publish dispatched event & mirror to Mongo
        await workflow.execute_activity(
            activity_publish_nats_event,
            args=["task.dispatched", envelope_dict, "dispatched", {"attempt": self.attempt}],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=STANDARD_RETRY_POLICY,
        )
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "dispatched", {"phase": "dispatched", "attempt": self.attempt}],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        # 3. Transition to running state with real parameters
        self.status = "running"
        self.phase = "worktree_hydration"
        self.worker_id = envelope_dict.get("preferred_provider") or envelope_dict.get("assignee") or "dev_swarm_worker"
        self.provider = envelope_dict.get("preferred_provider") or "local"

        await workflow.execute_activity(
            activity_publish_nats_event,
            args=["task.running", envelope_dict, "running", {
                "worker_id": self.worker_id,
                "provider": self.provider,
                "workflow_id": workflow.info().workflow_id,
                "run_id": workflow.info().run_id,
                "attempt": self.attempt,
            }],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=STANDARD_RETRY_POLICY,
        )
        await workflow.execute_activity(
            activity_sync_mongo_mirror,
            args=[envelope_dict, "running", {
                "phase": "hydrating",
                "worker_id": self.worker_id,
                "provider": self.provider,
                "workflow_id": workflow.info().workflow_id,
                "run_id": workflow.info().run_id,
                "attempt": self.attempt,
            }],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        # 4. Hydrate worktree
        wt = await workflow.execute_activity(
            activity_hydrate_worktree,
            envelope_dict,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=STANDARD_RETRY_POLICY,
        )

        # 5. Check for cancellation
        if self.cancelled:
            self.status = "cancelled"
            await workflow.execute_activity(
                activity_publish_nats_event,
                args=["task.cancelled", envelope_dict, "cancelled", {"reason": self.cancel_reason}],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "cancelled", {"reason": self.cancel_reason}],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "cancelled", "reason": self.cancel_reason}

        # 6. Run LangGraph / Agent Execution
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
                activity_publish_nats_event,
                args=["circuit_breaker.triggered", envelope_dict, "pending_human_review", self.evidence],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            await workflow.execute_activity(
                activity_sync_mongo_mirror,
                args=[envelope_dict, "pending_human_review", self.evidence],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=STANDARD_RETRY_POLICY,
            )
            return {"status": "pending_human_review", "evidence": self.evidence}

        return await self._finalize_agent_result(envelope_dict, agent_res)

    @workflow.signal
    def cursor_claim_handoff(self, payload: Dict[str, Any]) -> None:
        self.cursor_handoff = dict(payload or {})

    @workflow.signal
    def cursor_execution_complete(self, payload: Dict[str, Any]) -> None:
        self.cursor_completion = dict(payload or {})
        self.cursor_completion["submitted"] = True

    @workflow.signal
    def heartbeat(self, hb_dict: Dict[str, Any]) -> None:
        self.last_heartbeat = hb_dict

    @workflow.signal
    def record_candidate_result(self, res_dict: Dict[str, Any]) -> None:
        self.candidate_result = res_dict.get("result", "")
        if res_dict.get("evidence"):
            self.evidence.update(res_dict.get("evidence"))

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
            "attempt": self.attempt,
            "worker_id": self.worker_id,
            "provider": self.provider,
            "candidate_result": self.candidate_result,
            "last_heartbeat": self.last_heartbeat,
            "approved": self.approved,
            "cancelled": self.cancelled,
            "evidence": self.evidence,
        }
