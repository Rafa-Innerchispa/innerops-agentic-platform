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
    dispatch_mode: str = ""
    do_not_auto_dispatch: bool = False
    model_preflight_required: bool = False
    provider_transport: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskEnvelopeV1:
        from inneros_core_runtime.execution_binding import merge_task_dispatch_fields

        data = merge_task_dispatch_fields(dict(data or {}))
        task_id = str(data.get("task_id") or "")
        workflow_id = str(data.get("workflow_id") or (f"ops_task:{task_id}" if task_id else ""))
        if "preferred_model" in data:
            preferred_model = "" if data.get("preferred_model") is None else str(data.get("preferred_model") or "")
        else:
            preferred_model = "qwen2.5-coder:7b"
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
            preferred_provider=str(data.get("preferred_provider") or data.get("assignee") or "local"),
            preferred_model=preferred_model,
            fallback_policy=str(data.get("fallback_policy") or "amd_vllm -> intel_ollama -> fail_closed"),
            evidence_required=list(data.get("evidence_required") or []),
            verification_policy=str(data.get("verification_policy") or "automated_gate"),
            timeout_policy=dict(data.get("timeout_policy") or {}),
            retry_policy=dict(data.get("retry_policy") or {}),
            idempotency_key=str(data.get("idempotency_key") or f"idem_{task_id}"),
            assignee=str(data.get("assignee") or data.get("preferred_provider") or "local"),
            revision=int(data.get("revision") or 1),
            dispatch_mode=str(data.get("dispatch_mode") or ""),
            do_not_auto_dispatch=bool(data.get("do_not_auto_dispatch")),
            model_preflight_required=bool(data.get("model_preflight_required")),
            provider_transport=str(data.get("provider_transport") or ""),
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
            "dispatch_mode": self.dispatch_mode,
            "do_not_auto_dispatch": self.do_not_auto_dispatch,
            "model_preflight_required": self.model_preflight_required,
            "provider_transport": self.provider_transport,
        }


class ProtocolMutationGuard:
    @staticmethod
    def validate_mutation(
        envelope: TaskEnvelopeV1,
        caller_agent: str,
        acknowledged_revision: int,
    ) -> Dict[str, Any]:
        if not envelope.task_id:
            return {"allowed": False, "reason": "TASK_NOT_ASSIGNED", "message": "Missing task_id in envelope"}
        if acknowledged_revision < 0:
            return {"allowed": False, "reason": "STALE_TASK_REVISION", "message": "Invalid negative revision"}
        return {"allowed": True, "reason": "AUTHORIZED", "message": "Mutation permitted"}
