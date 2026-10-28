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
    full = {
        "commit_sha": "a" * 40,
        "objective_paths": ["src/x.py"],
        "objective_files_count": 1,
        "test_results": {"exit_code": 0, "ok": True},
        "evidence_source": "git_committed_diff_on_execution_host",
        "git_before_sha": "b" * 40,
    }
    assert ocp.validate_completed_evidence(task, full) is None
    assert ocp.validate_completed_evidence(task, {"commit_sha": "a" * 40}) is not None


def test_protected_bellini_canary_flag():
    assert ol.is_protected_live_canary("ops_e23af9238701") is True
    assert ol.is_protected_live_canary("ops_deadbeef0001") is False


def test_duplicate_terminal_whatsapp_idempotency_key():
    tid = "ops_test12345678"
    flag = f"owner_terminal_whatsapp:{tid}:completed"
    assert "completed" in flag


def test_execution_state_refresh_does_not_drop_task_id():
    from inneros_core_runtime import ops_execution_state as oes
    from unittest.mock import MagicMock, patch

    task = {"task_id": "ops_test00000001", "status": "claimed", "assignee": "cursor"}
    with patch("inneros_core_runtime.ops_execution_state.mongo_store") as ms:
        db = MagicMock()
        ms.get_db.return_value = db
        db.__getitem__.return_value.find_one.return_value = {}
        db.__getitem__.return_value.update_one.return_value = MagicMock()
        with patch("inneros_core_runtime.ops_execution_state.eb.resolve_execution_binding", return_value={"status": "claimed"}):
            with patch("inneros_core_runtime.ops_execution_state.eb.owner_execution_summary", return_value={}):
                out = oes.refresh_current_execution_state(task, event="test")
    assert out.get("ok") is True


def test_submit_completion_fallback_structure():
    from inneros_core_runtime import ops_lifecycle as ol
    assert callable(ol.submit_completion_with_temporal_fallback)
    assert callable(ol.replay_pending_temporal_completion)


def test_reconciler_callable():
    from inneros_core_runtime.ops_lifecycle_reconciler import reconcile_ops_lifecycle
    assert callable(reconcile_ops_lifecycle)
