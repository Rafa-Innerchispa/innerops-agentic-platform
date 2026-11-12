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


def test_local_swarm_probe_keeps_lane_despite_readonly_markers():
    task = {
        "task_id": "ops_probe1",
        "title": "CANARY sonda de verificacion local (solo lectura, sin cambios)",
        "objective": "Solo lectura, NO modifiques archivos. Reporta python3 --version.",
        "task_class": "verification",
        "assignee": "dev_swarm",
        "preferred_provider": "dev_swarm",
        "execution_lane": "local_dev_swarm",
        "do_not_auto_dispatch": False,
    }
    out = ota.normalize_ops_admission(task)
    assert out["execution_lane"] == "local_dev_swarm"
    assert out["task_class"] == "verification"
    assert out["do_not_auto_dispatch"] is False
    assert "admission_normalized" not in out


def test_device_read_without_agentic_lane_still_reclassified():
    task = {
        "task_id": "ops_dev1",
        "title": "Leer estado EntraPass Kantech",
        "task_class": "operational",
        "assignee": "ralfia",
        "execution_lane": "internal",
    }
    out = ota.normalize_ops_admission(task)
    assert out["execution_lane"] == "device_fabric"
    assert out["do_not_auto_dispatch"] is True


def test_repair_skips_protected_lane():
    task = {
        "task_id": "ops_probe2",
        "title": "preflight solo lectura Bellini",
        "task_class": "coding",
        "execution_lane": "local_dev_swarm",
    }
    assert ota.repair_misclassified_task(task) is None


def test_repair_still_fixes_unbound_coding_without_repo():
    task = {
        "task_id": "ops_dev2",
        "title": "preflight solo lectura Bellini",
        "task_class": "coding",
        "execution_lane": "internal",
    }
    patch = ota.repair_misclassified_task(task)
    assert patch is not None
    assert patch["execution_lane"] == "device_fabric"


def test_explicit_interactive_lanes_keep_lane_despite_readonly_markers():
    # Canary v3: cursor/codex/antigravity tasks with "Solo lectura" objectives
    # were hijacked to device_fabric at create time, which broke binding and
    # tripped the workflow circuit breaker. Explicit agentic lanes win.
    for lane in (
        "cursor_interactive",
        "codex_interactive",
        "antigravity_interactive",
        "gemini_interactive",
        "chatgpt_interactive",
        "manual_interactive",
    ):
        provider = lane.split("_")[0]
        task = {
            "task_id": f"ops_canary_{provider}",
            "title": f"[quad-canary] {provider} SHA256 AGENTS.md",
            "objective": "Solo lectura: en el worktree ejecuta git rev-parse HEAD y entrega commit_sha en evidencia.",
            "task_class": "verification",
            "assignee": provider,
            "preferred_provider": provider,
            "execution_lane": lane,
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "do_not_auto_dispatch": True,
        }
        out = ota.normalize_ops_admission(task)
        assert out["execution_lane"] == lane, lane
        assert out["task_class"] == "verification", lane
        assert out["assignee"] == provider, lane
        assert out["preferred_provider"] == provider, lane
        assert out["do_not_auto_dispatch"] is True, lane
        assert "admission_normalized" not in out, lane


def test_repair_skips_all_protected_lanes():
    for lane in (
        "local_dev_swarm",
        "cursor_interactive",
        "codex_interactive",
        "antigravity_interactive",
        "gemini_interactive",
        "chatgpt_interactive",
        "manual_interactive",
    ):
        task = {
            "task_id": f"ops_repair_{lane}",
            "title": "preflight solo lectura Bellini",
            "task_class": "coding",
            "execution_lane": lane,
        }
        assert ota.repair_misclassified_task(task) is None, lane
