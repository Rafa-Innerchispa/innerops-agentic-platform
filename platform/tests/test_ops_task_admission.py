from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import ops_task_admission as ota
from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime import dev_swarm_scheduler as dss


def test_device_fabric_read_normalization():
    task = {
        "title": "Bellini III-IV | preflight Kantech EntraPass red 0 (solo lectura)",
        "objective": "Diagnosticar mediante Device Fabric sin intervenir equipos",
        "task_class": "coding",
        "execution_lane": "internal",
        "repo": None,
        "assignee": "inneros_orchestrator",
    }
    out = ota.normalize_ops_admission(task)
    assert out["execution_lane"] == "device_fabric"
    assert out["task_class"] == "operational"
    binding = eb.resolve_execution_binding(out)
    assert binding["allowed"] is True
    assert binding["runner"] == eb.DEVICE_FABRIC_RUNNER


def test_flat_product_root_counts_src_as_product():
    from pathlib import Path

    wt = Path("/tmp/fake-service-ops")
    assert dss._is_product_code_path("Rafa-Innerchispa/innerops-service-ops", wt, "src/service_operations.js") is True


def test_backlog_bucket_device_fabric():
    task = {
        "task_id": "ops_test1",
        "status": "waiting_for_binding",
        "title": "Bellini Kantech EntraPass preflight solo lectura",
        "task_class": "coding",
        "execution_lane": "internal",
    }
    assert dss.classify_coordination_backlog_task(task) == "needs_device_fabric_lane"
