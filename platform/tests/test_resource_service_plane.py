from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime.resource_service_plane import (
    AdmissionState,
    DynamicTokenBudget,
    NodeLiveCapacity,
    WeightedFairQueue,
    WorkloadClass,
    calculate_dynamic_token_budget,
    evaluate_workload_admission,
    get_resource_service_plane_status,
)


def test_dynamic_token_budget_preserves_p0_p1_service_reserve() -> None:
    """Dynamic token budget must deduct P0 and P1 service reserves before allocating dev tokens."""
    capacity = NodeLiveCapacity(
        node_name="intel-node",
        total_cpu_cores=16.0,
        total_ram_gb=32.0,
        total_vram_gb=12.0,
        cpu_load_ratio=0.20,
        ram_used_ratio=0.30,
        vram_used_ratio=0.35,
    )
    budget = calculate_dynamic_token_budget(capacity)
    
    assert budget.service_reserve_held is True
    # Free cores: 16 * 0.8 = 12.8; reserve: 4.0; available cpu tokens ~ 8.8
    assert budget.available_cpu_tokens == 8.8
    # Free RAM: 32 * 0.7 = 22.4; reserve: 8.0; available ram tokens ~ 14.4
    assert budget.available_ram_tokens == 14.4
    assert budget.recommended_concurrency >= 2


def test_workload_admission_admits_when_headroom_exists() -> None:
    """A standard coding task is ADMIT_NOW when healthy headroom is available."""
    capacity = NodeLiveCapacity(
        node_name="amd-node",
        total_cpu_cores=32.0,
        total_ram_gb=64.0,
        total_vram_gb=32.0,
        cpu_load_ratio=0.15,
        ram_used_ratio=0.25,
        vram_used_ratio=0.75,
    )
    budget = calculate_dynamic_token_budget(capacity)
    task = {
        "task_id": "ops_test_coding",
        "task_class": "coding",
        "priority": "normal",
        "title": "Build user auth adapter",
    }
    decision = evaluate_workload_admission(task, capacity, budget)
    assert decision["state"] == AdmissionState.ADMIT_NOW.value
    assert decision["admitted"] is True
    assert decision["workload_class"] == WorkloadClass.P3_BACKGROUND_DEV.value


def test_workload_admission_throttles_background_dev_under_pressure() -> None:
    """When system load approaches reserve boundary, P3 background dev is THROTTLED_SERVICE_RESERVE."""
    capacity = NodeLiveCapacity(
        node_name="intel-node",
        total_cpu_cores=8.0,
        total_ram_gb=16.0,
        total_vram_gb=12.0,
        cpu_load_ratio=0.88,  # high load
        ram_used_ratio=0.90,  # high RAM
        vram_used_ratio=0.50,
    )
    budget = calculate_dynamic_token_budget(capacity)
    task = {
        "task_id": "ops_test_bg_dev",
        "task_class": "coding",
        "priority": "normal",
        "title": "Batch lint cleanup",
    }
    decision = evaluate_workload_admission(task, capacity, budget)
    assert decision["state"] == AdmissionState.THROTTLED_SERVICE_RESERVE.value
    assert decision["admitted"] is False
    assert decision["reason"] == "service_reserve_protection_active"


def test_workload_admission_routes_edge_workloads_to_edge_node() -> None:
    """VigiLOS or on-site physical camera workloads return EDGE_ROUTE_REQUIRED."""
    capacity = NodeLiveCapacity(
        node_name="intel-node",
        total_cpu_cores=16.0,
        total_ram_gb=32.0,
        total_vram_gb=12.0,
        cpu_load_ratio=0.10,
        ram_used_ratio=0.20,
        vram_used_ratio=0.20,
    )
    budget = calculate_dynamic_token_budget(capacity)
    task = {
        "task_id": "ops_camera_stream",
        "task_class": "edge_vision",
        "priority": "p1",
        "title": "VigiLOS live on-site camera pipeline",
        "checklist": ["Process physical video stream on-site"],
    }
    decision = evaluate_workload_admission(task, capacity, budget)
    assert decision["state"] == AdmissionState.EDGE_ROUTE_REQUIRED.value
    assert decision["admitted"] is False
    assert decision["recommended_node"] == "bellini-edge-node"


def test_workload_admission_requires_cloud_burst_approval() -> None:
    """Cloud burst lane requires explicit owner approval ID."""
    capacity = NodeLiveCapacity(
        node_name="intel-node",
        total_cpu_cores=16.0,
        total_ram_gb=32.0,
        total_vram_gb=12.0,
        cpu_load_ratio=0.10,
        ram_used_ratio=0.20,
        vram_used_ratio=0.20,
    )
    budget = calculate_dynamic_token_budget(capacity)
    task = {
        "task_id": "ops_cloud_burst",
        "task_class": "coding",
        "priority": "p0",
        "title": "Cloud GPU burst training",
        "execution_lane": "cloud_burst",
    }
    decision = evaluate_workload_admission(task, capacity, budget)
    assert decision["state"] == AdmissionState.CLOUD_BURST_APPROVAL_REQUIRED.value
    assert decision["admitted"] is False


def test_weighted_fair_queue_interleaves_tenants_and_prevents_starvation() -> None:
    """WeightedFairQueue interleaves multiple tenant backlogs so no single tenant monopolizes workers."""
    fq = WeightedFairQueue()
    # Enqueue 4 tasks from InnerOS platform and 4 tasks from WorkForce
    for i in range(4):
        fq.push({"task_id": f"inneros_{i}", "project_id": "inneros", "title": f"InnerOS task {i}"})
        fq.push({"task_id": f"workforce_{i}", "project_id": "workforce", "title": f"Workforce task {i}"})

    selected = fq.select_next(limit=4)
    selected_tenants = [t.get("project_id") for t in selected]
    # Verify both tenants got slots (no starvation)
    assert "inneros" in selected_tenants
    assert "workforce" in selected_tenants
    assert len(selected) == 4


def test_unified_status_surface_returns_live_metrics_and_budget() -> None:
    """Unified status surface returns complete telemetry, dynamic tokens and admission policy."""
    status = get_resource_service_plane_status()
    assert status["ok"] is True
    assert "live_metrics" in status
    assert "dynamic_token_budget" in status
    assert "service_reservations" in status
    assert status["live_metrics"]["cpu_cores"] >= 1.0
    assert status["dynamic_token_budget"]["max_safe_concurrency"] >= 1
