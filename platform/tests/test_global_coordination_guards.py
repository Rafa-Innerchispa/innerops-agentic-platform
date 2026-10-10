"""Regressions for repo-less Temporal tasks and strict evidence gates."""
from __future__ import annotations
import asyncio
from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime import temporal_activities as ta

def test_repoless_internal_cannot_claim_executor():
    value = eb.resolve_execution_binding({"assignee":"inneros_orchestrator","execution_lane":"internal","task_class":"coding"})
    assert value["allowed"] is False
    assert value["error"] == "bounded_runner_requires_repo"

def test_internal_with_registered_repo_remains_allowed():
    value = eb.resolve_execution_binding({"assignee":"dev_swarm","execution_lane":"internal","repo":"Rafa-Innerchispa/innerops-agentic-platform"})
    assert value["allowed"] is True

def test_missing_required_evidence_always_blocks():
    envelope = {"task_class":"ops","evidence_required":["real_command_run_id"],"execution_lane":"internal"}
    result = {"ok":True,"test_results":{"ok":True,"exit_code":0},"response":"done"}
    value = asyncio.run(ta.activity_validate_completion_gate(envelope,result))
    assert value["passed"] is False

def test_commit_sha_cannot_bypass_operational_evidence():
    envelope = {"task_class":"coding","evidence_required":["commit_sha","systemd_status"]}
    value = asyncio.run(ta.activity_validate_completion_gate(envelope,{"ok":True,"commit_sha":"abc123","files_count":0,"test_results":{"ok":True,"exit_code":0}}))
    assert value["passed"] is False

def test_readonly_verification_only_commit_sha_can_pass():
    envelope = {"task_class":"verification","evidence_required":["commit_sha"]}
    value = asyncio.run(ta.activity_validate_completion_gate(envelope,{"ok":True,"commit_sha":"abc123"}))
    assert value["passed"] is True
