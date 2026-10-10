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

def peer_envelope(peer_action="status", **overrides):
    env = {
        "task_id":"ops_peer_test",
        "title":"peer test",
        "objective":"check mcp host status",
        "task_class":"ops",
        "assignee":"inneros_orchestrator",
        "execution_lane":"peer_ops",
        "payload":{
            "task_kind":"peer_ops",
            "requested_agent":"AG-41",
            "owner_approved":True,
            "peer_action":peer_action,
            "service_id":"mcp",
            "node":"amd",
        },
    }
    env.update(overrides)
    return env


def real_status_response():
    return {
        "ok":True, "protocol":"peer_ops.v1", "action":"status",
        "service_id":"mcp", "node":"amd", "read_only":True, "verified":True,
        "peer_status":{
            "ok":True, "healthy":True, "health":"up",
            "system_state":"active", "telemetry":"local_systemd",
        },
    }


def test_owner_authorized_readonly_peer_ops_routes_to_ag41():
    value = eb.resolve_execution_binding(peer_envelope())
    assert value["allowed"] is True
    assert value["runner"] == eb.PEER_OPS_RUNNER
    assert value["target_agent"] == "AG-41"
    assert value["node"] == "amd"
    assert value["peer_action"] == "status"
    assert value["read_only"] is True


def test_peer_ops_without_owner_approval_is_blocked():
    env = peer_envelope()
    env["payload"].pop("owner_approved")
    value = eb.resolve_execution_binding(env)
    assert value["allowed"] is False
    assert value["error"] == "peer_ops_owner_approval_required"


def test_peer_ops_wrong_target_is_blocked():
    env = peer_envelope()
    env["payload"]["requested_agent"] = "AG-40"
    assert eb.resolve_execution_binding(env)["error"] == "peer_ops_target_invalid"


def test_peer_ops_wrong_lane_is_blocked():
    env = peer_envelope(execution_lane="internal")
    assert eb.resolve_execution_binding(env)["error"] == "peer_ops_lane_mismatch"


def test_peer_ops_cannot_mutate_even_with_owner_approved():
    env = peer_envelope(peer_action="restart")
    assert eb.resolve_execution_binding(env)["error"] == "peer_ops_mutation_not_accredited"


def test_peer_ops_missing_action_is_not_a_snapshot_fallback():
    env = peer_envelope(peer_action="")
    assert eb.resolve_execution_binding(env)["allowed"] is False


def test_peer_ops_readonly_skips_worktree():
    value = asyncio.run(ta.activity_hydrate_worktree(peer_envelope()))
    assert value["ok"] is True
    assert value["source"] == "peer_ops_read_only"
    assert value["worktree"] == ""


def test_peer_ops_verified_status_passes_strict_gate(monkeypatch):
    import json
    from inneros_core_runtime import a2a_controller
    called = {}
    def fake_invoke(agent_id, message, timeout_seconds):
        called.update(agent_id=agent_id, request=json.loads(message), timeout=timeout_seconds)
        return real_status_response()
    monkeypatch.setattr(a2a_controller, "_invoke_agent_bounded", fake_invoke)
    env = peer_envelope()
    value = asyncio.run(ta.activity_execute_agent_graph(env, {"worktree":""}))
    gate = asyncio.run(ta.activity_validate_completion_gate(env, value))
    assert value["ok"] is True
    assert called["agent_id"] == "AG-41"
    assert called["request"] == {
        "protocol":"peer_ops.v1", "action":"status",
        "node":"amd", "service_id":"mcp",
    }
    assert value["test_results"]["exit_code"] is None
    assert gate["passed"] is True
    assert gate["mode"] == "peer_ops_verified_readonly_status"


def test_peer_ops_snapshot_cannot_claim_task_completed(monkeypatch):
    from inneros_core_runtime import a2a_controller
    def fake_snapshot(*_args):
        return {"ok":True, "agent_id":"AG-41", "healthy":True, "action":"peer_ops_snapshot"}
    monkeypatch.setattr(a2a_controller, "_invoke_agent_bounded", fake_snapshot)
    env = peer_envelope()
    value = asyncio.run(ta.activity_execute_agent_graph(env, {"worktree":""}))
    gate = asyncio.run(ta.activity_validate_completion_gate(env, value))
    assert value["ok"] is False
    assert gate["passed"] is False


def test_peer_ops_completion_gate_rejects_fabricated_test_success():
    env = peer_envelope()
    fake = {"ok":True, "test_results":{"ok":True, "exit_code":0}}
    gate = asyncio.run(ta.activity_validate_completion_gate(env, fake))
    assert gate["passed"] is False


def test_peer_ops_status_requires_systemd_evidence(monkeypatch):
    from inneros_core_runtime import a2a_controller
    resp = real_status_response()
    resp["peer_status"]["system_state"] = "unknown"
    monkeypatch.setattr(a2a_controller, "_invoke_agent_bounded", lambda *_args: resp)
    env = peer_envelope()
    value = asyncio.run(ta.activity_execute_agent_graph(env, {"worktree":""}))
    gate = asyncio.run(ta.activity_validate_completion_gate(env, value))
    assert value["ok"] is False
    assert gate["passed"] is False


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
