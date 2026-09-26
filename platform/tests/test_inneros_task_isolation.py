from __future__ import annotations

import sys
from pathlib import Path
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime.external_repair_agent import (
    evaluate_task_claim_eligibility,
    classify_nonterminal_task,
    _candidate_tasks,
)


def test_manual_interactive_is_never_eligible() -> None:
    """Tasks in manual_interactive lane must be marked NOT_ELIGIBLE / WAIT_MANUAL and excluded from auto-claim."""
    task = {
        "task_id": "ops_10f0390de4d0",
        "title": "P0 InnerOS task isolation and control-plane convergence",
        "status": "proposed",
        "execution_lane": "manual_interactive",
        "task_class": "platform_convergence",
        "assignee": "antigravity",
    }
    elig = evaluate_task_claim_eligibility(task, provider="antigravity")
    assert elig["eligible"] is False
    assert "manual_lane" in elig["reasons"]

    summary = classify_nonterminal_task(task)
    assert summary["bucket"] == "PROPOSED"
    assert summary["action"] == "WAIT_MANUAL"


def test_autonomy_disabled_is_never_eligible() -> None:
    """Tasks with autonomous_eligible=False must be excluded from auto-claim."""
    task = {
        "task_id": "ops_test_no_auto",
        "title": "Test task with autonomy disabled",
        "status": "proposed",
        "execution_lane": "antigravity_autonomous",
        "autonomous_eligible": False,
        "task_class": "coding",
        "assignee": "antigravity",
    }
    elig = evaluate_task_claim_eligibility(task, provider="antigravity")
    assert elig["eligible"] is False
    assert "autonomy_disabled" in elig["reasons"]


def test_conversation_and_email_scope_is_isolated() -> None:
    """Tasks originating from conversation or email_review must not be claimed by global autonomous queues."""
    conv_task = {
        "task_id": "ops_test_conv",
        "title": "Interactive chat discussion",
        "status": "proposed",
        "scope": "conversation",
        "origin_type": "conversation",
        "execution_lane": "chat_session",
        "task_class": "discussion",
        "assignee": "antigravity",
    }
    elig_conv = evaluate_task_claim_eligibility(conv_task, provider="antigravity")
    assert elig_conv["eligible"] is False
    assert "conversation_scope" in elig_conv["reasons"]

    email_task = {
        "task_id": "ops_test_email",
        "title": "[Correo/AG-05] Incoming message review",
        "status": "proposed",
        "scope": "email_review",
        "origin_type": "email_review",
        "execution_lane": "email_triage",
        "task_class": "email_classification",
        "assignee": "ralfia",
    }
    elig_email = evaluate_task_claim_eligibility(email_task, provider="antigravity")
    assert elig_email["eligible"] is False


def test_valid_global_autonomous_task_is_eligible() -> None:
    """Properly configured global autonomous task is eligible for claim."""
    task = {
        "task_id": "ops_test_valid_auto",
        "title": "Fix repository bug",
        "status": "proposed",
        "scope": "global",
        "origin_type": "global",
        "execution_lane": "antigravity_autonomous",
        "task_class": "agent_runtime_repair",
        "assignee": "antigravity",
        "autonomous_eligible": True,
    }
    elig = evaluate_task_claim_eligibility(task, provider="antigravity")
    assert elig["eligible"] is True
    assert len(elig["reasons"]) == 0

    summary = classify_nonterminal_task(task)
    assert summary["bucket"] == "PROPOSED"
    assert summary["action"] == "ELIGIBLE_FOR_CLAIM"
