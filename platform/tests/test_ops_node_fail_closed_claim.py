"""Claim routing: explicit AMD/Intel targets must not run on the wrong node."""

from __future__ import annotations

from unittest.mock import patch

from inneros_core_runtime import ops_execution_node_routing as oenr


def _task(**payload) -> dict:
    return {
        "task_id": "ops_abcdef123456",
        "assignee": "antigravity",
        "payload": payload,
    }


def test_amd_target_blocked_on_intel():
    task = _task(
        target_node="amd",
        fail_closed_on_node_mismatch=True,
        required_claim_execution_role="amd",
    )
    with patch("inneros_core_runtime.cursor_headless_lanes.node_role", return_value="intel"):
        allowed, reason, target = oenr.should_claim_on_this_node(task, "antigravity")
    assert not allowed
    assert target == "amd"
    assert "≠" in reason or "target_node" in reason


def test_amd_target_allowed_on_amd():
    task = _task(target_node="amd", fail_closed_on_node_mismatch=True)
    with patch("inneros_core_runtime.cursor_headless_lanes.node_role", return_value="amd"):
        with patch(
            "inneros_core_runtime.interactive_provider_lanes.should_this_node_run_task",
            return_value=(True, "local_ok"),
        ):
            allowed, _reason, target = oenr.should_claim_on_this_node(task, "antigravity")
    assert allowed
    assert target == "amd"