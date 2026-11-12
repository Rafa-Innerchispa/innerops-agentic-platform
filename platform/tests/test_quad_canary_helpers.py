from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

_spec = importlib.util.spec_from_file_location(
    "ops_quad_lane_canary_test", PLATFORM_DIR / "scripts" / "ops_quad_lane_canary.py")
assert _spec and _spec.loader
canary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canary)


def test_extract_flat_candidate_evidence():
    final = {"candidate_evidence": {"commit_sha": "aaa111"}}
    assert canary.extract_evidence_sha(final) == "aaa111"


def test_extract_flat_evidence():
    final = {"evidence": {"commit_sha": "bbb222"}}
    assert canary.extract_evidence_sha(final) == "bbb222"


def test_extract_nested_agent_result_dev_swarm_shape():
    # Real canary-v3 dev_swarm evidence shape (was missed -> None).
    final = {"evidence": {"agent_result": {
        "commit_sha": "69b894fb",
        "evidence": {"commit_sha": "69b894fb"},
    }}}
    assert canary.extract_evidence_sha(final) == "69b894fb"


def test_extract_gate_verification_fallback():
    final = {"evidence": {"gate_verification": {"commit_sha": "ccc333"}}}
    assert canary.extract_evidence_sha(final) == "ccc333"


def test_extract_missing_returns_none():
    assert canary.extract_evidence_sha({}) is None
    assert canary.extract_evidence_sha({"evidence": {}}) is None


def test_shas_match_all_four_equal():
    lanes = [{"evidence_commit": "69b894fb"} for _ in range(4)]
    match, shared = canary.evidence_shas_match(lanes)
    assert match is True
    assert shared == "69b894fb"


def test_shas_match_single_lane_is_not_a_match():
    # Canary v3 flaw: 1 evidencing lane of 4 returned True (vacuous).
    lanes = [{"evidence_commit": None},
             {"evidence_commit": "69b894fb"},
             {"evidence_commit": None},
             {"evidence_commit": None}]
    match, shared = canary.evidence_shas_match(lanes)
    assert match is False
    assert shared == ["69b894fb"]


def test_shas_match_distinct_shas():
    lanes = [{"evidence_commit": "aaa111"}, {"evidence_commit": "bbb222"}]
    match, shared = canary.evidence_shas_match(lanes)
    assert match is False
    assert shared == ["aaa111", "bbb222"]


def test_shas_match_empty_lanes():
    match, shared = canary.evidence_shas_match([])
    assert match is False
    assert shared == []
