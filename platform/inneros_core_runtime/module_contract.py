"""Canonical Execution Envelope and Protocol Guards for InnerOS.

Defines the single unified logical execution contract for internal and external workers:
Dev Swarm, External Repair, Codex, Cursor, AntiGravity, and AG-xx agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TaskEnvelopeV1:
    task_id: str
    workflow_id: str = ""
    correlation_id: str = ""
    project_id: str = ""
    repo: str = ""
    base_ref: str = "main"
    expected_base_sha: str = ""
    work_branch: str = ""
    task_class: str = "coding"
    execution_lane: str = "internal"
    objective: str = ""
    title: str = ""
    checklist: List[str] = field(default_factory=list)
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    execution_policy: str = "local_first"
    mutation_policy: str = "allow_worktree_commit"
    approval_policy: str = "auto"
    preferred_provider: str = "local"
    preferred_model: str = "qwen2.5-coder:7b"
    fallback_policy: str = "amd_vllm -> intel_ollama -> fail_closed"
    evidence_required: List[str] = field(default_factory=list)
    verification_policy: str = "automated_gate"
    timeout_policy: Dict[str, Any] = field(default_factory=dict)
    retry_policy: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    assignee: str = ""
    revision: int = 1
    status: str = "pending"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskEnvelopeV1:
        task_id = str(data.get("task_id") or "")
        workflow_id = str(data.get("workflow_id") or (f"ops_task:{task_id}" if task_id else ""))
        return cls(
            task_id=task_id,
            workflow_id=workflow_id,
            correlation_id=str(data.get("correlation_id") or task_id),
            project_id=str(data.get("project_id") or ""),
            repo=str(data.get("repo") or ""),
            base_ref=str(data.get("base_ref") or "main"),
            expected_base_sha=str(data.get("expected_base_sha") or ""),
            work_branch=str(data.get("work_branch") or ""),
            task_class=str(data.get("task_class") or "coding"),
            execution_lane=str(data.get("execution_lane") or "internal"),
            objective=str(data.get("objective") or data.get("title") or ""),
            title=str(data.get("title") or ""),
            checklist=list(data.get("checklist") or []),
            allowed_paths=list(data.get("allowed_paths") or []),
            denied_paths=list(data.get("denied_paths") or []),
            execution_policy=str(data.get("execution_policy") or "local_first"),
            mutation_policy=str(data.get("mutation_policy") or "allow_worktree_commit"),
            approval_policy=str(data.get("approval_policy") or "auto"),
            preferred_provider=str(data.get("preferred_provider") or "local"),
            preferred_model=str(data.get("preferred_model") or "qwen2.5-coder:7b"),
            fallback_policy=str(data.get("fallback_policy") or "amd_vllm -> intel_ollama -> fail_closed"),
            evidence_required=list(data.get("evidence_required") or []),
            verification_policy=str(data.get("verification_policy") or "automated_gate"),
            timeout_policy=dict(data.get("timeout_policy") or {}),
            retry_policy=dict(data.get("retry_policy") or {}),
            idempotency_key=str(data.get("idempotency_key") or f"idem_{task_id}"),
            assignee=str(data.get("assignee") or data.get("preferred_provider") or "local"),
            revision=int(data.get("revision") or 1),
            status=str(data.get("status") or "pending"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "correlation_id": self.correlation_id,
            "project_id": self.project_id,
            "repo": self.repo,
            "base_ref": self.base_ref,
            "expected_base_sha": self.expected_base_sha,
            "work_branch": self.work_branch,
            "task_class": self.task_class,
            "execution_lane": self.execution_lane,
            "objective": self.objective,
            "title": self.title,
            "checklist": self.checklist,
            "allowed_paths": self.allowed_paths,
            "denied_paths": self.denied_paths,
            "execution_policy": self.execution_policy,
            "mutation_policy": self.mutation_policy,
            "approval_policy": self.approval_policy,
            "preferred_provider": self.preferred_provider,
            "preferred_model": self.preferred_model,
            "fallback_policy": self.fallback_policy,
            "evidence_required": self.evidence_required,
            "verification_policy": self.verification_policy,
            "timeout_policy": self.timeout_policy,
            "retry_policy": self.retry_policy,
            "idempotency_key": self.idempotency_key,
            "assignee": self.assignee,
            "revision": self.revision,
            "status": self.status,
        }


class ProtocolMutationGuard:
    TERMINAL_STATES = frozenset({"completed", "cancelled", "superseded", "pending_human_review"})

    @classmethod
    def validate_mutation(
        cls,
        *,
        envelope: TaskEnvelopeV1,
        caller_agent: str,
        acknowledged_revision: int,
        target_action: str = "write",
    ) -> Dict[str, Any]:
        if envelope.status in cls.TERMINAL_STATES:
            return {
                "allowed": False,
                "reason": "TASK_TERMINAL",
                "message": f"Task '{envelope.task_id}' is terminal ({envelope.status}) and immutable.",
            }

        if caller_agent and envelope.assignee and caller_agent.lower() != envelope.assignee.lower():
            return {
                "allowed": False,
                "reason": "TASK_NOT_ASSIGNED",
                "message": f"Task '{envelope.task_id}' is assigned to '{envelope.assignee}', not '{caller_agent}'.",
            }

        if acknowledged_revision < envelope.revision:
            return {
                "allowed": False,
                "reason": "STALE_TASK_REVISION",
                "message": f"Acknowledged revision {acknowledged_revision} is stale (current: {envelope.revision}). Refresh required.",
            }

        return {"allowed": True, "reason": "ALLOWED", "message": "Mutation permitted."}
