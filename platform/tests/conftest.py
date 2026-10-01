"""Shared pytest fixtures — keep GitHub Actions offline (no Mongo/Temporal)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _offline_coordination_state_in_ci(monkeypatch: pytest.MonkeyPatch):
    if os.getenv("GITHUB_ACTIONS") != "true":
        yield
        return
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    state = {"ok": False, "state": {}}
    mock_db = MagicMock()
    mock_db.find_one.return_value = None
    mock_db.__getitem__ = MagicMock(return_value=MagicMock())
    with (
        patch("inneros_core_runtime.mcp_diagnostics.mongo_store.get_coordination_state", return_value=state),
        patch("raphiia_openai.mongo_store.get_coordination_state", return_value=state),
        patch("inneros_core_runtime.mongo_store.get_db", return_value=mock_db),
        patch("raphiia_openai.mongo_store.get_db", return_value=mock_db),
    ):
        yield
