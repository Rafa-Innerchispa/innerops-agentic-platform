"""Synthetic canary spoofing and real CLI availability (offline, no spend)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from inneros_core_runtime import interactive_provider_bounded_executor as ipbe


def test_payload_spoof_synthetic_mode_rejected():
    spoof = {
        "payload": {
            "provider_canary": "codex",
            "execution_mode": "SYNTHETIC_CANARY",
            "synthetic_canary": True,
        }
    }
    assert ipbe.is_innocuous_canary_task(spoof, "codex") is False


def test_trusted_token_allows_canary():
    task = {
        "payload": {
            "provider_canary": "codex",
            "execution_mode": "SYNTHETIC_CANARY",
            "synthetic_canary": True,
            "synthetic_canary_auth_token": "secret-token",
        }
    }
    with patch.dict(os.environ, {"INNEROS_OPS_SYNTHETIC_CANARY_TOKEN": "secret-token"}):
        assert ipbe.is_innocuous_canary_task(task, "codex") is True


def test_codex_real_path_blocked_without_grant_and_env():
    task = {
        "task_id": "ops_real",
        "claim_token": "tok",
        "worktree": "/tmp/nope",
        "assignee": "codex",
        "owner_authorized_at": "2026-10-29T00:00:00Z",
    }
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = task
    wt = MagicMock()
    wt.is_dir.return_value = True
    wt.__truediv__ = lambda self, other: MagicMock(exists=lambda: True)
    with (
        patch.object(ipbe.mongo_store, "get_db", return_value=db),
        patch.object(ipbe, "Path", return_value=wt),
        patch.object(ipbe, "is_innocuous_canary_task", return_value=False),
        patch.dict(os.environ, {"INNEROS_CODEX_OPS_ALLOW_MODEL_EXEC": "1"}, clear=False),
        patch("inneros_core_runtime.ops_owner_approval_ha.paid_execution_allowed", return_value={"allowed": False, "error": "owner_budget_grant_required"}),
        patch.object(ipbe.ior, "complete_ops_task", return_value={"ok": True}) as complete,
    ):
        out = ipbe.execute_claimed_task("ops_real", "codex")
    assert out["error"] == "owner_budget_grant_required"
    complete.assert_called_once()
