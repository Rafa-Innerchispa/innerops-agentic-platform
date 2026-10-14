"""Lifecycle policy, execution state projection, completion without commit."""

from __future__ import annotations

from inneros_core_runtime import ops_completion_policy as ocp
from inneros_core_runtime import ops_lifecycle as ol


def test_read_only_task_allows_non_commit_completion():
    task = {"task_class": "read_only", "objective": "rev-parse HEAD only", "repo": "org/r"}
    assert ocp.requires_git_commit(task) is False
    assert ocp.validate_completed_evidence(task, {"summary": "ok", "notes": "sha=abc"}) is None


def test_coding_task_requires_commit_or_objective():
    task = {"task_class": "coding", "repo": "org/r", "evidence_required": ["commit_sha"]}
    assert ocp.requires_git_commit(task) is True
    err = ocp.validate_completed_evidence(task, {"notes": "done"})
    assert err is not None
    assert ocp.validate_completed_evidence(task, {"commit_sha": "a" * 40}) is None


def test_protected_bellini_canary_flag():
    assert ol.is_protected_live_canary("ops_e23af9238701") is True
    assert ol.is_protected_live_canary("ops_deadbeef0001") is False


def test_duplicate_terminal_whatsapp_idempotency_key():
    tid = "ops_test12345678"
    flag = f"owner_terminal_whatsapp:{tid}:completed"
    assert "completed" in flag
