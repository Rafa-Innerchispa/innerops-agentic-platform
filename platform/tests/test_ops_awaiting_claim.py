from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import ops_awaiting_claim as oac


def test_preferred_provider_wins_over_internal_assignee():
    task = {"assignee": "inneros_orchestrator", "preferred_provider": "codex"}
    assert oac.awaiting_claim_status_for_task(task) == "awaiting_codex_claim"


def test_claimed_by_used_without_preferred():
    task = {"assignee": "system", "claimed_by": "antigravity"}
    assert oac.awaiting_claim_status_for_task(task) == "awaiting_antigravity_claim"


def test_lane_sniffing_without_provider_fields():
    task = {"execution_lane": "antigravity_interactive"}
    assert oac.awaiting_claim_status_for_task(task) == "awaiting_antigravity_claim"


def test_internal_assignee_skipped_to_owner():
    task = {"assignee": "system", "owner": "cursor"}
    assert oac.awaiting_claim_status_for_task(task) == "awaiting_cursor_claim"


def test_external_assignee_used():
    task = {"assignee": "codex"}
    assert oac.awaiting_claim_status_for_task(task) == "awaiting_codex_claim"


def test_none_task_defaults_cursor():
    assert oac.awaiting_claim_status_for_task(None) == "awaiting_cursor_claim"


def test_unknown_provider_generic_claim():
    assert oac.awaiting_claim_status_for_provider("nope") == "awaiting_ide_claim"


def test_awaiting_claim_precedence_for_orchestrated_tasks():
    """Provider awaiting resolution for orchestrated tasks."""
    t_anti = {
        "task_id": "ops_orch_1",
        "assignee": "inneros_orchestrator",
        "preferred_provider": "antigravity",
    }
    assert oac.awaiting_claim_status_for_task(t_anti) == "awaiting_antigravity_claim"

    t_cur = {
        "task_id": "ops_orch_2",
        "assignee": "inneros_orchestrator",
        "claimed_by": "cursor",
    }
    assert oac.awaiting_claim_status_for_task(t_cur) == "awaiting_cursor_claim"

    t_codex = {
        "task_id": "ops_orch_3",
        "assignee": "dev_swarm",
        "execution_lane": "codex_interactive",
    }
    assert oac.awaiting_claim_status_for_task(t_codex) == "awaiting_codex_claim"

    t_direct = {
        "task_id": "ops_orch_4",
        "assignee": "antigravity",
    }
    assert oac.awaiting_claim_status_for_task(t_direct) == "awaiting_antigravity_claim"
