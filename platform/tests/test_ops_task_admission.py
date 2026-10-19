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
    # Explicitly reproduce package_roots=["."]; a fake worktree alone is not
    # sufficient because manifest discovery may return no package root.
    from unittest import mock

    repo = "Rafa-Innerchispa/innerops-service-ops"
    wt = Path("/tmp/fake-service-ops")
    with mock.patch.object(dss, "_primary_product_root", return_value="."):
        assert dss._is_product_code_path(repo, wt, "src/service_operations.js")
        assert dss._is_product_code_path(repo, wt, "./src/service_operations.js")
        classes = dss._implementation_write_classes(
            repo, wt, ["src/service_operations.js", "tests/service_operations.test.mjs", "src/inneros_dev_swarm/debug.js"]
        )
        assert classes == {
            "product": ["src/service_operations.js"],
            "diagnostic": ["src/inneros_dev_swarm/debug.js"],
            "other": ["tests/service_operations.test.mjs"],
        }


def test_nested_product_root_must_not_classify_outside_scope():
    from unittest import mock

    repo = "Rafa-Innerchispa/innerops-agentic-platform"
    wt = Path("/tmp/fake-nested-package")
    with mock.patch.object(dss, "_primary_product_root", return_value="services/product-a"):
        assert dss._is_product_code_path(repo, wt, "services/product-a/src/feature.py")
        assert not dss._is_product_code_path(repo, wt, "src/unscoped.py")
        assert not dss._is_product_code_path(repo, wt, "services/product-b/src/feature.py")
        assert not dss._is_product_code_path(repo, wt, "services/product-a/tests/test_feature.py")


def test_backlog_bucket_device_fabric():
    task = {
        "task_id": "ops_test1",
        "status": "waiting_for_binding",
        "title": "Bellini Kantech EntraPass preflight solo lectura",
        "task_class": "coding",
        "execution_lane": "internal",
    }
    assert dss.classify_coordination_backlog_task(task) == "needs_device_fabric_lane"
