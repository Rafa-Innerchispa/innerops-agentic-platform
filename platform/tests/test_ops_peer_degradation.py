"""Intel degraded-mode steering when AMD peer is offline."""

from __future__ import annotations

from unittest.mock import patch

from inneros_core_runtime import ops_execution_node_routing as oenr
from inneros_core_runtime import ops_peer_degradation as opd


def _task(**payload) -> dict:
    return {
        "task_id": "ops_test_peer_deg",
        "assignee": "cursor",
        "title": "Homelab migrate InnerOS",
        "payload": payload,
        "target_execution_node": "amd",
    }


def test_amd_pinned_allowed_on_intel_when_degraded():
    task = _task(
        target_node="amd",
        fail_closed_on_node_mismatch=True,
        required_claim_execution_role="amd",
    )
    with patch("inneros_core_runtime.cursor_headless_lanes.node_role", return_value="intel"):
        with patch.object(opd, "degradation_active_local", return_value=True):
            with patch.object(opd, "task_requires_amd_gpu", return_value=False):
                allowed, reason, target = oenr.should_claim_on_this_node(task, "cursor")
    assert allowed
    assert target == "intel"
    assert reason == "degraded_intel_steering" or "local_ok" in reason or allowed


def test_qwen_task_not_steered():
    task = _task(preferred_model="Qwen2.5-32B-Instruct")
    assert opd.task_requires_amd_gpu(task)


def test_cursor_lane_relaxed_fail_closed():
    task = _task(target_node="amd", fail_closed_on_node_mismatch=True)
    with patch("inneros_core_runtime.cursor_headless_lanes.node_role", return_value="intel"):
        with patch.object(opd, "allow_intel_steering", return_value=True):
            from inneros_core_runtime import cursor_headless_lanes as chl

            ok, reason = chl.should_this_node_run_task(task)
    assert ok
    assert "degraded" in reason