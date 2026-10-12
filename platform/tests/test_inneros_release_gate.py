"""Offline tests: no GitHub release is trusted without both on-host receipts."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inneros_release_gate.py"
SPEC = importlib.util.spec_from_file_location("release_gate_under_test", SCRIPT)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
SHA = "a" * 40
NOW = datetime(2026, 10, 12, 16, 30, tzinfo=timezone.utc)


def host(node):
    return {
        "verified": True, "runtime_git_sha": SHA,
        "evidence_path": "var/evidence/" + node + "/release.json",
        "runtime_import_sha256": "b" * 64,
        "runtime_pid": 123,
        "tests_exit_code": 0, "smoke_exit_code": 0,
        "rollback_snapshot": node + "-snapshot",
        "verified_at_utc": NOW.isoformat(),
    }


def attestation():
    return {"schema": "inneros-runtime-host-attestation-v1",
            "hosts": {"amd": host("amd"), "intel": host("intel")}}


def last_known_good():
    return {"schema": "inneros-last-known-good-v1", "status": "UNSET",
            "git_sha": None, "release_tag": None, "hosts": {}}


def test_actual_uncertified_hosts_must_block_version_publication():
    att = json.loads((ROOT / "docs" / "INNEROS_RELEASE_ATTESTATION.json").read_text())
    lkg = json.loads((ROOT / "docs" / "INNEROS_LAST_KNOWN_GOOD.json").read_text())
    report = gate.evaluate(SHA, att, lkg, NOW)
    assert report["status"] == "BLOCKED"
    assert "amd:not_attested" in report["blockers"]
    assert "intel:not_attested" in report["blockers"]
    assert report["github_release_authorized_by_this_check"] is False


def test_complete_metadata_still_needs_live_independent_confirmation():
    result = gate.evaluate(SHA, attestation(), last_known_good(), NOW)
    assert result["host_metadata_complete"]
    assert result["status"] == "HOST_METADATA_PRESENT_RECHECK_REQUIRED"
    assert result["production_runtime_verified_by_this_check"] is False
    assert result["github_release_authorized_by_this_check"] is False


def test_wrong_sha_or_duplicate_receipt_blocks():
    att = attestation()
    att["hosts"]["intel"]["runtime_git_sha"] = "c" * 40
    att["hosts"]["intel"]["evidence_path"] = att["hosts"]["amd"]["evidence_path"]
    result = gate.evaluate(SHA, att, last_known_good(), NOW)
    assert "intel:runtime_sha_mismatch" in result["blockers"]
    assert "host_receipts_must_be_distinct" in result["blockers"]


def test_stale_pid_smoke_and_rollback_fail_closed():
    att = attestation()
    att["hosts"]["intel"]["runtime_pid"] = True
    att["hosts"]["intel"]["rollback_snapshot"] = ""
    att["hosts"]["intel"]["verified_at_utc"] = (NOW - timedelta(days=2)).isoformat()
    att["hosts"]["amd"]["smoke_exit_code"] = 1
    result = gate.evaluate(SHA, att, last_known_good(), NOW)
    assert "intel:pid_missing" in result["blockers"]
    assert "intel:rollback_snapshot_missing" in result["blockers"]
    assert "intel:receipt_stale" in result["blockers"]
    assert "amd:smoke_not_passed" in result["blockers"]


def test_lkg_certified_without_real_refs_is_rejected():
    lkg = last_known_good()
    lkg.update({"status": "CERTIFIED", "git_sha": "short",
                "release_tag": "v1", "hosts": {"amd": {}, "intel": {}}})
    result = gate.evaluate(SHA, attestation(), lkg, NOW)
    assert "invalid_lkg_git_sha" in result["blockers"]
    assert "invalid_lkg_release_tag" in result["blockers"]
    assert "lkg_missing_node_rollback" in result["blockers"]


def test_unpinned_sha_or_incorrect_payload_is_invalid():
    with pytest.raises(ValueError, match="candidate_must_be_full"):
        gate.evaluate("main", attestation(), last_known_good(), NOW)
    with pytest.raises(ValueError, match="invalid_manifest_type"):
        gate.evaluate(SHA, None, last_known_good(), NOW)


def test_preflight_cannot_mutate_deployment_or_github():
    code = SCRIPT.read_text()
    assert "github_release_authorized_by_this_check" in code
    assert "subprocess" not in code
    assert "os.system" not in code
    assert "git push" not in code
    assert "rsync" not in code
