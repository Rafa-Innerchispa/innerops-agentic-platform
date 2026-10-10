"""Regressions for repo-less Temporal tasks and strict evidence gates."""
from __future__ import annotations
import asyncio
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def candidate(name):
    path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / (name + ".py")
    spec = importlib.util.spec_from_file_location("candidate_coord_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

eb = candidate("execution_binding")
ta = candidate("temporal_activities")

def test_repoless_internal_cannot_claim_executor():
    value = eb.resolve_execution_binding({"assignee":"inneros_orchestrator","execution_lane":"internal","task_class":"coding"})
    assert value["allowed"] is False
    assert value["error"] == "bounded_runner_requires_repo"

def test_internal_with_registered_repo_remains_allowed():
    value = eb.resolve_execution_binding({"assignee":"dev_swarm","execution_lane":"internal","repo":"Rafa-Innerchispa/innerops-agentic-platform"})
    assert value["allowed"] is True

def test_owner_authorized_peer_ops_routes_to_ag41():
    value = eb.resolve_execution_binding({
        "assignee":"inneros_orchestrator",
        "execution_lane":"peer_ops",
        "payload":{
            "task_kind":"peer_ops",
            "requested_agent":"AG-41",
            "owner_approved":True,
            "node":"amd",
        },
    })
    assert value["allowed"] is True
    assert value["runner"] == eb.PEER_OPS_RUNNER
    assert value["target_agent"] == "AG-41"
    assert value["node"] == "amd"

def test_peer_ops_without_owner_approval_is_blocked():
    value = eb.resolve_execution_binding({
        "execution_lane":"peer_ops",
        "payload":{"task_kind":"peer_ops","requested_agent":"AG-41"},
    })
    assert value["allowed"] is False
    assert value["error"] == "peer_ops_owner_approval_required"

def test_peer_ops_wrong_target_is_blocked():
    value = eb.resolve_execution_binding({
        "execution_lane":"peer_ops",
        "payload":{"task_kind":"peer_ops","requested_agent":"AG-40","owner_approved":True},
    })
    assert value["allowed"] is False
    assert value["error"] == "peer_ops_target_invalid"

def test_peer_ops_activity_invokes_ag41(monkeypatch):
    from inneros_core_runtime import a2a_controller
    called = {}
    def fake_invoke(agent_id, message, timeout_seconds):
        called.update(agent_id=agent_id, message=message, timeout_seconds=timeout_seconds)
        return {"ok":True, "evidence":{"systemd_status":"active"}, "real_command_run_id":"run-1"}
    monkeypatch.setattr(a2a_controller, "_invoke_agent_bounded", fake_invoke)
    envelope = {
        "task_id":"ops_peer_test",
        "title":"peer test",
        "objective":"check host",
        "task_class":"ops",
        "execution_lane":"peer_ops",
        "payload":{
            "task_kind":"peer_ops",
            "requested_agent":"AG-41",
            "owner_approved":True,
            "node":"amd",
        },
    }
    value = asyncio.run(ta.activity_execute_agent_graph(envelope, {"worktree":""}))
    assert value["ok"] is True
    assert called["agent_id"] == "AG-41"
    assert value["evidence"]["systemd_status"] == "active"
    assert value["evidence"]["real_command_run_id"] == "run-1"

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
