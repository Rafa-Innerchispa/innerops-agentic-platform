from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

_spec = importlib.util.spec_from_file_location(
    "sync_mongo_scoped_dryrun_test", PLATFORM_DIR / "scripts" / "sync_mongo_scoped_dryrun.py")
assert _spec and _spec.loader
dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dryrun)


def _task(tid, status="proposed", rev=1, updated="2026-11-12T09:00:00+00:00", **kw):
    doc = {"task_id": tid, "status": status, "revision": rev, "updated_at": updated}
    doc.update(kw)
    return doc


def test_missing_either_side_syncs():
    assert dryrun.compare_pair(None, _task("t1"), "ralfia_ops_tasks")["action"] == "pull"
    assert dryrun.compare_pair(_task("t1"), None, "ralfia_ops_tasks")["action"] == "push"


def test_identical_content_in_sync():
    assert dryrun.compare_pair(_task("t1"), _task("t1"), "ralfia_ops_tasks")["action"] == "in_sync"


def test_higher_revision_wins_either_direction():
    old, new = _task("t1", rev=3), _task("t1", rev=4, updated="2026-11-12T09:05:00+00:00")
    assert dryrun.compare_pair(old, new, "ralfia_ops_tasks")["action"] == "pull"
    assert dryrun.compare_pair(new, old, "ralfia_ops_tasks")["action"] == "push"


def test_timestamp_breaks_revision_ties():
    a = _task("t1", rev=5, updated="2026-11-12T09:00:00+00:00")
    b = _task("t1", rev=5, updated="2026-11-12T09:30:00+00:00", status="claimed")
    assert dryrun.compare_pair(a, b, "ralfia_ops_tasks")["action"] == "pull"


def test_bad_timestamps_fall_back_to_epoch_deterministically():
    a = _task("t1", rev=5, updated="not-a-date")
    b = _task("t1", rev=5, updated="2026-11-12T09:30:00+00:00", status="claimed")
    assert dryrun.compare_pair(a, b, "ralfia_ops_tasks")["action"] == "pull"


def test_terminal_mismatch_flagged_never_auto():
    live = _task("t1", status="claimed", rev=9)
    dead = _task("t1", status="cancelled", rev=9, updated="2026-11-12T09:35:00+00:00")
    out = dryrun.compare_pair(live, dead, "ralfia_ops_tasks")
    assert out["action"] == "flag_terminal_mismatch"


def test_same_version_different_content_is_conflict():
    a = _task("t1", rev=5, updated="2026-11-12T09:00:00+00:00", status="proposed")
    b = _task("t1", rev=5, updated="2026-11-12T09:00:00+00:00", status="blocked")
    out = dryrun.compare_pair(a, b, "ralfia_ops_tasks")
    assert out["action"] == "conflict"


def test_messages_use_message_id_and_scores():
    a = {"message_id": "m1", "status": "open"}
    assert dryrun.compare_pair(a, None, "ralfia_agent_messages")["action"] == "push"
    assert dryrun.compare_pair(None, a, "ralfia_agent_messages")["action"] == "pull"


def _fake_db(tasks, messages):
    db = MagicMock()
    tcol, mcol = MagicMock(), MagicMock()
    tcol.find.return_value = list(tasks)
    mcol.find.return_value.limit.return_value = list(messages)
    db.__getitem__.side_effect = lambda name: {"ralfia_ops_tasks": tcol,
                                               "ralfia_agent_messages": mcol}[name]
    return db, tcol, mcol


def test_compute_manifest_counts_and_never_writes():
    amd, _, _ = _fake_db([_task("same"), _task("amd-newer", rev=2)],
                         [{"message_id": "m1", "status": "open"}])
    intel, _, _ = _fake_db([_task("same"), _task("amd-newer", rev=1),
                            _task("intel-only")], [])
    out = dryrun.compute_manifest(amd, intel)
    assert out["collections"]["tasks"]["actions"]["push"] == 1
    assert out["collections"]["tasks"]["actions"]["pull"] == 1
    assert out["collections"]["tasks"]["actions"]["in_sync"] == 1
    assert "amd-newer" in out["collections"]["tasks"]["samples"]["push"]
    for mock_db in (amd, intel):
        for col in (mock_db["ralfia_ops_tasks"], mock_db["ralfia_agent_messages"]):
            col.update_one.assert_not_called()
            col.insert_one.assert_not_called()
            col.insert_many.assert_not_called()
            col.delete_one.assert_not_called()
            col.delete_many.assert_not_called()


def test_module_performs_zero_writes_by_construction():
    source = Path(dryrun.__file__).read_text(encoding="utf-8")
    for forbidden in ("update_one", "update_many", "insert_one", "insert_many",
                      "delete_one", "delete_many", "bulk_write", "drop(",
                      "find_one_and_update", "find_one_and_replace", "replace_one"):
        assert forbidden not in source
