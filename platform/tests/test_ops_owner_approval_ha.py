"""Owner approval HA view: budget unknown≠0, grant gate, push hook."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from inneros_core_runtime import ops_owner_approval_ha as oah


def test_natural_language_budget_unknown_not_zero():
    parsed = oah.parse_natural_language_budget("haz algo sin presupuesto")
    assert parsed["quote_usd_max"] is None
    assert parsed["token_limit"] is None
    assert parsed["credit_limit"] is None


def test_parse_budget_fields():
    text = "provider: codex model: gpt-5.6-sol usd: 1.5-3.0 tokens: 12000 credits: 50 expires: 2026-11-01"
    parsed = oah.parse_natural_language_budget(text)
    assert parsed["provider"] == "codex"
    assert parsed["model"] == "gpt-5.6-sol"
    assert parsed["quote_usd_min"] == 1.5
    assert parsed["quote_usd_max"] == 3.0
    assert parsed["token_limit"] == 12000
    assert parsed["credit_limit"] == 50.0


def test_paid_execution_blocked_without_grant():
    task = {
        "task_id": "ops_paid",
        "assignee": "codex",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
    }
    db = MagicMock()
    tasks = MagicMock()
    grants = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == oah.OPS_TASKS_COL else grants
    tasks.find_one.return_value = task
    grants.find_one.return_value = None
    with patch.object(oah.mongo_store, "get_db", return_value=db):
        out = oah.paid_execution_allowed("ops_paid", provider="codex")
    assert out["allowed"] is False
    assert out["error"] == "owner_budget_grant_required"


def test_record_grant_idempotent():
    db = MagicMock()
    grants = MagicMock()
    events = MagicMock()
    db.__getitem__.side_effect = lambda n: grants if n == oah.COL_GRANTS else events
    grants.find_one.side_effect = [None, {"grant_id": "grant_abc", "status": "active"}]
    with patch.object(oah.mongo_store, "get_db", return_value=db):
        first = oah.record_owner_grant("ops_paid", idempotency_key="idem-1", usd_limit=2.5)
        second = oah.record_owner_grant("ops_paid", idempotency_key="idem-1", usd_limit=2.5)
    assert first["ok"] and second.get("duplicate") is True
    grants.insert_one.assert_called_once()


def test_record_grant_requires_durable_limits():
    out = oah.record_owner_grant("ops_paid", idempotency_key="no-limits")
    assert out["ok"] is False
    assert out["error"] == "owner_grant_limits_required"


def test_paid_execution_blocked_when_grant_limits_null():
    task = {
        "task_id": "ops_paid",
        "assignee": "codex",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
    }
    grant = {"grant_id": "g1", "usd_limit": None, "token_limit": None, "credit_limit": None}
    db = MagicMock()
    tasks = MagicMock()
    grants = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == oah.OPS_TASKS_COL else grants
    tasks.find_one.return_value = task
    grants.find_one.return_value = grant
    with patch.object(oah.mongo_store, "get_db", return_value=db):
        out = oah.paid_execution_allowed("ops_paid", provider="codex")
    assert out["allowed"] is False
    assert out["error"] == "owner_grant_limits_required"


def test_paid_execution_allowed_with_limits_and_journal_under_cap():
    task = {
        "task_id": "ops_paid",
        "assignee": "codex",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
        "model_execution_journal": [{"usage": {"input_tokens": 100, "output_tokens": 50, "usd": 0.5}}],
    }
    grant = {
        "grant_id": "g1",
        "usd_limit": 2.0,
        "token_limit": 5000,
        "credit_limit": None,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "provider": "codex",
    }
    db = MagicMock()
    tasks = MagicMock()
    grants = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == oah.OPS_TASKS_COL else grants
    tasks.find_one.return_value = task
    grants.find_one.return_value = grant
    with patch.object(oah.mongo_store, "get_db", return_value=db):
        out = oah.paid_execution_allowed("ops_paid", provider="codex")
    assert out["allowed"] is True


def test_paid_execution_blocked_zero_estimate_not_verified():
    task = {
        "task_id": "ops_paid",
        "assignee": "codex",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
        "payload": {"budget_estimate": {"usd_max": 0}},
    }
    grant = {"grant_id": "g1", "usd_limit": 1.0, "token_limit": 1000, "expires_at": "2099-01-01T00:00:00+00:00"}
    db = MagicMock()
    tasks = MagicMock()
    grants = MagicMock()
    db.__getitem__.side_effect = lambda n: tasks if n == oah.OPS_TASKS_COL else grants
    tasks.find_one.return_value = task
    grants.find_one.return_value = grant
    with patch.object(oah.mongo_store, "get_db", return_value=db):
        out = oah.paid_execution_allowed("ops_paid", provider="codex")
    assert out["allowed"] is False
    assert out["error"] == "owner_budget_estimate_zero_not_verified"


def test_push_owner_approval_ha_uses_checkpoint():
    view = {"ok": True, "task_id": "ops_x", "budget": {"natural_language": {}, "estimate": {}, "observed": {}}}
    with (
        patch.object(oah, "build_owner_approval_view", return_value=view),
        patch("inneros_core_runtime.ops_owner_checkpoint.publish_ops_owner_checkpoint", return_value={"ok": True}) as pub,
        patch.object(oah.mongo_store, "get_db") as gdb,
    ):
        gdb.return_value.__getitem__.return_value.find_one.return_value = {"task_id": "ops_x"}
        out = oah.push_owner_approval_ha("ops_x", notes="test")
    assert out["ok"] is True
    pub.assert_called_once()
