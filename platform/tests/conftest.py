"""Shared pytest fixtures: CI must not contact real Mongo or Temporal."""
from __future__ import annotations

from contextlib import ExitStack
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
    targets = (
        ("inneros_core_runtime.mcp_diagnostics.mongo_store.get_coordination_state", state),
        ("raphiia_openai.mongo_store.get_coordination_state", state),
        ("inneros_core_runtime.mongo_store.get_db", mock_db),
        ("raphiia_openai.mongo_store.get_db", mock_db),
    )
    # Partial CI environments may not install legacy/optional bridge modules.
    # Continue to patch all importable providers without making tests load a
    # non-existent package. The AG-60 tests mock their own external clients.
    with ExitStack() as stack:
        for target, replacement in targets:
            try:
                stack.enter_context(patch(target, return_value=replacement))
            except (ImportError, AttributeError):
                continue
        yield
