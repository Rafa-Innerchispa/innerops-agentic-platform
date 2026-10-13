"""Prevent silently skipping P0 safety gates after a merge to main.

The CI path whitelist used to omit Cursor headless/Temporal recovery changes,
so merged runtime code could go to main without a new CI result.
"""
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/inneros-runtime-gates.yml"


def test_main_push_always_runs_runtime_contracts():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "\n  push:\n" in content
    push_section = content.split("\n  push:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "branches: [main]" in push_section
    assert "\n    paths:" not in push_section
    assert "\n    paths-ignore:" not in push_section


def test_runtime_gate_cannot_drop_core_coordination_regressions():
    content = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "platform/tests/test_ops_auto_claim_admission.py",
        "platform/tests/test_reconcile_ops_mongo_temporal.py",
        "platform/tests/test_execution_receipts.py",
        "platform/tests/test_main_ci_gate_trigger.py",
    )
    for test_path in required:
        assert test_path in content, f"Missing P0 runtime gate: {test_path}"
