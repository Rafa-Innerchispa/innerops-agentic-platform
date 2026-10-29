"""Deploy/host gate must not re-spawn Cursor or requeue DevSwarm (offline regression)."""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

from inneros_core_runtime import ops_deploy_execution_pause as odep
from inneros_core_runtime import ops_auto_claim_admission as oaca
from inneros_core_runtime import ops_temporal_recovery as otr
from inneros_core_runtime import cursor_ops_runner as cor
from scripts import cursor_ops_headless_autopilot as autopilot


HOST_GATE = (
    "Completion prohibited: host/deployment task requires observed host mutation "
    "and verified postconditions"
)


def _deploy_task(**extra):
    base = {
        "task_id": "ops_loop",
        "task_class": "deployment",
        "assignee": "cursor",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
        "status": "in_progress",
        "claim_token": "abc",
        "payload": {"requires_deploy_approval": True},
    }
    base.update(extra)
    return base


def test_blocked_complete_does_not_advance_to_verification():
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    task = {
        "task_id": "ops_pause",
        "claim_token": "tok",
        "lease_until": "2099-01-01T00:00:00+00:00",
        "status": "in_progress",
        "task_class": "deployment",
        "payload": {},
    }
    tasks.find_one.side_effect = [task, task]
    change = MagicMock()
    change.modified_count = 1
    tasks.update_one.return_value = change
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        with patch.object(cor, "_lease_valid", return_value=True):
            with patch.object(cor, "_validate_pinned_model", return_value=None):
                with patch.object(cor, "_validate_completion_evidence", return_value=None):
                    with patch(
                        "inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
                        return_value={"ok": True},
                    ):
                        with patch.object(cor, "heartbeat_ops_task"):
                            with patch.object(cor, "_publish_task_event"):
                                out = cor.complete_ops_task(
                                    "ops_pause",
                                    claim_token="tok",
                                    status="blocked",
                                    evidence={"notes": HOST_GATE},
                                )
    assert out["ok"] is True
    assert out["status"] == odep.STATUS_AWAITING_DEPLOY
    assert out.get("paused") is True
    mongo_patch = tasks.update_one.call_args[0][1]["$set"]
    assert mongo_patch["status"] == odep.STATUS_AWAITING_DEPLOY
    assert mongo_patch["do_not_auto_dispatch"] is True


def test_temporal_reopen_refused_when_deploy_paused():
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    tasks.find_one.return_value = {
        "task_id": "ops_pause",
        "status": odep.STATUS_AWAITING_DEPLOY,
        "do_not_auto_dispatch": True,
        "execution_paused_for_deploy": True,
    }
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        out = otr.reopen_ops_temporal_execution("ops_pause", reason="test")
    assert out["ok"] is False
    assert out["error"] == "temporal_reopen_blocked_deploy_pause"


def test_autopilot_resume_skips_verification_and_deploy_pause():
    rows = [
        _deploy_task(status="verification", headless_execution_started_at=None),
        _deploy_task(status=odep.STATUS_AWAITING_DEPLOY),
        _deploy_task(status="in_progress", do_not_auto_dispatch=True),
        _deploy_task(status="in_progress"),
    ]
    db = MagicMock()
    col = MagicMock()
    col.find.return_value.sort.return_value.limit.return_value = rows
    db.__getitem__.return_value = col
    with patch("raphiia_openai.mongo_store.get_db", return_value=db):
        with patch.object(autopilot.lanes, "hostname", return_value="ralfiia-amd"):
            resumed = autopilot._find_resume_on_host(8)
    assert len(resumed) == 1
    assert resumed[0]["status"] == "in_progress"


def test_claim_admission_denies_awaiting_deploy():
    row = _deploy_task(status=odep.STATUS_AWAITING_DEPLOY)
    out = oaca.claim_admission(row, provider="cursor", ready=True)
    assert out["eligible"] is False
    assert out["reason"] == "execution_paused_awaiting_owner"


def test_scheduler_simulation_20_ticks_no_respawn_on_pause():
    paused = _deploy_task(
        status=odep.STATUS_AWAITING_DEPLOY,
        do_not_auto_dispatch=True,
        headless_last_result={"completion_policy_blocked": True},
    )
    for _ in range(20):
        counts = odep.simulate_autopilot_spawn_decisions([paused])
        assert counts["spawn"] == 0
        assert counts["skip"] == 1

    rng = random.Random(97310078)
    pool = []
    for i in range(1000):
        t = {
            "task_id": f"ops_{i}",
            "status": rng.choice(["queued", "in_progress", "claimed", "verification", "failed", odep.STATUS_AWAITING_DEPLOY]),
            "assignee": "cursor",
            "claim_token": "x" if rng.random() > 0.3 else None,
            "headless_execution_started_at": None,
            "do_not_auto_dispatch": rng.random() < 0.08,
            "execution_paused_for_deploy": rng.random() < 0.03,
        }
        if t["status"] == odep.STATUS_AWAITING_DEPLOY:
            t["do_not_auto_dispatch"] = True
            t["execution_paused_for_deploy"] = True
        pool.append(t)
    deploy_paused = [t for t in pool if t["status"] == odep.STATUS_AWAITING_DEPLOY]
    assert len(deploy_paused) > 10
    for t in deploy_paused:
        assert odep.headless_resume_allowed(t) is False
        assert odep.execution_automation_frozen(t) is True


def test_claimable_statuses_exclude_blocked_failed():
    assert "blocked" not in cor.CLAIM_STATUSES
    assert "failed" not in cor.CLAIM_STATUSES


def test_coding_deploy_completed_without_host_receipt_is_paused_before_temporal():
    """Real reported bug: Cursor returns completed with git/tests, no deploy receipt."""
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    task = _deploy_task(task_id="ops_code_deploy")
    tasks.find_one.return_value = task
    tasks.update_one.return_value.modified_count = 1
    ev = {"commit_sha": "a" * 40, "objective_files_count": 1,
          "objective_paths": ["fixed.py"], "test_results": {"ok": True, "exit_code": 0}}
    with patch("raphiia_openai.mongo_store.get_db", return_value=db), \
         patch.object(cor, "_lease_valid", return_value=True), \
         patch.object(cor, "_validate_pinned_model", return_value=None), \
         patch.object(cor, "_validate_completion_evidence", return_value=None), \
         patch("inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
               return_value={"ok": True}) as temporal, \
         patch.object(cor, "heartbeat_ops_task"), \
         patch.object(cor, "_publish_task_event"):
        result = cor.complete_ops_task("ops_code_deploy", claim_token="abc",
                                       status="completed", evidence=ev)
    assert result["status"] == odep.STATUS_AWAITING_DEPLOY
    assert result["paused"] is True
    assert temporal.call_args.args[2]["status"] == odep.STATUS_AWAITING_DEPLOY
    assert tasks.update_one.call_args.args[1]["$set"]["do_not_auto_dispatch"] is True


def test_transient_provider_failure_keeps_failure_not_deploy_pause():
    db = MagicMock()
    tasks = MagicMock()
    db.__getitem__.return_value = tasks
    task = {"task_id": "ops_transient", "assignee": "cursor", "status": "in_progress",
            "claim_token": "abc", "task_class": "coding", "payload": {}}
    tasks.find_one.return_value = task
    with patch("raphiia_openai.mongo_store.get_db", return_value=db), \
         patch.object(cor, "_lease_valid", return_value=True), \
         patch.object(cor, "_validate_pinned_model", return_value=None), \
         patch.object(cor, "_validate_completion_evidence", return_value=None), \
         patch("inneros_core_runtime.durable_coordination_spine.signal_task_workflow",
               return_value={"ok": True}), \
         patch.object(cor, "heartbeat_ops_task"), \
         patch.object(cor, "_publish_task_event"):
        result = cor.complete_ops_task("ops_transient", claim_token="abc",
                                       status="failed", evidence={"notes": "429 retry later"})
    assert result["status"] == "failed"
    patch_data = tasks.update_one.call_args.args[1]["$set"]
    assert patch_data["status"] == "failed"
    assert "do_not_auto_dispatch" not in patch_data


def test_deploy_receipt_does_not_pause_and_can_progress_to_verification():
    task = _deploy_task()
    ev = {"host_execution": {"executed": True}, "postconditions": {"verified": True}}
    assert odep.completion_requires_deploy_pause(task, ev) is False
    assert odep.completion_requires_deploy_pause(task, {}) is True
    assert odep.completion_requires_deploy_pause(
        {"task_class": "coding", "payload": {}}, {}
    ) is False
