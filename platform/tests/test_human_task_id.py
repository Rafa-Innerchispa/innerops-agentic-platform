from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import human_task_id as hti


def test_explicit_alias_normalized():
    assert hti.normalize_human_task_id("amd-league-wrapup") == "AMD-LEAGUE-WRAPUP"


def test_generate_from_correlation_override():
    alias = hti.generate_human_task_id(correlation_id="amd-ai-league-umbrella-20261019", title="Create umbrella repo")
    assert alias == "AMD-LEAGUE-WRAPUP"


def test_generate_auto_from_title():
    alias = hti.generate_human_task_id(
        correlation_id="inneros-telegram-notify-20261020",
        title="Add Telegram backup notifications",
    )
    assert alias.startswith("INNEROS-")
    assert "TELEGRAM" in alias or "ADD" in alias


def test_inherit_from_correlation_in_db():
    fake_col = mock.MagicMock()
    fake_col.find_one.return_value = {"human_task_id": "AMD-LEAGUE-WRAPUP"}
    fake_db = mock.MagicMock()
    fake_db.__getitem__.return_value = fake_col
    with mock.patch.object(hti.mongo_store, "get_db", return_value=fake_db):
        alias = hti.resolve_human_task_id_for_create(
            {"correlation_id": "amd-ai-league-umbrella-20261019", "title": "takeover", "task_id": "ops_new1"}
        )
    assert alias == "AMD-LEAGUE-WRAPUP"


def test_takeover_inherits_parent():
    fake_col = mock.MagicMock()
    fake_col.find_one.side_effect = [
        {"human_task_id": "AMD-LEAGUE-WRAPUP"},
        None,
    ]
    fake_db = mock.MagicMock()
    fake_db.__getitem__.return_value = fake_col
    with mock.patch.object(hti.mongo_store, "get_db", return_value=fake_db):
        alias = hti.resolve_human_task_id_for_create(
            {
                "parent_task_id": "ops_8dc1dbe7eddd",
                "correlation_id": "other",
                "title": "Antigravity takeover",
                "task_id": "ops_84c81dfcc896",
            }
        )
    assert alias == "AMD-LEAGUE-WRAPUP"


def test_group_same_correlation():
    tasks = [
        {"task_id": "ops_8dc1dbe7eddd", "human_task_id": "AMD-LEAGUE-WRAPUP", "status": "blocked", "assignee": "dev_swarm", "title": "dev swarm", "updated_at": "2026-10-18"},
        {"task_id": "ops_84c81dfcc896", "human_task_id": "AMD-LEAGUE-WRAPUP", "status": "awaiting_antigravity_claim", "assignee": "antigravity", "title": "umbrella", "updated_at": "2026-10-19"},
    ]
    groups = hti.group_tasks_by_human_id(tasks)
    assert len(groups) == 1
    assert groups[0]["human_task_id"] == "AMD-LEAGUE-WRAPUP"
    assert groups[0]["active"]["active_ops_task_id"] == "ops_84c81dfcc896"


def test_whatsapp_alias_first_line():
    task = {
        "task_id": "ops_84c81dfcc896",
        "human_task_id": "AMD-LEAGUE-WRAPUP",
        "status": "awaiting_antigravity_claim",
        "assignee": "antigravity",
        "correlation_id": "amd-ai-league-umbrella-20261019",
        "title": "Create AMD AI League umbrella repo now",
    }
    body = hti.format_whatsapp_owner_body(
        task=task,
        headline="🛂 EXTERNO",
        provider="antigravity",
        objective=task["title"],
        spends="gasta créditos",
        detail="",
        alert_kind="external_spend",
        short_ops_suffix="84c81d",
        related=[
            {"task_id": "ops_8dc1dbe7eddd", "status": "blocked"},
            task,
        ],
    )
    assert body.splitlines()[0] == "[AMD-LEAGUE-WRAPUP]"
    assert "OPS actual: ops_84c81dfcc896" in body
    assert "ops_8dc1dbe7eddd" in body


def test_list_line_format():
    line = hti.format_list_line(
        {
            "human_task_id": "AMD-LEAGUE-WRAPUP",
            "status": "awaiting_antigravity_claim",
            "assignee": "antigravity",
            "task_id": "ops_84c81dfcc896",
            "title": "Create umbrella",
        }
    )
    assert line.startswith("AMD-LEAGUE-WRAPUP |")


def test_find_by_alias_mock():
    fake_col = mock.MagicMock()
    fake_col.find.return_value.sort.return_value.limit.return_value = [{"task_id": "ops_84c81dfcc896"}]
    fake_db = mock.MagicMock()
    fake_db.__getitem__.return_value = fake_col
    with mock.patch.object(hti.mongo_store, "get_db", return_value=fake_db):
        rows = hti.find_tasks_by_human_task_id("AMD-LEAGUE-WRAPUP")
    assert rows[0]["task_id"] == "ops_84c81dfcc896"


def test_offline_store_without_task_collection_still_generates_alias():
    # CI's lightweight coordination store may deliberately omit this collection.
    # Alias inheritance is optional, but task admission and Temporal linkage are not.
    with mock.patch.object(hti.mongo_store, "get_db", return_value={}):
        alias = hti.resolve_human_task_id_for_create(
            {"correlation_id": "gitlab-ops-routing-20261019", "title": "Repair Dev Swarm task routing"}
        )
    assert alias.startswith("GITLAB-")
    assert alias == hti.generate_human_task_id(
        correlation_id="gitlab-ops-routing-20261019",
        title="Repair Dev Swarm task routing",
    )
