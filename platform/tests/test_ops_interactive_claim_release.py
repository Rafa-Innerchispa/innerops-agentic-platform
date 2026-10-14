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
