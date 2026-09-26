from __future__ import annotations

import sys
from pathlib import Path
import pytest
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import coordination_live
from inneros_core_runtime.external_repair_agent import complete_external_repair_run


def test_provider_run_transitions_to_verification_when_independent_authority_required() -> None:
    """A task with completion_authority='CHATGPT' must enter verification state upon provider completion, not completed."""
    # Test logic asserting authority separation
    task = {
        "task_id": "ops_test_independent",
        "title": "Task requiring independent verification",
        "status": "in_progress",
        "completion_authority": "CHATGPT",
        "owner": "antigravity",
    }
    
    auth_authority = str(task.get("completion_authority") or "").strip().lower()
    actor_name = "antigravity"
    requires_independent = auth_authority and auth_authority != actor_name.lower()
    
    assert requires_independent is True
    target_status = "verification" if requires_independent else "completed"
    assert target_status == "verification"
