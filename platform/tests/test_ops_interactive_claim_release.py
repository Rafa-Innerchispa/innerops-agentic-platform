from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from inneros_core_runtime import interactive_ops_runner as ior
from inneros_core_runtime.ops_awaiting_claim import awaiting_claim_status_for_task


def test_awaiting_claim_status_antigravity_task() -> None:
    task = {
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "execution_lane": "antigravity_interactive",
    }
    assert awaiting_claim_status_for_task(task) == "awaiting_antigravity_claim"


def test_release_claim_after_worktree_failure_preserves_antigravity_status() -> None:
    from inneros_core_runtime.cursor_ops_runner import _release_claim

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = {
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "owner_authorized_at": "2026-10-14T18:00:00+00:00",
    }

    _release_claim(db, "ops_07568a25eaf7", reason="worktree_create_failed")

    update_doc = col.update_one.call_args[0][1]
    assert update_doc["$set"]["status"] == "awaiting_antigravity_claim"
    assert "claimed_by" in update_doc["$unset"]


def _mock_db():
    from unittest.mock import MagicMock

    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    col.find_one.return_value = {
        "assignee": "antigravity",
        "preferred_provider": "antigravity",
        "owner_authorized_at": "2026-10-14T18:00:00+00:00",
    }
    return db, col


def test_release_claim_persists_bounded_worktree_details() -> None:
    import json

    from inneros_core_runtime.cursor_ops_runner import _release_claim

    db, col = _mock_db()
    details = {"error": "source_repo_missing", "source_path": "/data/repos/x",
               "worktree": "/w/ops-1", "stderr": "fatal: boom " * 500}

    _release_claim(db, "ops_07568a25eaf7", reason="worktree_create_failed", details=details)

    update_doc = col.update_one.call_args[0][1]
    assert update_doc["$set"]["claim_error"] == "worktree_create_failed"
    det = update_doc["$set"]["claim_error_detail"]
    assert det["error"] == "source_repo_missing"
    assert det["source_path"] == "/data/repos/x"
    assert len(json.dumps(det)) <= 2000


def test_release_claim_without_details_clears_stale_detail() -> None:
    from inneros_core_runtime.cursor_ops_runner import _release_claim

    db, col = _mock_db()

    _release_claim(db, "ops_07568a25eaf7", reason="model_not_pinned")

    update_doc = col.update_one.call_args[0][1]
    assert update_doc["$set"]["claim_error"] == "model_not_pinned"
    assert "claim_error_detail" in update_doc["$unset"]
