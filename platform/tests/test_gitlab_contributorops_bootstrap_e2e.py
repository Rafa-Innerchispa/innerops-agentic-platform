"""GitLab ContributorOps — registry + bootstrap contract (offline + optional live dry_run)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import project_runtime_registry as prr


def test_bootstrap_fails_closed_when_project_not_registered():
    with patch.object(prr, "_find", return_value=None):
        with patch.object(prr, "_project_id", side_effect=lambda x: x or "missing"):
            with patch.object(prr, "_repo", return_value=""):
                out = prr.bootstrap_runtime(project_id="missing-project-xyz", dry_run=True)
    assert out["ok"] is False
    assert out["error"] == "project_not_registered"
    assert "project_path" not in out


def test_gitlab_contributorops_registered_in_registry():
    reg_path = prr._registry_file()
    if not reg_path.exists():
        pytest.skip("registry.json not present in this checkout")
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    entry = (data.get("projects") or {}).get("gitlab-contributorops-agent")
    assert entry is not None
    assert entry.get("repo") == "Rafa-Innerchispa/gitlab-contributorops-agent"
    assert "gitlab-contributorops-agent" in (entry.get("paths") or {}).get("primary", "")


@pytest.mark.skipif(os.getenv("GITLAB_E2E_LIVE") != "1", reason="set GITLAB_E2E_LIVE=1 for node helper dry_run")
def test_live_dry_run_bootstrap_gitlab_contributorops_agent():
    resolved = prr.resolve_project(project_id="gitlab-contributorops-agent")
    assert resolved.get("ok") is True, resolved
    out = prr.bootstrap_runtime(
        project_id="gitlab-contributorops-agent",
        correlation_id="gitlab-contributorops-20261001",
        dry_run=True,
    )
    assert out.get("ok") is True, out
    assert out.get("dry_run") is True
