"""Offline checks for ContributorOps canary script structure."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gitlab_contributorops_canary.py"


def _load():
    spec = importlib.util.spec_from_file_location("gitlab_contributorops_canary", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["gitlab_contributorops_canary"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_canary_module_exposes_expected_gates():
    mod = _load()
    assert mod.REPO == "gitlab-org/gitlab"
    assert mod.PROBE_REL.startswith("doc/")
    assert callable(mod.gate_auth_and_fork)
    assert callable(mod.gate_registry_and_policy)
    assert callable(mod.main)
