"""Fail-closed: runner failures must not remain in verification."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import ops_lifecycle as ol


def _mock_db(task: dict):
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.side_effect = [dict(task), {**task, "status": "blocked", "revision": 2}]
    col.update_one.return_value = MagicMock(modified_count=1)
    return db, col


def test_submit_completion_blocked_sets_mongo_blocked_not_verification() -> None:
    task = {
        "task_id": "ops_fail0001",
        "status": "in_progress",
        "revision": 1,
        "claim_token": "tok",
        "assignee": "antigravity",
    }
    db, col = _mock_db(task)
    evidence = {
        "notes": "bounded_run_failed",
        "test_results": {"exit_code": -1, "ok": False},
    }
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.ops_lifecycle.emit_chatgpt_completion_handoff", return_value={"ok": True}),
        patch("inneros_core_runtime.ops_lifecycle.emit_owner_terminal_whatsapp", return_value={"ok": True}),
    ):
        out = ol.submit_completion_with_temporal_fallback(
            "ops_fail0001",
            claim_token="tok",
            status="blocked",
            evidence=evidence,
            agent_result={"blocked": True},
            actor="antigravity",
            signal_name="cursor_execution_complete",
        )
    assert out["status"] == "blocked"
    patch_body = col.update_one.call_args.args[1]
    assert patch_body["$set"]["status"] == "blocked"


def test_candidate_evidence_indicates_failure_detects_bad_tests() -> None:
    assert ol._candidate_evidence_indicates_failure(
        {"test_results": {"exit_code": 1, "ok": False}},
        {},
    )


def test_submit_completed_with_failed_tests_coerced_to_blocked() -> None:
    task = {
        "task_id": "ops_fail0002",
        "status": "in_progress",
        "revision": 3,
        "claim_token": "tok2",
    }
    db, col = _mock_db(task)
    evidence = {"test_results": {"exit_code": 2, "ok": False}, "notes": "pytest failed"}
    with (
        patch("raphiia_openai.mongo_store.get_db", return_value=db),
        patch(
            "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
            return_value={"ok": True},
        ),
        patch("inneros_core_runtime.ops_lifecycle.emit_chatgpt_completion_handoff", return_value={"ok": True}),
        patch("inneros_core_runtime.ops_lifecycle.emit_owner_terminal_whatsapp", return_value={"ok": True}),
    ):
        out = ol.submit_completion_with_temporal_fallback(
            "ops_fail0002",
            claim_token="tok2",
            status="completed",
            evidence=evidence,
            agent_result={},
            actor="antigravity",
            signal_name="cursor_execution_complete",
        )
    assert out["status"] == "blocked"
    assert out.get("coerced_from") == "completed"