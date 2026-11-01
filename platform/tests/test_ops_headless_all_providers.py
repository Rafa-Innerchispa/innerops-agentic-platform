"""Paid headless admission applies equally to Cursor, Codex, and Antigravity."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from inneros_core_runtime.ops_headless_execution_policy import headless_denial
from inneros_core_runtime import codex_headless_dispatch as codex_dispatch
from inneros_core_runtime import antigravity_headless_dispatch as ag_dispatch


def _task(provider: str) -> dict:
    return {
        "task_id": "ops_test",
        "status": "in_progress",
        "assignee": provider,
        "claim_token": "tok",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
        "payload": {},
        "execution_lane": f"{provider}_headless",
    }


@pytest.mark.parametrize("provider", ["codex", "antigravity"])
@pytest.mark.parametrize("changes", [{"status": "verification"}, {"headless_dispatch_attempts": 3}])
def test_non_cursor_providers_denied_like_cursor(provider, changes, monkeypatch):
    task = _task(provider) | deepcopy(changes)
    assert headless_denial(task, provider=provider)


@pytest.mark.parametrize("module", [codex_dispatch, ag_dispatch])
def test_spawn_never_updates_mongo_when_denied(module, monkeypatch):
    task = _task("codex" if module is codex_dispatch else "antigravity")
    task["status"] = "verification"
    coll = Mock()
    coll.find_one.return_value = task
    monkeypatch.setattr(module.mongo_store, "get_db", lambda: {module.OPS_TASKS_COL: coll})
    from inneros_core_runtime import cursor_headless_lanes as lanes
    from inneros_core_runtime import interactive_provider_lanes as ipl

    monkeypatch.setattr(lanes, "is_ha_execution_node", lambda: True)
    monkeypatch.setattr(ipl, "available_slots", lambda _p: 4)
    monkeypatch.setattr(ipl, "hostname", lambda: "intel-test")
    monkeypatch.setenv("INNEROS_CODEX_HEADLESS_EXECUTE", "1")
    monkeypatch.setenv("INNEROS_ANTIGRAVITY_HEADLESS_EXECUTE", "1")
    assert not module.spawn_headless_execute("ops_test")["ok"]
    coll.find_one_and_update.assert_not_called()
