"""Registro único Telegram + Alexa: primera decisión gana, segunda se rechaza."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

for _name in (
    "inneros_core_runtime.coordination_live",
    "raphiia_openai",
    "raphiia_openai.mongo_store",
):
    if _name not in sys.modules:
        sys.modules[_name] = MagicMock()

_reg_path = PLATFORM_DIR / "inneros_core_runtime" / "ops_owner_decision_registry.py"
_spec = importlib.util.spec_from_file_location("ops_owner_decision_registry_test", _reg_path)
assert _spec and _spec.loader
decisions = importlib.util.module_from_spec(_spec)
sys.modules["ops_owner_decision_registry_test"] = decisions
_spec.loader.exec_module(decisions)


def _task():
    return {
        "task_id": "ops_abcdef123456",
        "assignee": "codex",
        "objective": "revisar cola",
        "correlation_id": "test-voice-approval",
        "revision": 3,
    }


def _fresh_col():
    col = MagicMock()
    col.find_one.return_value = None
    return col


def test_publish_reuses_same_nonce_before_expiry():
    col = _fresh_col()
    row = {
        "task_id": "ops_abcdef123456",
        "status": "awaiting_owner_decision",
        "scope_hash": decisions._scope_hash(_task()),
        "revision": 3,
        "nonce": "n1",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    col.find_one.return_value = row
    with patch.object(decisions, "_collection", return_value=col):
        out = decisions.publish_decision_request(_task())
    assert out["ok"] is True
    assert out["nonce"] == "n1"
    assert out.get("duplicate") is True


def test_first_decision_wins_second_rejected():
    col = MagicMock()
    row = {
        "task_id": "ops_abcdef123456",
        "status": "awaiting_owner_decision",
        "nonce": "n1",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    col.find_one.side_effect = [
        row,
        {**row, "status": "approved", "decided_by": "alexa"},
        {**row, "status": "approved", "decided_by": "alexa"},
    ]
    col.find_one_and_update.side_effect = [{**row, "status": "approved", "decided_by": "alexa"}, None]
    with patch.object(decisions, "_collection", return_value=col):
        first = decisions.consume_decision(
            task_id="ops_abcdef123456", nonce="n1", decision="approve", channel="alexa",
        )
        second = decisions.consume_decision(
            task_id="ops_abcdef123456", nonce="n1", decision="approve", channel="telegram",
        )
    assert first["ok"] is True
    assert first["decided_by"] == "alexa"
    assert second["ok"] is False
    assert second["decided_by"] == "alexa"


def test_expired_decision_rejected():
    col = MagicMock()
    col.find_one.return_value = {
        "task_id": "ops_abcdef123456",
        "status": "awaiting_owner_decision",
        "nonce": "n1",
        "expires_at": "2000-01-01T00:00:00+00:00",
    }
    with patch.object(decisions, "_collection", return_value=col):
        out = decisions.consume_decision(
            task_id="ops_abcdef123456", nonce="n1", decision="approve", channel="telegram",
        )
    assert out["ok"] is False
    assert out["error"] == "decision_not_found_or_expired"


def test_alexa_approve_uses_shared_executor():
    _alexa_path = PLATFORM_DIR / "inneros_core_runtime" / "ops_alexa_owner_auth.py"
    _aspec = importlib.util.spec_from_file_location("ops_alexa_owner_auth_test", _alexa_path)
    assert _aspec and _aspec.loader
    alexa = importlib.util.module_from_spec(_aspec)
    sys.modules["ops_alexa_owner_auth_test"] = alexa
    sys.modules["inneros_core_runtime.ops_owner_decision_registry"] = decisions
    _aspec.loader.exec_module(alexa)

    col = MagicMock()
    row = {
        "task_id": "ops_abcdef123456",
        "status": "awaiting_owner_decision",
        "nonce": "n1",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    col.find_one.return_value = row
    col.find_one_and_update.return_value = {**row, "status": "approved"}
    with (
        patch.object(decisions, "_collection", return_value=col),
        patch.object(alexa, "mongo_store") as ms,
        patch.object(alexa.shared_executor, "handle_owner_reply", return_value={"ok": True}) as h,
    ):
        ms.get_db.return_value.__getitem__.return_value.find_one.return_value = {"task_id": "ops_abcdef123456"}
        out = alexa.apply_alexa_decision(task_id="ops_abcdef123456", nonce="n1", decision="approve")
    assert out == {"ok": True}
    h.assert_called_once()
