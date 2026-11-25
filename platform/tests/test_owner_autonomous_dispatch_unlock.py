from inneros_core_runtime import ops_deploy_execution_pause as odep
from inneros_core_runtime import ops_headless_execution_policy as ohep


def _autonomous_blocked():
    return {
        "task_id": "ops_test",
        "status": "claimed",
        "owner_authorized_at": "2026-01-01T00:00:00+00:00",
        "do_not_auto_dispatch": True,
        "assignee": "antigravity",
        "claim_token": "abc",
        "execution_lane": "antigravity_interactive",
        "payload": {"interaction_mode": "autonomous", "do_not_auto_dispatch": True},
    }


def test_owner_unlock_not_frozen():
    t = _autonomous_blocked()
    assert odep.owner_autonomous_dispatch_unlocked(t) is True
    assert odep.execution_automation_frozen(t) is False


def test_headless_allowed_after_owner_unlock():
    t = _autonomous_blocked()
    assert ohep.headless_denial(t, provider="antigravity") == ""


def test_still_frozen_on_deploy_pause():
    t = _autonomous_blocked()
    t["status"] = odep.STATUS_AWAITING_DEPLOY
    assert odep.execution_automation_frozen(t) is True