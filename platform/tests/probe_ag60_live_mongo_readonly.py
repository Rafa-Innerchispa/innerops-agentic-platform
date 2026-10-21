"""Opt-in, read-only AG-60 Mongo witness probe.

Not named test_*, so this is NEVER automatically collected by CI or routine
unit tests. Invoke explicitly on authorized local AMD worktree:
  pytest -q -s platform/tests/probe_ag60_live_mongo_readonly.py
Displays only sample IDs/timestamps/status; no credentials, device data or writes.
"""
import importlib.util
import json
from pathlib import Path


def test_live_mongo_two_distinct_recent_samples():
    path = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "bellini_network_guardian.py"
    spec = importlib.util.spec_from_file_location("ag60_local_readonly_mongo_witness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = module.get_mongo_db()
    assert db is not None, "Mongo connector unavailable on test runner"
    state = db.bellini_guardian_state.find_one({"site_id": module.SITE_ID},
                                              {"_id": 0, "timestamp": 1, "site_id": 1})
    assert isinstance(state, dict) and state.get("timestamp"), "No stored current Bellini Guardian timestamp"
    proof, _ = module._read_mongo_sample_evidence(db, state["timestamp"])
    witness = {
        "site_id": module.SITE_ID,
        "current_state_timestamp": state["timestamp"],
        "proof_status": proof.get("status"),
        "two_recent_distinct_samples": proof.get("two_recent_distinct_samples"),
        "samples": [
            {"id": x.get("id"), "timestamp": x.get("timestamp"), "recent": x.get("recent")}
            for x in proof.get("samples", [])
        ],
    }
    print("AG60_MONGO_READONLY_WITNESS=" + json.dumps(witness, ensure_ascii=True, default=str))
    assert proof.get("two_recent_distinct_samples") is True, (
        "No two independently stored recent Mongo samples verified; inspect printed witness"
    )
