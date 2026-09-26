from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import local_model_router
from inneros_core_runtime import coordination_live


def test_antigravity_routes_to_gemini_37() -> None:
    """Antigravity agent must route to Gemini 3.7 with Google vendor."""
    route = local_model_router.route_agent_model("antigravity")
    assert route["ok"] is True
    assert route["agent"] == "antigravity"
    assert route["provider"] == "antigravity"
    assert route["model"] == "gemini-3.7"
    assert route["vendor"] == "google"
    assert route["is_external"] is True
    assert "gemini-3.7" in route["available_models"]


def test_codex_routes_to_gpt_56() -> None:
    """Codex agent must route to OpenAI GPT (gpt-5.6 / gpt-sol)."""
    route = local_model_router.route_agent_model("codex")
    assert route["ok"] is True
    assert route["agent"] == "codex"
    assert route["provider"] == "codex"
    assert route["model"] == "gpt-5.6"
    assert route["vendor"] == "openai"
    assert route["is_external"] is True
    assert "gpt-5.6" in route["available_models"]
    assert "gpt-sol" in route["available_models"]


def test_cursor_routes_to_composer_25() -> None:
    """Cursor agent must route to Composer 2.5."""
    route = local_model_router.route_agent_model("cursor")
    assert route["ok"] is True
    assert route["agent"] == "cursor"
    assert route["provider"] == "cursor"
    assert route["model"] == "composer-2.5"
    assert route["vendor"] == "cursor"
    assert route["is_external"] is True
    assert "composer-2.5" in route["available_models"]


def test_local_agent_routes_to_local_model() -> None:
    """RalfIA local agent must route to local Qwen coder model."""
    route = local_model_router.route_agent_model("ralfia")
    assert route["ok"] is True
    assert route["agent"] == "ralfia"
    assert route["provider"] == "local"
    assert "Qwen" in route["model"] or "qwen" in route["model"]
    assert route["vendor"] == "qwen"
    assert route["is_external"] is False


def test_dev_swarm_routes_to_local_qwen() -> None:
    """Dev Swarm lane must route to dedicated local Qwen coder."""
    route = local_model_router.route_agent_model("dev_swarm")
    assert route["ok"] is True
    assert route["agent"] == "dev_swarm"
    assert route["provider"] == "local"
    assert route["transport"] == "vllm"
    assert route["is_external"] is False


def test_unknown_agent_falls_back_to_local_model_safely() -> None:
    """Any unspecified agent safely falls back to local execution without external spend."""
    route = local_model_router.route_agent_model("custom_internal_agent")
    assert route["ok"] is True
    assert route["provider"] == "local"
    assert route["is_external"] is False


def test_create_ops_task_auto_pins_agent_model() -> None:
    """When a task is created for an assignee, its preferred_model and preferred_provider are auto-pinned."""
    with mock.patch("raphiia_openai.mongo_store.get_db") as mock_db_getter:
        mock_coll = mock.MagicMock()
        mock_coll.find_one.return_value = None
        mock_state = mock.MagicMock()
        mock_state.find_one.return_value = {"revision": 1}
        mock_msg = mock.MagicMock()
        mock_log = mock.MagicMock()
        mock_db = {
            "ralfia_ops_tasks": mock_coll,
            "ralfia_coordination_state": mock_state,
            "ralfia_agent_messages": mock_msg,
            "ralfia_coordination_log": mock_log,
        }
        mock_db_getter.return_value = mock_db

        with mock.patch("inneros_core_runtime.coordination_live._publish_task_event"):
            with mock.patch("raphiia_openai.memory.agent_messages.create_agent_message"):
                # 1. Antigravity task
                res_ag = coordination_live.create_ops_task(
                    assignee="antigravity",
                    title="Antigravity autonomous repair",
                    checklist=["Check health"],
                    project_id="inneros",
                )
                assert res_ag["ok"] is True
                doc_ag = mock_coll.insert_one.call_args[0][0]
                assert doc_ag["preferred_provider"] == "antigravity"
                assert doc_ag["preferred_model"] == "gemini-3.7"

                # 2. Codex task
                res_codex = coordination_live.create_ops_task(
                    assignee="codex",
                    title="Codex backend refactor",
                    checklist=["Refactor endpoints"],
                    project_id="inneros",
                )
                assert res_codex["ok"] is True
                doc_codex = mock_coll.insert_one.call_args[0][0]
                assert doc_codex["preferred_provider"] == "codex"
                assert doc_codex["preferred_model"] == "gpt-5.6"
