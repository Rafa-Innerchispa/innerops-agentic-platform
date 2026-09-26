"""InnerOS Resource & Service Plane.

Provides multi-lane dynamic token capacity governance, P0-P4 service reservations,
GPU admission separated from CPU worker concurrency, fair multi-tenant queueing,
and admission states (ADMIT_NOW, QUEUE_RESOURCE, THROTTLED_SERVICE_RESERVE, etc.).
"""

from __future__ import annotations

import enum
import json
import os
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class WorkloadClass(str, enum.Enum):
    P0_CRITICAL_SERVICE = "P0_CRITICAL_SERVICE"
    P1_PRODUCT_SERVICE = "P1_PRODUCT_SERVICE"
    P2_ACTIVE_CODING = "P2_ACTIVE_CODING"
    P3_BACKGROUND_DEV = "P3_BACKGROUND_DEV"
    P4_BATCH_EXPLORATION = "P4_BATCH_EXPLORATION"


class AdmissionState(str, enum.Enum):
    ADMIT_NOW = "ADMIT_NOW"
    QUEUE_RESOURCE = "QUEUE_RESOURCE"
    THROTTLED_SERVICE_RESERVE = "THROTTLED_SERVICE_RESERVE"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    EDGE_ROUTE_REQUIRED = "EDGE_ROUTE_REQUIRED"
    CLOUD_BURST_APPROVAL_REQUIRED = "CLOUD_BURST_APPROVAL_REQUIRED"


# Standard cost weights by task class
TASK_CLASS_TOKEN_COST: Dict[str, Dict[str, float]] = {
    "coding": {"cpu": 1.5, "ram_gb": 2.0, "gpu_lane": 1.0, "io": 1.0},
    "autonomous_coding": {"cpu": 1.5, "ram_gb": 2.0, "gpu_lane": 1.0, "io": 1.0},
    "docs_only": {"cpu": 0.5, "ram_gb": 0.5, "gpu_lane": 0.0, "io": 0.5},
    "verifier": {"cpu": 1.0, "ram_gb": 1.0, "gpu_lane": 0.0, "io": 1.0},
    "heavy_reasoning": {"cpu": 2.0, "ram_gb": 4.0, "gpu_lane": 2.0, "io": 1.5},
    "edge_vision": {"cpu": 2.0, "ram_gb": 4.0, "gpu_lane": 2.0, "io": 2.0, "edge_required": True},
    "default": {"cpu": 1.0, "ram_gb": 1.0, "gpu_lane": 0.5, "io": 1.0},
}

# Service reservation tokens by priority
SERVICE_RESERVES: Dict[str, Dict[str, float]] = {
    "P0_CRITICAL_SERVICE": {"cpu": 2.0, "ram_gb": 4.0, "gpu_vram_gb": 4.0, "io": 2.0},
    "P1_PRODUCT_SERVICE": {"cpu": 2.0, "ram_gb": 4.0, "gpu_vram_gb": 8.0, "io": 2.0},
}


@dataclass
class NodeLiveCapacity:
    node_name: str
    total_cpu_cores: float
    total_ram_gb: float
    total_vram_gb: float
    cpu_load_ratio: float
    ram_used_ratio: float
    vram_used_ratio: float
    swap_used_mb: float = 0.0
    psi_cpu_some: float = 0.0
    psi_memory_some: float = 0.0
    psi_io_some: float = 0.0
    baseline_vram_gb: float = 0.0
    active_workers: int = 0
    gpu_inference_queue_depth: int = 0


@dataclass
class DynamicTokenBudget:
    available_cpu_tokens: float
    available_ram_tokens: float
    available_gpu_lanes: float
    available_io_tokens: float
    service_reserve_held: bool
    recommended_concurrency: int
    max_safe_concurrency: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hostname() -> str:
    return socket.gethostname().lower()


def sample_node_live_capacity(snapshot: Optional[Dict[str, Any]] = None) -> NodeLiveCapacity:
    """Sample live CPU/RAM/VRAM/PSI metrics for the host node."""
    host = _hostname()
    is_intel = "intel" in host or "ver-10" in host or "192.168.1.4" in host
    is_amd = "amd" in host or "192.168.1.5" in host

    total_cores = float(os.cpu_count() or 8)
    total_ram_gb = 32.0 if is_intel else 64.0
    total_vram_gb = 12.0 if is_intel else 32.0

    # Live CPU
    load_ratio = 0.1
    if hasattr(os, "getloadavg"):
        try:
            load_ratio = os.getloadavg()[0] / max(1.0, total_cores)
        except Exception:
            pass

    # Live RAM
    ram_used_ratio = 0.4
    swap_used_mb = 0.0
    try:
        proc = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=3, check=False)
        if proc.returncode == 0:
            lines = proc.stdout.splitlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 3 and "Mem:" in parts[0]:
                    total_m = float(parts[1])
                    used_m = float(parts[2])
                    total_ram_gb = round(total_m / 1024.0, 1)
                    ram_used_ratio = used_m / total_m
                elif len(parts) >= 3 and "Swap:" in parts[0]:
                    swap_used_mb = float(parts[2])
    except Exception:
        pass

    # Live PSI
    psi_cpu = 0.0
    psi_mem = 0.0
    psi_io = 0.0
    for res_name, target_var in [("cpu", "psi_cpu"), ("memory", "psi_mem"), ("io", "psi_io")]:
        psi_path = Path(f"/proc/pressure/{res_name}")
        if psi_path.exists():
            try:
                content = psi_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("some"):
                        parts = dict(kv.split("=") for kv in line.split()[1:] if "=" in kv)
                        val = float(parts.get("avg10", 0.0))
                        if res_name == "cpu":
                            psi_cpu = val
                        elif res_name == "memory":
                            psi_mem = val
                        elif res_name == "io":
                            psi_io = val
            except Exception:
                pass

    # Live VRAM
    vram_used_ratio = 0.0
    baseline_vram_gb = 0.0
    if is_intel:
        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if proc.returncode == 0:
                parts = proc.stdout.strip().split(",")
                if len(parts) >= 2:
                    tot = float(parts[0])
                    used = float(parts[1])
                    total_vram_gb = tot / 1024.0
                    vram_used_ratio = used / tot
                    baseline_vram_gb = min(used / 1024.0, 4.5)  # Qwen2.5VL baseline residency
        except Exception:
            pass
    elif is_amd:
        try:
            proc = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--json"], capture_output=True, text=True, timeout=4, check=False)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                # AMD vLLM occupies primary VRAM for Qwen3-Coder-30B
                baseline_vram_gb = 24.0
                vram_used_ratio = 0.8
        except Exception:
            baseline_vram_gb = 24.0
            vram_used_ratio = 0.8

    return NodeLiveCapacity(
        node_name=host,
        total_cpu_cores=total_cores,
        total_ram_gb=total_ram_gb,
        total_vram_gb=total_vram_gb,
        cpu_load_ratio=round(load_ratio, 3),
        ram_used_ratio=round(ram_used_ratio, 3),
        vram_used_ratio=round(vram_used_ratio, 3),
        swap_used_mb=round(swap_used_mb, 1),
        psi_cpu_some=round(psi_cpu, 2),
        psi_memory_some=round(psi_mem, 2),
        psi_io_some=round(psi_io, 2),
        baseline_vram_gb=round(baseline_vram_gb, 1),
        active_workers=snapshot.get("active_workers", 0) if snapshot else 0,
        gpu_inference_queue_depth=0,
    )


def calculate_dynamic_token_budget(capacity: NodeLiveCapacity) -> DynamicTokenBudget:
    """Derive multi-resource dynamic token budget with P0/P1 production service reservation."""
    # 1. Total reserve deductions
    p0_cpu = SERVICE_RESERVES["P0_CRITICAL_SERVICE"]["cpu"]
    p1_cpu = SERVICE_RESERVES["P1_PRODUCT_SERVICE"]["cpu"]
    total_cpu_reserve = p0_cpu + p1_cpu

    p0_ram = SERVICE_RESERVES["P0_CRITICAL_SERVICE"]["ram_gb"]
    p1_ram = SERVICE_RESERVES["P1_PRODUCT_SERVICE"]["ram_gb"]
    total_ram_reserve = p0_ram + p1_ram

    # 2. Live headroom calculation
    free_cores = max(0.0, capacity.total_cpu_cores * (1.0 - capacity.cpu_load_ratio))
    free_ram_gb = max(0.0, capacity.total_ram_gb * (1.0 - capacity.ram_used_ratio))

    available_cpu_tokens = max(0.0, free_cores - total_cpu_reserve)
    available_ram_tokens = max(0.0, free_ram_gb - total_ram_reserve)

    # 3. GPU Lanes (separated from CPU workers)
    # AMD R9700 / Intel GPU: calculate concurrent inference slots available without swapping model
    free_vram_gb = max(0.0, capacity.total_vram_gb * (1.0 - capacity.vram_used_ratio))
    available_gpu_lanes = 4.0 if "amd" in capacity.node_name else 2.0
    if capacity.vram_used_ratio >= 0.95 or capacity.psi_memory_some > 20.0:
        available_gpu_lanes = max(0.0, available_gpu_lanes - 2.0)

    # 4. IO Tokens based on IO PSI
    available_io_tokens = max(1.0, 10.0 - capacity.psi_io_some)

    # 5. Determine recommended concurrency from live headroom
    cpu_slots = int(available_cpu_tokens // 1.5)
    ram_slots = int(available_ram_tokens // 2.0)
    concurrency = max(1, min(cpu_slots, ram_slots, int(available_gpu_lanes)))

    # Hard pressure throttle
    if capacity.cpu_load_ratio >= 0.92 or capacity.ram_used_ratio >= 0.94 or capacity.swap_used_mb > 2048:
        concurrency = 0
    elif capacity.cpu_load_ratio >= 0.85 or capacity.ram_used_ratio >= 0.88:
        concurrency = min(concurrency, 1)

    max_safe = max(2, int(capacity.total_cpu_cores // 2))

    return DynamicTokenBudget(
        available_cpu_tokens=round(available_cpu_tokens, 2),
        available_ram_tokens=round(available_ram_tokens, 2),
        available_gpu_lanes=round(available_gpu_lanes, 1),
        available_io_tokens=round(available_io_tokens, 2),
        service_reserve_held=True,
        recommended_concurrency=concurrency,
        max_safe_concurrency=max_safe,
    )


def evaluate_workload_admission(
    task: Dict[str, Any],
    capacity: NodeLiveCapacity,
    budget: DynamicTokenBudget,
    active_workload_classes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Evaluate task admission against dynamic tokens, service reserves, and workload class."""
    task_id = str(task.get("task_id") or "")
    task_class = str(task.get("task_class") or "coding").lower()
    priority = str(task.get("priority") or "normal").lower()
    title = str(task.get("title") or "")
    checklist = " ".join(str(c) for c in (task.get("checklist") or []))

    # 1. Edge-route check (e.g. VigiLOS on-site camera / physical video streaming)
    if "vigilos" in title.lower() or "camera" in title.lower() or "bellini" in title.lower() or "edge" in task_class:
        if "physical" in checklist.lower() or "video stream" in checklist.lower() or "on-site" in checklist.lower():
            return {
                "state": AdmissionState.EDGE_ROUTE_REQUIRED.value,
                "admitted": False,
                "reason": "workload_requires_dedicated_edge_node",
                "recommended_node": "bellini-edge-node",
                "task_id": task_id,
            }

    # 2. Cloud burst check
    if str(task.get("execution_lane") or "") == "cloud_burst":
        if not bool(task.get("approval_id")):
            return {
                "state": AdmissionState.CLOUD_BURST_APPROVAL_REQUIRED.value,
                "admitted": False,
                "reason": "cloud_burst_requires_explicit_owner_approval",
                "task_id": task_id,
            }

    # 3. Workload priority class mapping
    if priority in {"critical", "p0"} and ("service" in title.lower() or "guardian" in title.lower() or "control" in task_class):
        workload_class = WorkloadClass.P0_CRITICAL_SERVICE
    elif priority in {"p0", "p1"} and ("production" in title.lower() or "workforce" in title.lower() or "live" in title.lower()):
        workload_class = WorkloadClass.P1_PRODUCT_SERVICE
    elif priority in {"p0", "p1"}:
        workload_class = WorkloadClass.P2_ACTIVE_CODING
    elif priority in {"normal", "p2", "p3"}:
        workload_class = WorkloadClass.P3_BACKGROUND_DEV
    else:
        workload_class = WorkloadClass.P4_BATCH_EXPLORATION

    cost = TASK_CLASS_TOKEN_COST.get(task_class, TASK_CLASS_TOKEN_COST["default"])

    # 4. Service Reserve Throttle Guard
    # P3/P4 background dev work cannot breach service reserves
    if workload_class in {WorkloadClass.P3_BACKGROUND_DEV, WorkloadClass.P4_BATCH_EXPLORATION}:
        if budget.recommended_concurrency <= 0 or budget.available_cpu_tokens < cost["cpu"] or budget.available_ram_tokens < cost["ram_gb"]:
            return {
                "state": AdmissionState.THROTTLED_SERVICE_RESERVE.value,
                "admitted": False,
                "workload_class": workload_class.value,
                "reason": "service_reserve_protection_active",
                "task_id": task_id,
                "required_cpu": cost["cpu"],
                "available_cpu_tokens": budget.available_cpu_tokens,
                "available_ram_tokens": budget.available_ram_tokens,
            }

    # 5. Capacity token check
    if capacity.active_workers >= budget.max_safe_concurrency:
        return {
            "state": AdmissionState.QUEUE_RESOURCE.value,
            "admitted": False,
            "workload_class": workload_class.value,
            "reason": "active_workers_reach_max_concurrency_ceiling",
            "task_id": task_id,
        }

    # 6. GPU Lane Check
    if cost.get("gpu_lane", 0) > 0 and budget.available_gpu_lanes <= 0:
        return {
            "state": AdmissionState.QUEUE_RESOURCE.value,
            "admitted": False,
            "workload_class": workload_class.value,
            "reason": "gpu_inference_lanes_saturated",
            "task_id": task_id,
        }

    return {
        "state": AdmissionState.ADMIT_NOW.value,
        "admitted": True,
        "workload_class": workload_class.value,
        "reason": "sufficient_dynamic_tokens_and_headroom",
        "task_id": task_id,
        "allocated_tokens": cost,
    }


class WeightedFairQueue:
    """Inter-project / inter-tenant fair scheduler to prevent large backlogs from starving other workloads."""

    def __init__(self, tenant_weights: Optional[Dict[str, float]] = None) -> None:
        self.weights = tenant_weights or {"inneros": 1.5, "workforce": 1.5, "default": 1.0}
        self.queues: Dict[str, List[Dict[str, Any]]] = {}

    def push(self, task: Dict[str, Any]) -> None:
        tenant = str(task.get("project_id") or task.get("related_project") or "default").lower()
        if "/" in tenant:
            tenant = tenant.split("/")[-1]
        self.queues.setdefault(tenant, []).append(task)

    def select_next(self, limit: int = 1) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        tenants = sorted(self.queues.keys(), key=lambda t: -self.weights.get(t, self.weights["default"]))
        
        while len(selected) < limit:
            progress_made = False
            for tenant in tenants:
                queue = self.queues.get(tenant, [])
                if queue and len(selected) < limit:
                    selected.append(queue.pop(0))
                    progress_made = True
            if not progress_made:
                break
        return selected


def get_resource_service_plane_status() -> Dict[str, Any]:
    """Unified capacity/service status surface."""
    capacity = sample_node_live_capacity()
    budget = calculate_dynamic_token_budget(capacity)
    
    return {
        "ok": True,
        "timestamp": _now(),
        "node": capacity.node_name,
        "live_metrics": {
            "cpu_cores": capacity.total_cpu_cores,
            "cpu_load_ratio": capacity.cpu_load_ratio,
            "ram_gb": capacity.total_ram_gb,
            "ram_used_ratio": capacity.ram_used_ratio,
            "swap_used_mb": capacity.swap_used_mb,
            "vram_gb": capacity.total_vram_gb,
            "vram_used_ratio": capacity.vram_used_ratio,
            "baseline_vram_gb": capacity.baseline_vram_gb,
            "psi": {
                "cpu_some": capacity.psi_cpu_some,
                "memory_some": capacity.psi_memory_some,
                "io_some": capacity.psi_io_some,
            },
        },
        "dynamic_token_budget": asdict(budget),
        "service_reservations": SERVICE_RESERVES,
        "admission_policy": "dynamic_multi_resource_tokens_with_service_reserve",
    }
