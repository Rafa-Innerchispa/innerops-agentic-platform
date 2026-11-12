from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

_spec = importlib.util.spec_from_file_location(
    "sync_mongo_scoped_test", PLATFORM_DIR / "scripts" / "sync_mongo_scoped.py")
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


def _live_dbs(amd_tasks, intel_tasks):
    amd, atcol, amcol = _mock_db(), MagicMock(), MagicMock()
    intel, itcol, imcol = _mock_db(), MagicMock(), MagicMock()
    atcol.find.return_value = list(amd_tasks)
    itcol.find.return_value = list(intel_tasks)
    amcol.find.return_value.limit.return_value = []
    imcol.find.return_value.limit.return_value = []
    amd.__getitem__.side_effect = lambda name: {"ralfia_ops_tasks": atcol,
                                                "ralfia_agent_messages": amcol,
                                                "sync_control": MagicMock()}[name]
    intel.__getitem__.side_effect = lambda name: {"ralfia_ops_tasks": itcol,
                                                  "ralfia_agent_messages": imcol,
                                                  "sync_control": MagicMock()}[name]
    return (amd, atcol), (intel, itcol)


def _mock_db():
    return MagicMock()


def test_apply_push_pull_write_with_stamps():
    (amd, atcol), (intel, itcol) = _live_dbs(
        [_task("t_push", rev=2), _task("t_same")],
        [_task("t_push", rev=1), _task("t_same"), _task("t_pull")],
    )
    atcol.find_one.side_effect = lambda filt, *a, **k: _task("t_push", rev=2)
    itcol.find_one.side_effect = lambda filt, *a, **k: _task("t_pull")
    manifest = dryrun.compute_manifest(amd, intel)
    out = dryrun.apply_manifest(amd, intel, manifest)
    assert {a["key"] for a in out["applied"]} == {"t_push", "t_pull"}
    written = itcol.update_one.call_args.args[1]["$set"]
    assert written["revision"] == 2
    assert written["synced_from"] == "amd"
    assert written["synced_at"]
    assert out["blocked"] == {"conflict": [], "flag_terminal_mismatch": []}
    assert out["errors"] == []


def test_apply_skips_conflicts_and_mismatches():
    live = _task("t_live", status="claimed", rev=9)
    dead = _task("t_live", status="cancelled", rev=9, updated="2026-11-12T09:35:00+00:00")
    same_a = _task("t_c", status="proposed", rev=5, updated="2026-11-12T09:00:00+00:00")
    same_b = _task("t_c", status="blocked", rev=5, updated="2026-11-12T09:00:00+00:00")
    (amd, atcol), (intel, itcol) = _live_dbs([live, same_a], [dead, same_b])
    manifest = dryrun.compute_manifest(amd, intel)
    out = dryrun.apply_manifest(amd, intel, manifest)
    assert out["applied"] == []
    assert sorted(out["blocked"]["flag_terminal_mismatch"]) == ["t_live"]
    assert sorted(out["blocked"]["conflict"]) == ["t_c"]
    atcol.update_one.assert_not_called()
    itcol.update_one.assert_not_called()


def test_apply_honors_limit():
    tasks = [_task(f"t{i}") for i in range(4)]
    (amd, atcol), (intel, itcol) = _live_dbs(tasks, [])
    itcol.find_one.side_effect = lambda filt, *a, **k: None
    atcol.find_one.side_effect = lambda filt, *a, **k: next(
        t for t in tasks if t["task_id"] == filt["task_id"])
    manifest = dryrun.compute_manifest(amd, intel)
    out = dryrun.apply_manifest(amd, intel, manifest, limit=1)
    assert len(out["applied"]) == 1
    assert out.get("truncated") is True


def test_apply_skips_stale_plan():
    fresh_equal = _task("t1", rev=1)
    (amd, atcol), (intel, itcol) = _live_dbs([_task("t1", rev=2)], [_task("t1", rev=1)])
    atcol.find_one.return_value = dict(fresh_equal)
    manifest = dryrun.compute_manifest(amd, intel)
    out = dryrun.apply_manifest(amd, intel, manifest)
    assert out["applied"] == []
    assert out["skipped"][0]["reason"] == "stale_plan_now_in_sync"


def test_kill_switch_blocks_either_side():
    off, on, missing = MagicMock(), MagicMock(), MagicMock()
    off.find_one.return_value = {"enabled": False}
    on.find_one.return_value = {"enabled": True}
    missing.find_one.return_value = None
    db_off, db_on, db_missing = MagicMock(), MagicMock(), MagicMock()
    db_off.__getitem__.return_value = off
    db_on.__getitem__.return_value = on
    db_missing.__getitem__.return_value = missing
    assert dryrun.kill_switch_engaged(db_off, db_on)[0] is True
    assert dryrun.kill_switch_engaged(db_on, db_off)[0] is True
    assert dryrun.kill_switch_engaged(db_on, db_missing)[0] is False
    assert dryrun.kill_switch_engaged(db_missing, db_missing)[0] is False


def test_build_parser_defaults_to_dry_run():
    args = dryrun.build_parser().parse_args([])
    assert args.apply is False
    assert args.limit == dryrun.DEFAULT_LIMIT
    args = dryrun.build_parser().parse_args(["--apply", "--yes", "--limit", "50",
                                             "--directions", "push"])
    assert args.apply is True and args.yes is True
    assert args.limit == 50
    assert args.directions == "push"
