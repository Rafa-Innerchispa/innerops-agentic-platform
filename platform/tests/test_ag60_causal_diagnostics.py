import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inneros_core_runtime"))
from ag60_causal_diagnostics import report


def sample(ids):
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "site_id": "bellini-i-ii",
            "targets": [{"asset_id": x, "online": False, "ip": "192.168.3.185"} for x in ids]}


def test_unknown_stays_unknown():
    r = report(sample(["a"]), {"inventory": []})
    assert r["incidents"][0]["type"] == "tipo no identificado"
    assert r["incidents"][0]["upstream"] == "no identificado"
    assert r["root_cause_verified"] is False


def test_known_switch_and_shared_upstream():
    inv = {"inventory": [{"asset_id": "a", "device_type": "poe_switch", "vendor": "Hikvision"}]}
    topo = {"a": {"upstream_asset_id": "s"}, "b": {"upstream_asset_id": "s"}}
    r = report(sample(["a", "b"]), inv, topo)
    assert r["incidents"][0]["type"] == "poe_switch"
    assert r["shared_upstreams"] == {"s": ["a", "b"]}
    assert r["incidents"][0]["hypotheses"][0]["confidence"] == "medium"


def test_delta_and_stale():
    r = report(sample(["b"]), {"inventory": []}, previous=sample(["a"]))
    assert r["new_offline_ids"] == ["b"]
    assert r["recovered_ids"] == ["a"]
    assert report({"targets": []}, {"inventory": []})["freshness"] == "STALE"
