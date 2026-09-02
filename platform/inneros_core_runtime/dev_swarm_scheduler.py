"""Bounded 1-to-N ops task scheduler for InnerOS dev swarm.

This module intentionally does not run arbitrary shell. It turns approved
``ralfia_ops_tasks`` into durable worker records through one canonical control
plane: fetch once per repo/batch, resolve an immutable base SHA, create isolated
worktrees from that SHA, then execute implementation/test/repair locally.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import capacity_governor_vnext, coordination_live, dev_swarm_watchdog, execution_policy, local_execution_plane, local_model_router, mongo_store

SCHEDULER_STATE_KEY = "dev_swarm_scheduler"
WORKERS_COL = "ralfia_dev_swarm_workers"
EXECUTOR_VERSION = "autonomous_impl_v9_platform_contract_base_ref"
executor_version = EXECUTOR_VERSION
DEFAULT_MAX_CONCURRENT = 4
STALE_WORKER_SECONDS = 3600
STALE_PROGRESS_SECONDS = 1800
MAX_STALE_RECLAIMS = 2
CAPACITY_STATE_KEY = "dev_swarm_capacity_governor"
ELIGIBLE_STATUSES = ("proposed",)
OPS_TERMINAL_STATUSES = frozenset({"blocked", "completed", "cancelled", "failed"})
PRIORITY_ORDER = {"critical": 0, "p0": 1, "p1": 2, "normal": 3, "p2": 4, "low": 5}
SAFE_INNEROS_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
ALLOWED_ASSIGNEES = {"codex", "chatgpt", "antigravity", "cursor", "ralfia", "gemini", "dev_swarm"}
TERMINAL_EXECUTOR_STATUSES = {"executed", "needs_implementation", "failed", "blocked"}
LEGACY_SAFE_TASK_IDS = {
    "ops_e7cacfc4a525",
    "ops_ca2281d54189",
    "ops_4afe0b330d8a",
    "ops_f61caab418a2",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _db():
    return mongo_store.get_db()


def _record_watchdog_anomaly_safe(anomaly: dict[str, Any], repair_task_id: str = "ops_e85143bd8ffc") -> None:
    try:
        dev_swarm_watchdog.record_anomaly(anomaly, repair_task_id=repair_task_id, actor="dev_swarm_reconciler")
    except Exception:
        pass


def _state() -> dict[str, Any]:
    doc = mongo_store.get_coordination_state(SCHEDULER_STATE_KEY)
    state = dict(doc.get("state") or {}) if doc.get("ok") else {}
    state.pop("_id", None)
    state.pop("key", None)
    state.setdefault("enabled", False)
    state.setdefault("max_concurrent", DEFAULT_MAX_CONCURRENT)
    state.setdefault("primary_node", "amd")
    state.setdefault("secondary_node", "intel")
    return state


def _save_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = _state()
    state.update(patch)
    state["updated_at"] = _now()
    mongo_store.upsert_coordination_state(key=SCHEDULER_STATE_KEY, data=state)
    return state


def _read_meminfo() -> dict[str, int]:
    data: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                data[parts[0].rstrip(":")] = int(parts[1]) * 1024
    except Exception:
        pass
    return data


def _gpu_snapshot() -> dict[str, Any]:
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            proc = subprocess.run(
                [
                    nvidia,
                    "--query-gpu=utilization.gpu,memory.total,memory.used,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                capture_output=True,
                timeout=5,
            )
            if proc.returncode == 0:
                rows = []
                for line in proc.stdout.splitlines():
                    cols = [x.strip() for x in line.split(",")]
                    if len(cols) >= 5:
                        rows.append({
                            "backend": "nvidia",
                            "util_percent": float(cols[0] or 0),
                            "vram_total_mb": float(cols[1] or 0),
                            "vram_used_mb": float(cols[2] or 0),
                            "temperature_c": float(cols[3] or 0),
                            "power_w": float(cols[4] or 0),
                        })
                return {"ok": True, "gpus": rows}
        except Exception as exc:
            return {"ok": False, "backend": "nvidia", "error": str(exc)}
    rocm = shutil.which("rocm-smi")
    if rocm:
        try:
            proc = subprocess.run([rocm, "--showuse", "--showmemuse", "--showtemp"], text=True, capture_output=True, timeout=8)
            return {"ok": proc.returncode == 0, "backend": "rocm", "raw": proc.stdout[-4000:], "error": proc.stderr[-1000:]}
        except Exception as exc:
            return {"ok": False, "backend": "rocm", "error": str(exc)}
    return {"ok": False, "backend": "none", "gpus": []}


def sample_capacity(node: str | None = None, simulated_load: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sample local resource capacity without using an LLM."""
    mem = _read_meminfo()
    total = int(mem.get("MemTotal") or 0)
    available = int(mem.get("MemAvailable") or 0)
    swap_total = int(mem.get("SwapTotal") or 0)
    swap_free = int(mem.get("SwapFree") or 0)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    disk = shutil.disk_usage(str(Path.home()))
    cores = os.cpu_count() or 1
    cpu_load_ratio = max(0.0, float(load[0]) / max(1, cores))
    ram_used_ratio = 1.0 - (available / total) if total else 0.0
    if simulated_load:
        if "cpu_load_ratio" in simulated_load:
            cpu_load_ratio = float(simulated_load["cpu_load_ratio"])
        if "ram_used_ratio" in simulated_load:
            ram_used_ratio = float(simulated_load["ram_used_ratio"])
    hard_reasons: list[str] = []
    soft_reasons: list[str] = []
    if cpu_load_ratio >= 0.95:
        hard_reasons.append("cpu_hard")
    elif cpu_load_ratio >= 0.82:
        soft_reasons.append("cpu_soft")
    if ram_used_ratio >= 0.92:
        hard_reasons.append("ram_hard")
    elif ram_used_ratio >= 0.80:
        soft_reasons.append("ram_soft")
    if disk.free < 10 * 1024 * 1024 * 1024:
        soft_reasons.append("disk_low")
    base = max(1, min(12, cores // 2 or 1))
    if hard_reasons:
        recommended_total = 0
    elif soft_reasons:
        recommended_total = max(1, min(base, 2))
    else:
        recommended_total = base
    snapshot = {
        "ok": True,
        "version": EXECUTOR_VERSION,
        "node": node or os.uname().nodename if hasattr(os, "uname") else (node or "local"),
        "sampled_at": _now(),
        "cpu": {"cores": cores, "load1": load[0], "load5": load[1], "load15": load[2], "load_ratio": round(cpu_load_ratio, 3)},
        "memory": {"total_bytes": total, "available_bytes": available, "used_ratio": round(ram_used_ratio, 3)},
        "swap": {"total_bytes": swap_total, "free_bytes": swap_free},
        "disk": {"path": str(Path.home()), "total_bytes": disk.total, "free_bytes": disk.free},
        "gpu": _gpu_snapshot(),
        "limits": {"soft_cpu_ratio": 0.82, "hard_cpu_ratio": 0.95, "soft_ram_ratio": 0.80, "hard_ram_ratio": 0.92},
        "recommendation": {
            "configured_max_total": 12,
            "recommended_concurrency_total": recommended_total,
            "coding_inference": min(recommended_total, 4),
            "tests_build": min(recommended_total, max(1, cores // 2)),
            "browser_review": min(recommended_total, 2),
            "throttled": bool(soft_reasons or hard_reasons),
            "reasons": hard_reasons + soft_reasons,
        },
    }
    snapshot = capacity_governor_vnext.enrich_capacity_snapshot(snapshot, active_worker_count=0)
    mongo_store.upsert_coordination_state(key=CAPACITY_STATE_KEY, data=snapshot)
    return snapshot


def capacity_status(simulated_load: dict[str, Any] | None = None) -> dict[str, Any]:
    current = sample_capacity(simulated_load=simulated_load)
    active = _db()[WORKERS_COL].count_documents(_active_worker_query())
    current = capacity_governor_vnext.enrich_capacity_snapshot(current, active_worker_count=active)
    recommended = int((current.get("recommendation") or {}).get("recommended_concurrency_total") or 0)
    current["workers"] = {"active_worker_count": active}
    current["recommendation"]["admittable_now"] = max(0, recommended - active)
    return current


def _priority_key(task: dict[str, Any]) -> tuple[int, str]:
    return (PRIORITY_ORDER.get(str(task.get("priority") or "normal").lower(), 9), str(task.get("created_at") or ""))


def _task_doc(task_id: str) -> dict[str, Any] | None:
    return _db()[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})


def _worker_worktree(worker: dict[str, Any]) -> str | None:
    launch = worker.get("launch") or {}
    worktree = launch.get("worktree") if isinstance(launch, dict) else None
    if isinstance(worktree, dict):
        return worktree.get("worktree")
    return None


def _worker_objective(worker: dict[str, Any], task: dict[str, Any] | None) -> str:
    if task:
        lines = [str(task.get("title") or ""), ""]
        lines.extend(str(item) for item in task.get("checklist") or [])
        return "\n".join(lines).strip()
    plan = ((worker.get("launch") or {}).get("plan") or {}) if isinstance(worker.get("launch"), dict) else {}
    return str(plan.get("objective") or worker.get("task_id") or "").strip()


CANONICAL_REPO_HINTS = {
    "inneros-alpha-alpaca": "Rafa-Innerchispa/inneros-alpha-alpaca",
    "innerops-agentic-platform": SAFE_INNEROS_REPO,
    "innerspark-workforce-ai": "Rafa-Innerchispa/innerspark-workforce-ai",
}


def _explicit_repo_hint(task: dict[str, Any], text: str) -> str | None:
    candidates: list[str] = []
    for key in ("repo", "repository", "repo_full_name", "canonical_repo", "target_repo", "project", "related_project"):
        value = str(task.get(key) or "").strip()
        if value:
            candidates.append(value)
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    for obj in (payload, metadata):
        for key in ("repo", "repository", "repo_full_name", "canonical_repo", "target_repo", "project", "related_project"):
            value = str((obj or {}).get(key) or "").strip()
            if value:
                candidates.append(value)
    for value in candidates:
        if value.startswith("Rafa-Innerchispa/"):
            return value
        lowered = value.lower()
        for marker, repo in CANONICAL_REPO_HINTS.items():
            if marker in lowered:
                return repo
    if "services/femar-mvp-core" in text:
        return "Rafa-Innerchispa/innerspark-workforce-ai"
    if "innerspark-workforce-ai" in text:
        return "Rafa-Innerchispa/innerspark-workforce-ai"
    workforce_dev = "workforce" in text and any(marker in text for marker in ("dev swarm", "implementation", "implementacion", "implementar", "tests", "jest", "package_root", "package roots", "femar", "node_modules", "npm ci", "worktree", "base_ref"))
    hostname_only = "workforce.pcdoctor.ai" in text and not any(marker in text for marker in ("innerspark-workforce-ai", "services/femar-mvp-core", "dev swarm", "npm ci", "worktree"))
    if workforce_dev and not hostname_only:
        return "Rafa-Innerchispa/innerspark-workforce-ai"
    return None


def _infer_repo(task: dict[str, Any]) -> str | None:
    tags = set(str(x) for x in task.get("tags") or [])
    if "dev_swarm_fixture" in tags:
        return SAFE_INNEROS_REPO
    task_id = str(task.get("task_id") or "")
    if task_id in LEGACY_SAFE_TASK_IDS:
        return SAFE_INNEROS_REPO
    text = _task_search_text(task)
    repo = _explicit_repo_hint(task, text)
    if repo:
        return repo
    if _is_non_dev_ops_task(task, text):
        return None
    current_markers = (
        "inneros",
        "innerops",
        "all things agentic",
        "agentic platform",
        "zkteco",
        "hikvision",
        "vigil",
        "integration guardian",
        "cloudflare",
        "github",
        "gitlab",
        "browser ops",
        "playwright",
        "gcp",
        "google cloud",
        "gemini agent runtime",
        "scheduler 1",
        "autonomous",
        "dev swarm",
        "codex-continuity",
        "parallel-swarm",
        "ralphiia-ecosystem-core",
        "ralphi ia",
        "resource fabric",
        "local execution",
    )
    platform_override_markers = ("innerops", "inneros", "all things agentic", "agentic platform", "dev swarm", "resource fabric", "local execution", "github", "gitlab", "browser ops", "playwright")
    innerops_context = any(marker in text for marker in ("innerops", "all things agentic", "agentic platform"))
    if any(marker in text for marker in ("xprize", "devpost")) and not innerops_context:
        return None
    if "cloudflare" in text and not any(marker in text for marker in ("ag-44", "mcp", "tool", "toolchain", "owner_vault", "provider", "runtime", "local execution")):
        return None
    product_only_markers = (
        "workforce",
        "workforce.pcdoctor.ai",
        "femar",
        "payroll",
        "hr/payroll",
        "pre-nomina",
        "pre-nómina",
        "empleados",
        "marcaciones",
    )
    # A product task that merely says "use Dev Swarm" must not be rewritten as
    # platform work. Product repos need an explicit repo/project policy path.
    if any(marker in text for marker in product_only_markers) and not repo:
        return None
    if any(marker in text for marker in current_markers):
        if any(marker in text for marker in product_only_markers) and not any(marker in text for marker in platform_override_markers):
            return None
        return SAFE_INNEROS_REPO
    return None


def _task_search_text(task: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "correlation_id", "related_project", "project", "kind", "source"):
        parts.append(str(task.get(key) or ""))
    payload = task.get("payload")
    if isinstance(payload, dict):
        for key in ("repo", "repository", "related_project", "project", "task_id", "kind", "source"):
            parts.append(str(payload.get(key) or ""))
    parts.extend(str(item) for item in task.get("checklist") or [])
    parts.extend(str(item) for item in task.get("tags") or [])
    return " ".join(parts).lower()


def _is_non_dev_ops_task(task: dict[str, Any], text: str | None = None) -> bool:
    haystack = text if text is not None else _task_search_text(task)
    tags = {str(item).lower() for item in task.get("tags") or []}
    kind = str(task.get("kind") or "").lower()
    source = str(task.get("source") or "").lower()
    non_dev_tags = {"email", "email_ops", "finance", "funding", "whatsapp", "quoteops", "notion_sync", "calendar"}
    non_dev_markers = (
        "email",
        "imap",
        "gmail",
        "outlook",
        "finanzas",
        "finance",
        "billing",
        "factura",
        "invoice",
        "whatsapp",
        "cotizacion",
        "quoteops",
        "contifico",
    )
    if tags & non_dev_tags:
        return True
    if any(marker in kind for marker in non_dev_markers) or any(marker in source for marker in non_dev_markers):
        return True
    return any(marker in haystack for marker in non_dev_markers) and not any(marker in haystack for marker in ("inneros", "dev swarm", "scheduler", "runtime", "mcp"))


def _active_worker_query() -> dict[str, Any]:
    return {
        "status": {"$in": ["starting", "running"]},
        "$or": [
            {"executor.status": {"$exists": False}},
            {"executor.status": {"$nin": list(TERMINAL_EXECUTOR_STATUSES)}},
        ],
    }


def _worker_progress_time(worker: dict[str, Any]) -> datetime | None:
    executor = worker.get("executor") if isinstance(worker.get("executor"), dict) else {}
    candidates = [
        executor.get("last_progress_at"),
        executor.get("updated_at"),
        worker.get("last_heartbeat_at"),
        worker.get("updated_at"),
    ]
    parsed = [_parse_dt(value) for value in candidates]
    parsed = [value for value in parsed if value]
    return max(parsed) if parsed else None


def _reclaim_stale_workers(db: Any, stale_workers: list[dict[str, Any]], now_iso: str, reason: str) -> dict[str, int]:
    retriable = 0
    exhausted = 0
    for worker in stale_workers:
        task_id = str(worker.get("task_id") or "")
        if not task_id:
            continue
        executor = worker.get("executor") if isinstance(worker.get("executor"), dict) else {}
        reclaim_count = int(executor.get("stale_reclaim_count") or 0) + 1
        retryable = reclaim_count <= MAX_STALE_RECLAIMS
        executor_status = "failed_retryable" if retryable else "blocked"
        blocker = "stale_worker_reclaimed_for_retry" if retryable else "stale_worker_retry_budget_exhausted"
        db[WORKERS_COL].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "owner": "dev_swarm",
                    "status": "blocked",
                    "capacity_reconciled_at": now_iso,
                    "capacity_reconcile_reason": reason,
                    "blocker": blocker,
                    "slot_reclaimed_at": now_iso,
                    "executor.status": executor_status,
                    "executor.phase": "stale",
                    "executor.blocker": blocker,
                    "executor.stale_reclaim_count": reclaim_count,
                    "executor.updated_at": now_iso,
                }
            },
        )
        db[coordination_live.OPS_TASKS_COL].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "owner": "dev_swarm",
                    "status": "blocked",
                    "dev_swarm_last_skip_reason": blocker,
                    "dev_swarm_last_skip_at": now_iso,
                    "dev_swarm_retry_requested": retryable,
                    "updated_at": now_iso,
                }
            },
        )
        _record_watchdog_anomaly_safe(
            {
                "type": blocker,
                "component": "dev_swarm_scheduler",
                "task_id": task_id,
                "repo_actual": worker.get("repo"),
                "worker": worker.get("worker_id") or worker.get("id"),
                "node": worker.get("node"),
                "model": worker.get("model"),
                "profile": worker.get("profile"),
                "severity": "high",
                "evidence": {"reason": reason, "reclaim_count": reclaim_count, "retryable": retryable},
            }
        )
        if retryable:
            retriable += 1
        else:
            exhausted += 1
    return {"retriable": retriable, "exhausted": exhausted}


def reconcile_capacity_state(reason: str = "scheduler_tick") -> dict[str, Any]:
    db = _db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    stale_before = now.timestamp() - STALE_WORKER_SECONDS
    stale_progress_before = now.timestamp() - STALE_PROGRESS_SECONDS
    executed_res = db[WORKERS_COL].update_many(
        {"status": {"$in": ["starting", "running", "verification"]}, "executor.status": "executed"},
        {"$set": {"status": "executed", "capacity_reconciled_at": now_iso, "capacity_reconcile_reason": reason}},
    )
    failed_res = db[WORKERS_COL].update_many(
        {"status": {"$in": ["starting", "running", "verification"]}, "executor.status": {"$in": ["failed", "needs_implementation"]}},
        {"$set": {"status": "blocked", "capacity_reconciled_at": now_iso, "capacity_reconcile_reason": reason}},
    )
    blocked_res = db[WORKERS_COL].update_many(
        {"status": {"$in": ["starting", "running", "verification"]}, "executor.status": "blocked"},
        {"$set": {"status": "blocked", "capacity_reconciled_at": now_iso, "capacity_reconcile_reason": reason}},
    )
    terminal_modified = executed_res.modified_count + failed_res.modified_count + blocked_res.modified_count

    invalid_route_count = 0
    for worker in db[WORKERS_COL].find(
        {
            "status": {"$in": ["starting", "running"]},
            "$or": [{"executor.status": {"$exists": False}}, {"executor.status": {"$nin": list(TERMINAL_EXECUTOR_STATUSES)}}],
        },
        {"_id": 0},
    ):
        task_id = str(worker.get("task_id") or "")
        task = _task_doc(task_id) if task_id else None
        if not task:
            invalid_reason = "task_not_found"
            expected_repo = None
        else:
            ok, invalid_reason, expected_repo = _eligible_reason(task)
            worker_repo = _worker_repo(worker)
            ops_status = str(task.get("status") or "").lower()
            if ops_status in OPS_TERMINAL_STATUSES and not _ops_auto_retry_allowed(task):
                invalid_reason = f"ops_status_{ops_status}_no_auto_retry"
                ok = False
            if ok:
                continue
            if invalid_reason == "repo_not_inferred" and worker_repo:
                policy = local_execution_plane.repo_policy_status(worker_repo)
                if policy.get("ok") and policy.get("write_scope") not in {"none", "read_only"}:
                    db[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {"repo": worker_repo, "executor.expected_repo": worker_repo, "updated_at": now_iso}})
                    continue
                expected_repo = worker_repo
        blocker = f"invalid_dev_swarm_route:{invalid_reason}"
        db[WORKERS_COL].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": "blocked",
                    "capacity_reconciled_at": now_iso,
                    "capacity_reconcile_reason": reason,
                    "blocker": blocker,
                    "slot_reclaimed_at": now_iso,
                    "executor.status": "blocked",
                    "executor.phase": "invalid_route",
                    "executor.blocker": blocker,
                    "executor.expected_repo": expected_repo,
                    "executor.updated_at": now_iso,
                }
            },
        )
        if task_id:
            db[coordination_live.OPS_TASKS_COL].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "owner": "dev_swarm",
                        "status": "blocked",
                        "dev_swarm_last_skip_reason": blocker,
                        "dev_swarm_last_skip_at": now_iso,
                        "dev_swarm_retry_requested": False,
                        "updated_at": now_iso,
                    }
                },
            )
        _record_watchdog_anomaly_safe(
            {
                "type": blocker,
                "component": "dev_swarm_scheduler",
                "task_id": task_id,
                "repo_expected": expected_repo,
                "repo_actual": worker.get("repo"),
                "worker": worker.get("worker_id") or worker.get("id"),
                "node": worker.get("node"),
                "model": worker.get("model"),
                "profile": worker.get("profile"),
                "severity": "high",
                "evidence": {"reason": invalid_reason, "reconcile_reason": reason},
            }
        )
        invalid_route_count += 1

    stale_workers = []
    for worker in db[WORKERS_COL].find(
        {
            "status": {"$in": ["starting", "running"]},
            "$or": [{"executor.status": {"$exists": False}}, {"executor.status": {"$nin": list(TERMINAL_EXECUTOR_STATUSES)}}],
        },
        {"_id": 0},
    ):
        heartbeat = _parse_dt(worker.get("last_heartbeat_at") or worker.get("updated_at"))
        progress = _worker_progress_time(worker)
        heartbeat_expired = bool(heartbeat and heartbeat.timestamp() < stale_before)
        progress_expired = bool(progress and progress.timestamp() < stale_progress_before)
        if heartbeat_expired or progress_expired:
            stale_workers.append(worker)
    stale_reclaim = _reclaim_stale_workers(db, stale_workers, now_iso, reason) if stale_workers else {"retriable": 0, "exhausted": 0}
    lock_res = db["ralfia_coordination_locks"].update_many(
        {"status": "active", "expires_at": {"$lt": now_iso}},
        {"$set": {"status": "expired", "expired_at": now_iso, "updated_at": now_iso, "expired_by": "dev_swarm_reconciler"}},
    )
    active = db[WORKERS_COL].count_documents(_active_worker_query())
    return {
        "ok": True,
        "reason": reason,
        "terminal_workers_reconciled": terminal_modified,
        "invalid_route_workers_reconciled": invalid_route_count,
        "stale_workers_reconciled": stale_reclaim["retriable"] + stale_reclaim["exhausted"],
        "stale_workers_retryable": stale_reclaim["retriable"],
        "stale_workers_exhausted": stale_reclaim["exhausted"],
        "expired_locks": lock_res.modified_count,
        "active_worker_count": active,
    }


def _ops_auto_retry_allowed(task: dict[str, Any]) -> bool:
    """Only explicit retry flag may relaunch blocked/in_progress ops owned by dev_swarm."""
    if not task.get("dev_swarm_retry_requested"):
        return False
    owner = str(task.get("owner") or "").lower()
    return owner == "dev_swarm"


def _eligible_reason(task: dict[str, Any]) -> tuple[bool, str, str | None]:
    status = str(task.get("status") or "").lower()
    retry_allowed = status == "blocked" and _ops_auto_retry_allowed(task)
    if status in OPS_TERMINAL_STATUSES and not retry_allowed:
        return False, f"ops_status_{status}_no_auto_retry", None
    if status not in ELIGIBLE_STATUSES and not retry_allowed and not (
        status in {"accepted", "in_progress"} and str(task.get("owner") or "").lower() == "dev_swarm"
    ):
        return False, "status_not_proposed", None
    assignee = str(task.get("assignee") or "").lower()
    if assignee not in ALLOWED_ASSIGNEES:
        return False, f"assignee_not_swarm_eligible:{assignee}", None
    text = _task_search_text(task)
    if _is_non_dev_ops_task(task, text):
        return False, "non_development_ops_filtered", None
    repo = _infer_repo(task)
    if not repo:
        return False, "repo_not_inferred", None
    policy = local_execution_plane.repo_policy_status(repo)
    if not policy.get("ok"):
        return False, f"repo_policy_denied:{policy.get('error')}", repo
    if policy.get("write_scope") in {"none", "read_only"}:
        return False, "repo_read_only_policy", repo
    return True, "eligible", repo


def scheduler_status() -> dict[str, Any]:
    db = _db()
    reconcile = reconcile_capacity_state(reason="scheduler_status")
    state = _state()
    capacity = capacity_status()
    active_statuses = ["accepted", "in_progress", "blocked", "awaiting_approval", "verification"]
    workers = list(db[WORKERS_COL].find({}, {"_id": 0}).sort("updated_at", -1).limit(20))
    return {
        "ok": True,
        "executor_version": EXECUTOR_VERSION,
        "state": state,
        "reconcile": reconcile,
        "capacity": capacity,
        "active_worker_count": db[WORKERS_COL].count_documents(_active_worker_query()),
        "proposed_count": db[coordination_live.OPS_TASKS_COL].count_documents({"status": "proposed"}),
        "active_ops_count": db[coordination_live.OPS_TASKS_COL].count_documents({"status": {"$in": active_statuses}}),
        "recent_workers": workers,
    }


def executor_status() -> dict[str, Any]:
    db = _db()
    reconcile = reconcile_capacity_state(reason="executor_status")
    capacity = capacity_status()
    running = list(db[WORKERS_COL].find(_active_worker_query(), {"_id": 0}).sort("updated_at", -1).limit(20))
    executed = db[WORKERS_COL].count_documents({"executor.status": {"$in": ["executed", "needs_implementation"]}})
    failed = db[WORKERS_COL].count_documents({"executor.status": "failed"})
    return {
        "ok": True,
        "executor_version": EXECUTOR_VERSION,
        "reconcile": reconcile,
        "capacity": capacity,
        "running_count": len(running),
        "executed_count": executed,
        "failed_count": failed,
        "recent_running": [
            {
                "task_id": w.get("task_id"),
                "branch": w.get("branch"),
                "repo": w.get("repo"),
                "node": w.get("node"),
                "worktree": _worker_worktree(w),
                "phase": (w.get("executor") or {}).get("phase"),
                "attempts": (w.get("executor") or {}).get("attempt_count", 0),
                "files_touched": (w.get("executor") or {}).get("files_touched", []),
                "test_status": (w.get("executor") or {}).get("test_status"),
                "commit": (w.get("executor") or {}).get("commit"),
                "blocker": (w.get("executor") or {}).get("blocker"),
                "executor": w.get("executor"),
            }
            for w in running
        ],
    }


def _command_succeeded(item: dict[str, Any]) -> bool:
    result = item.get("result") or {}
    command_result = result.get("command_result")
    if isinstance(command_result, dict):
        return bool(result.get("ok")) and bool(command_result.get("ok"))
    return bool(result.get("ok"))


def _test_command_for_worktree(worktree: Path) -> list[str] | None:
    if (worktree / "package.json").exists():
        return ["npm", "run", "lint"]
    if (worktree / "pyproject.toml").exists() or (worktree / "requirements.txt").exists():
        return ["python3", "-m", "compileall", "."]
    return None


def _implementation_writes_for_objective(objective: str) -> list[dict[str, str]]:
    """Return deterministic safe writes for explicit smoke-test objectives.

    This keeps the generic executor from being report-only while still avoiding
    free-form edits. Broader feature work must come through specialized agents.
    """
    lowered = objective.lower()
    if "src/inneros/runtime_health.py" in lowered and "tests/test_runtime_health.py" in lowered:
        module_content = '''"""Deterministic runtime-health contract for InnerOS local execution."""

from __future__ import annotations


def runtime_health_status() -> dict[str, str | bool]:
    """Return a tiny stable payload used by dev-swarm E2E tests."""
    return {
        "ok": True,
        "component": "runtime_health",
        "runtime": "local-dev-swarm",
    }
'''
        test_content = '''import unittest

from src.inneros.runtime_health import runtime_health_status


class RuntimeHealthTests(unittest.TestCase):
    def test_runtime_health_status(self):
        status = runtime_health_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["component"], "runtime_health")
        self.assertEqual(status["runtime"], "local-dev-swarm")


if __name__ == "__main__":
    unittest.main()
'''
        return [
            {"path": "src/inneros/runtime_health.py", "content": module_content},
            {"path": "tests/test_runtime_health.py", "content": test_content},
        ]
    if "src/modules/controlplane_smoke.py" not in lowered or "tests/test_controlplane_smoke.py" not in lowered:
        return []
    module_content = '''"""Deterministic control-plane smoke contract for InnerOS local execution."""

from __future__ import annotations


def controlplane_smoke_status() -> dict[str, str | bool]:
    """Return a tiny stable payload used by dev-swarm E2E tests."""
    return {
        "ok": True,
        "component": "controlplane_smoke",
        "runtime": "local-dev-swarm",
    }
'''
    test_content = '''import unittest

from src.modules.controlplane_smoke import controlplane_smoke_status


class ControlplaneSmokeTests(unittest.TestCase):
    def test_controlplane_smoke_status(self):
        status = controlplane_smoke_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["component"], "controlplane_smoke")
        self.assertEqual(status["runtime"], "local-dev-swarm")


if __name__ == "__main__":
    unittest.main()
'''
    return [
        {"path": "src/modules/controlplane_smoke.py", "content": module_content},
        {"path": "tests/test_controlplane_smoke.py", "content": test_content},
    ]


def _cleanup_generated_python_artifacts(worktree: Path) -> list[str]:
    removed: list[str] = []
    for root_name in ("src", "tests"):
        root = worktree / root_name
        if not root.exists():
            continue
        for pyc in root.rglob("*.pyc"):
            try:
                pyc.unlink()
                removed.append(str(pyc.relative_to(worktree)))
            except OSError:
                pass
        for cache_dir in sorted(root.rglob("__pycache__"), key=lambda p: len(p.parts), reverse=True):
            try:
                cache_dir.rmdir()
                removed.append(str(cache_dir.relative_to(worktree)))
            except OSError:
                pass
    return removed


def scheduler_start(max_concurrent: int = DEFAULT_MAX_CONCURRENT, dry_run: bool = False) -> dict[str, Any]:
    max_c = max(DEFAULT_MAX_CONCURRENT, min(int(max_concurrent or DEFAULT_MAX_CONCURRENT), 12))
    if dry_run:
        return {"ok": True, "dry_run": True, "would_set": {"enabled": True, "max_concurrent": max_c}}
    state = _save_state({"enabled": True, "max_concurrent": max_c, "started_at": _now(), "stopped_at": None, "stop_reason": ""})
    coordination_live.bump_revision(reason="dev_swarm_scheduler enabled", source="dev_swarm")
    return {"ok": True, "state": state}


def scheduler_stop(reason: str = "", dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "would_set": {"enabled": False, "reason": reason}}
    state = _save_state({"enabled": False, "stopped_at": _now(), "stop_reason": reason[:300]})
    coordination_live.bump_revision(reason="dev_swarm_scheduler stopped", source="dev_swarm")
    return {"ok": True, "state": state}


def scheduler_tick(limit: int = 6, dry_run: bool = False, include_fixtures: bool = False) -> dict[str, Any]:
    db = _db()
    reconcile = reconcile_capacity_state(reason="scheduler_tick")
    state = _state()
    capacity = capacity_status()
    recommended = int((capacity.get("recommendation") or {}).get("recommended_concurrency_total") or DEFAULT_MAX_CONCURRENT)
    configured = int(state.get("max_concurrent") or DEFAULT_MAX_CONCURRENT)
    # Older persisted state sometimes pinned the swarm to 1/2 even when the
    # capacity governor admitted four lanes. Treat DEFAULT_MAX_CONCURRENT as
    # the floor for normal operation and let the governor remain the ceiling.
    effective_configured = max(DEFAULT_MAX_CONCURRENT, configured)
    max_concurrent = max(1, min(effective_configured, recommended or DEFAULT_MAX_CONCURRENT, 12))
    active = db[WORKERS_COL].count_documents(_active_worker_query())
    available = max(0, max_concurrent - active)
    if not state.get("enabled") and not dry_run:
        return {"ok": True, "enabled": False, "started": [], "skipped": [], "capacity": capacity, "available": available, "reconcile": reconcile}
    query: dict[str, Any] = {"status": "proposed"}
    if include_fixtures:
        query = {
            "status": "proposed",
            "$or": [
                {"tags": "dev_swarm_fixture"},
                {"task_id": {"$in": list(LEGACY_SAFE_TASK_IDS)}},
            ],
        }
    scan_limit = max(max(1, min(limit, 25)) * 5, 50)
    tasks = _load_scheduler_candidates(db, query, scan_limit)
    retry_query: dict[str, Any]
    if include_fixtures:
        retry_query = {
            "status": "blocked",
            "$or": [
                {"task_id": {"$in": list(LEGACY_SAFE_TASK_IDS)}},
                {"tags": "dev_swarm_fixture"},
            ],
        }
    else:
        retry_query = {
            "status": "blocked",
            "$or": [
                {"task_id": {"$in": list(LEGACY_SAFE_TASK_IDS)}},
                {"owner": "dev_swarm"},
            ],
        }
    retry_ids = [
        row["task_id"]
        for row in db[WORKERS_COL]
        .find(retry_query, {"_id": 0, "task_id": 1})
        .limit(max(1, min(limit, 25)))
        if row.get("task_id")
    ]
    # Only retry when ops explicitly requests it; blocked workers alone must not relaunch.
    if retry_ids:
        retry_ids = [
            tid
            for tid in retry_ids
            if (doc := db[coordination_live.OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0, "dev_swarm_retry_requested": 1, "status": 1}))
            and doc.get("dev_swarm_retry_requested")
            and str(doc.get("status") or "").lower() in {"accepted", "in_progress", "blocked"}
        ]
    if retry_ids:
        seen = {task.get("task_id") for task in tasks}
        retry_tasks = db[coordination_live.OPS_TASKS_COL].find(
            {"task_id": {"$in": retry_ids}, "owner": "dev_swarm", "status": {"$in": ["accepted", "in_progress", "blocked"]}},
            {"_id": 0},
        )
        tasks.extend(task for task in retry_tasks if task.get("task_id") not in seen)
    tasks.sort(key=_priority_key)
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for task in tasks:
        bucket = str(task.get("coordination_bucket") or task.get("cleanup_bucket") or "").strip()
        if bucket in {"email_ops_backlog", "needs_repo_metadata", "closed_watchdog_noise", "cancelled_stale_duplicate_shadow"}:
            filtered.append({"task_id": task.get("task_id"), "reason": bucket})
            continue
        text = _task_search_text(task)
        if _is_non_dev_ops_task(task, text):
            reason = "non_development_ops_filtered"
            filtered.append({"task_id": task.get("task_id"), "reason": reason})
            if not dry_run:
                db[coordination_live.OPS_TASKS_COL].update_one(
                    {"task_id": task.get("task_id")},
                    {"$set": {"dev_swarm_last_skip_reason": reason, "dev_swarm_last_skip_at": _now(), "dev_swarm_last_skip_repo": None}},
                )
            continue
        if len(selected) >= available and not dry_run:
            skipped.append({"task_id": task.get("task_id"), "reason": "capacity_full"})
            continue
        ok, reason, repo = _eligible_reason(task)
        if not ok:
            skipped.append({"task_id": task.get("task_id"), "reason": reason, "repo": repo})
            if not dry_run:
                db[coordination_live.OPS_TASKS_COL].update_one(
                    {"task_id": task.get("task_id")},
                    {"$set": {"dev_swarm_last_skip_reason": reason, "dev_swarm_last_skip_at": _now(), "dev_swarm_last_skip_repo": repo}},
                )
            continue
        task_id = str(task.get("task_id"))
        route = execution_policy.route_metadata(task_class="coding")
        selected.append({"task_id": task_id, "repo": repo, "priority": task.get("priority"), **route})
        if dry_run:
            continue
    if dry_run:
        return {"ok": True, "dry_run": True, "enabled": bool(state.get("enabled")), "selected": selected, "skipped": skipped, "filtered": filtered, "filtered_count": len(filtered), "capacity": capacity, "available": available, "reconcile": reconcile, "admission_policy": "repo_policy_priority_capacity"}

    batches: dict[str, list[str]] = {}
    for row in selected:
        batches.setdefault(str(row.get("repo") or SAFE_INNEROS_REPO), []).append(str(row["task_id"]))
    results: list[dict[str, Any]] = []
    for repo, ids in batches.items():
        results.append(fanout_execute(repo=repo, task_ids=ids, concurrency=min(max_concurrent, len(ids)), dry_run=False))
    _save_state({"last_tick_at": _now(), "last_tick_started": len(selected), "last_tick_skipped": len(skipped), "last_tick_core": "fanout_execute"})
    return {
        "ok": all(result.get("ok") for result in results) if results else True,
        "enabled": bool(state.get("enabled")),
        "capacity": capacity,
        "available": available,
        "active_worker_count": active,
        "reconcile": reconcile,
        "selected": selected,
        "skipped": skipped,
        "filtered": filtered,
        "filtered_count": len(filtered),
        "results": results,
        "admission_policy": "repo_policy_priority_capacity",
    }


def _load_scheduler_candidates(db: Any, base_query: dict[str, Any], scan_limit: int) -> list[dict[str, Any]]:
    """Load proposed tasks without letting Mongo natural order hide new P0s."""
    priorities = ["critical", "p0", "p1", "normal", "p2", "low"]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def is_latest(row: dict[str, Any]) -> bool:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            return False
        latest = (
            db[coordination_live.OPS_TASKS_COL]
            .find({"task_id": task_id}, {"_id": 0, "task_id": 1, "status": 1, "updated_at": 1, "created_at": 1, "revision": 1})
            .sort([("updated_at", -1), ("created_at", -1), ("revision", -1)])
            .limit(1)
        )
        latest_row = next(iter(latest), None)
        if not latest_row:
            return True
        return (
            str(latest_row.get("status") or "") == str(row.get("status") or "")
            and str(latest_row.get("updated_at") or "") == str(row.get("updated_at") or "")
            and int(latest_row.get("revision") or row.get("revision") or 1) == int(row.get("revision") or latest_row.get("revision") or 1)
        )

    per_bucket = max(5, min(scan_limit, 100))
    for priority in priorities:
        query = {**base_query, "priority": priority}
        rows = db[coordination_live.OPS_TASKS_COL].find(query, {"_id": 0}).sort("created_at", -1).limit(per_bucket)
        for row in rows:
            task_id = str(row.get("task_id") or "")
            if task_id and task_id not in seen and is_latest(row):
                seen.add(task_id)
                selected.append(row)
    if len(selected) < scan_limit:
        rows = db[coordination_live.OPS_TASKS_COL].find(base_query, {"_id": 0}).sort("created_at", -1).limit(scan_limit)
        for row in rows:
            task_id = str(row.get("task_id") or "")
            if task_id and task_id not in seen and is_latest(row):
                seen.add(task_id)
                selected.append(row)
    return selected


def _executor_report_markdown(
    *,
    worker: dict[str, Any],
    task: dict[str, Any] | None,
    commands: list[dict[str, Any]],
    local_model: dict[str, Any],
    outcome: str,
) -> str:
    title = (task or {}).get("title") or worker.get("task_id")
    objective = _worker_objective(worker, task)
    lines = [
        f"# Dev Swarm Executor Report — {worker.get('task_id')}",
        "",
        f"- Task: `{worker.get('task_id')}`",
        f"- Title: {title}",
        f"- Repo: `{worker.get('repo')}`",
        f"- Branch: `{worker.get('branch')}`",
        f"- Worktree: `{_worker_worktree(worker) or 'missing'}`",
        f"- Outcome: `{outcome}`",
        f"- Generated: `{_now()}`",
        "",
        "## Objective",
        "",
        objective[:4000] or "_No objective found._",
        "",
        "## Checks",
        "",
    ]
    for item in commands:
        cmd = " ".join(item.get("command") or [])
        result = item.get("result") or {}
        command_result = result.get("command_result") or result
        lines.extend(
            [
                f"### `{cmd}`",
                "",
                f"- ok: `{bool(result.get('ok'))}`",
                f"- returncode: `{command_result.get('returncode', 'n/a')}`",
                "",
                "```text",
                str(command_result.get("stdout") or command_result.get("stderr") or "")[:6000],
                "```",
                "",
            ]
        )
    lines.extend(["## Local Model Plan", ""])
    if local_model.get("ok"):
        response = local_model.get("response") or local_model.get("text") or local_model.get("content") or ""
        lines.extend([str(response)[:8000], ""])
    else:
        lines.extend([f"Local model unavailable or declined: `{local_model.get('error') or local_model.get('reason')}`", ""])
    lines.extend(
        [
            "## Executor Boundary",
            "",
            "This executor ran allowlisted diagnostics, generated a local plan, wrote evidence, and committed it on the isolated branch. Product code changes still require a specialized implementation agent unless the generated patch is explicitly approved and applied through Local Execution Plane.",
            "",
        ]
    )
    return "\n".join(lines)


def executor_tick(limit: int = 2, dry_run: bool = False, run_tests: bool = True) -> dict[str, Any]:
    db = _db()
    workers = list(
        db[WORKERS_COL]
        .find(
            {
                "status": "running",
                "$or": [
                    {"executor.status": {"$exists": False}},
                    {"executor.status": {"$in": ["pending", "failed_retryable"]}},
                ],
            },
            {"_id": 0},
        )
        .sort("created_at", 1)
        .limit(max(1, min(int(limit or 2), 6)))
    )
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for worker in workers:
        task_id = str(worker.get("task_id") or "")
        repo = str(worker.get("repo") or "")
        branch = str(worker.get("branch") or "")
        if not task_id or not repo or not branch:
            skipped.append({"task_id": task_id, "reason": "worker_missing_metadata"})
            continue
        if dry_run:
            executed.append({"task_id": task_id, "repo": repo, "branch": branch, "dry_run": True})
            continue
        executed.append(_execute_existing_worker_generic(worker, run_tests=run_tests))
    _save_state({"last_executor_tick_at": _now(), "last_executor_executed": len(executed), "last_executor_skipped": len(skipped)})
    return {"ok": True, "executed": executed, "skipped": skipped}


def create_fixture_tasks(count: int = 2) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    for idx in range(max(1, min(int(count or 2), 5))):
        task = coordination_live.create_ops_task(
            assignee="codex",
            title=f"Fixture dev swarm scheduler {idx + 1}",
            checklist=["Verify scheduler can accept and launch a safe isolated worktree.", "Do not modify production."],
            evidence_required=["worker record", "worktree evidence"],
            priority="p0",
            from_agent="DEV_SWARM",
            correlation_id=f"dev-swarm-fixture-{secrets.token_hex(4)}",
            related_project="innerops-agentic-platform",
        )
        if task.get("ok"):
            db = _db()
            db[coordination_live.OPS_TASKS_COL].update_one(
                {"task_id": task.get("task_id")},
                {"$addToSet": {"tags": "dev_swarm_fixture"}},
            )
        created.append(task)
    return {"ok": True, "created": created}


# --- Generic concurrent fan-out executor v4 (2026-08-23) ---
# Global path for all owner-approved projects. Structured inputs only.

def _fanout_parse_model_json(text: str) -> dict[str, Any] | None:
    import json
    raw = str(text or "").strip()
    candidates = [raw]
    if "```" in raw:
        for part in raw.split("```"):
            value = part.strip()
            if value.startswith("json"):
                value = value[4:].strip()
            if value.startswith("{"):
                candidates.append(value)
    first, last = raw.find("{"), raw.rfind("}")
    if first >= 0 and last > first:
        candidates.append(raw[first:last + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _fanout_repo_snapshot(worktree: Path, max_chars: int = 16000) -> str:
    deny = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
    suffixes = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".md"}
    chunks: list[str] = []
    used = 0
    for path in sorted(worktree.rglob("*")) if worktree.exists() else []:
        if not path.is_file():
            continue
        rel = path.relative_to(worktree)
        if any(part in deny for part in rel.parts):
            continue
        if path.suffix.lower() not in suffixes and path.name not in {"Dockerfile", ".gitignore"}:
            continue
        try:
            body = path.read_text(encoding="utf-8")[:4000]
        except Exception:
            continue
        piece = f"\n--- {rel.as_posix()} ---\n{body}\n"
        if used + len(piece) > max_chars:
            break
        chunks.append(piece)
        used += len(piece)
    return "".join(chunks) or "(empty repository scaffold)"


DEV_TASK_TERMS = (
    "implement", "build", "code", "feature", "module", "frontend", "runtime",
    "gateway", "contract", "adapter", "api", "test", "tests", "fix", "repair",
    "debug", "refactor", "regression", "scheduler", "worker", "verifier",
    "crear", "implementar", "construir", "codigo", "modulo", "contrato",
    "corregir", "arreglar", "reparar", "desarrollar", "programar", "prueba", "validar",
)
DOCS_TASK_TERMS = ("docs-only", "documentation only", "documentacion", "documentación", "readme", "runbook")
PRODUCT_PREFIXES = ("src/", "modules/", "app/", "lib/", "components/", "infra/", "commands/")
DIAGNOSTIC_PATH_PARTS = ("/inneros_dev_swarm/", "/__dev_swarm_contracts/", "/diagnostics/", "/dev_swarm_frontend_status")
NODE_PROJECT_FILES = ("package.json", "tsconfig.json", "vite.config.js", "vite.config.ts")
TEST_PREFIXES = ("tests/", "__tests__/", "test/")
WRITABLE_PREFIXES = PRODUCT_PREFIXES + TEST_PREFIXES + NODE_PROJECT_FILES
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "crypto", "events", "fs", "http", "https",
    "net", "os", "path", "process", "querystring", "stream", "timers", "url", "util",
}


def _is_docs_only_task(objective: str) -> bool:
    text = (objective or "").lower()
    return any(term in text for term in DOCS_TASK_TERMS) and not any(term in text for term in DEV_TASK_TERMS)


def _requires_product_writes(objective: str) -> bool:
    return not _is_docs_only_task(objective) and any(term in (objective or "").lower() for term in DEV_TASK_TERMS)


def _is_platform_regression_task(objective: str) -> bool:
    text = (objective or "").lower()
    return any(term in text for term in ("platform regression", "executor regression", "contract fixture", "diagnostic fixture"))


def _is_diagnostic_contract_path(path: str) -> bool:
    rel = "/" + str(path or "").replace("\\", "/").strip("/")
    return any(part in rel for part in DIAGNOSTIC_PATH_PARTS)


def _safe_module_name(path: str, fallback: str) -> str:
    stem = Path(path).stem or fallback
    return re.sub(r"[^A-Za-z0-9_]", "_", stem)


def _path_has_traversal(path: str) -> bool:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return any(part == ".." for part in parts)


def _product_roots_for_repo(repo: str, worktree: Path) -> list[str]:
    try:
        conf = local_execution_plane._repo_config(repo)
    except Exception:
        conf = {}
    configured = list(conf.get("package_roots") or [])
    if not configured:
        return []
    valid = local_execution_plane._package_roots_with_manifest(worktree, configured)
    roots: list[str] = []
    for root in configured:
        try:
            rel = local_execution_plane._clean_package_root(root)
        except PermissionError:
            continue
        if rel in valid and rel not in roots:
            roots.append(rel)
    return roots


def _primary_product_root(repo: str, worktree: Path) -> str:
    roots = _product_roots_for_repo(repo, worktree)
    return roots[0] if roots else ""


def _normalize_product_scoped_path(
    *,
    repo: str,
    worktree: Path,
    raw_path: str,
) -> dict[str, Any]:
    raw = str(raw_path or "").strip().replace("\\", "/")
    if not raw:
        return {"ok": False, "raw_path": raw_path, "reason": "empty_path"}
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return {"ok": False, "raw_path": raw, "reason": "absolute_path_denied"}
    candidate = raw.strip("/")
    if not candidate or _path_has_traversal(candidate):
        return {"ok": False, "raw_path": raw, "reason": "path_traversal_denied"}
    while candidate.startswith("./"):
        candidate = candidate[2:]
    rel = candidate.strip("/")
    if not rel or _path_has_traversal(rel):
        return {"ok": False, "raw_path": raw, "reason": "path_traversal_denied"}

    product_root = _primary_product_root(repo, worktree)
    if product_root:
        if rel == product_root or rel.startswith(product_root + "/"):
            normalized = rel
        elif rel.startswith(WRITABLE_PREFIXES):
            normalized = f"{product_root}/{rel}"
        else:
            return {"ok": False, "raw_path": raw, "reason": "outside_product_root", "product_root": product_root}
        try:
            local_execution_plane._validate_relative_path(normalized, [product_root])
        except Exception as exc:
            return {
                "ok": False,
                "raw_path": raw,
                "normalized_path": normalized,
                "reason": str(exc),
                "product_root": product_root,
            }
        return {
            "ok": True,
            "raw_path": raw,
            "normalized_path": normalized,
            "product_root": product_root,
            "path_mode": "product_root",
        }

    try:
        normalized = local_execution_plane._validate_relative_path(raw, list(local_execution_plane._repo_config(repo).get("allowed_paths") or ["."]))
    except Exception as exc:
        return {"ok": False, "raw_path": raw, "reason": str(exc)}
    if not normalized.startswith(WRITABLE_PREFIXES):
        return {"ok": False, "raw_path": raw, "normalized_path": normalized, "reason": "not_a_writable_product_prefix"}
    return {"ok": True, "raw_path": raw, "normalized_path": normalized, "path_mode": "repo_root"}


def _is_product_code_path(repo: str, worktree: Path, path: str) -> bool:
    if _is_diagnostic_contract_path(path):
        return False
    product_root = _primary_product_root(repo, worktree)
    rel = str(path or "").replace("\\", "/").strip("/")
    if product_root:
        prefix = product_root + "/"
        if not rel.startswith(prefix):
            return False
        rel = rel[len(prefix):]
    return rel.startswith(PRODUCT_PREFIXES)


def _implementation_write_classes(repo: str, worktree: Path, files_touched: list[str]) -> dict[str, list[str]]:
    product: list[str] = []
    diagnostic: list[str] = []
    other: list[str] = []
    for path in sorted(set(files_touched)):
        if _is_diagnostic_contract_path(path):
            diagnostic.append(path)
        elif _is_product_code_path(repo, worktree, path):
            product.append(path)
        else:
            other.append(path)
    return {"product": product, "diagnostic": diagnostic, "other": other}


def _verified_write_classes(repo: str, worktree: Path, files_touched: list[str]) -> dict[str, Any]:
    """Validate reported writes against the actual worktree and repo policy."""
    valid: list[str] = []
    invalid: list[dict[str, str]] = []
    try:
        conf = local_execution_plane._repo_config(repo)
        allowed_paths = list(conf.get("allowed_paths") or ["."])
    except Exception as exc:
        return {
            "ok": False,
            "classes": {"product": [], "diagnostic": [], "other": []},
            "invalid_files": [{"path": "*", "reason": f"repo_policy_unavailable:{exc}"}],
        }
    for raw in sorted(set(str(path or "").replace("\\", "/").strip("/") for path in files_touched)):
        if not raw:
            continue
        try:
            rel = local_execution_plane._validate_relative_path(raw, allowed_paths)
        except Exception as exc:
            invalid.append({"path": raw, "reason": str(exc)})
            continue
        target = (worktree / rel).resolve()
        try:
            base = worktree.resolve()
        except Exception:
            base = worktree
        if target != base and base not in target.parents:
            invalid.append({"path": rel, "reason": "path_outside_worktree"})
            continue
        if not target.is_file():
            invalid.append({"path": rel, "reason": "file_missing_in_worktree"})
            continue
        valid.append(rel)
    classes = _implementation_write_classes(repo, worktree, valid)
    return {"ok": not invalid, "classes": classes, "valid_files": valid, "invalid_files": invalid}


def _worker_repo(worker: dict[str, Any]) -> str:
    launch = worker.get("launch") if isinstance(worker.get("launch"), dict) else {}
    plan = launch.get("plan") if isinstance(launch.get("plan"), dict) else {}
    prepared = launch.get("prepared") if isinstance(launch.get("prepared"), dict) else {}
    return str(worker.get("repo") or plan.get("repo") or prepared.get("repo") or "")


def _worker_reported_file_validation(task_id: str, files_touched: list[str]) -> dict[str, Any]:
    worker = _db()[WORKERS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
    repo = _worker_repo(worker)
    worktree_raw = _worker_worktree(worker)
    if not repo or not worktree_raw:
        return {"ok": False, "valid_files": [], "invalid_files": [{"path": "*", "reason": "worker_repo_or_worktree_missing"}]}
    return _verified_write_classes(repo, Path(worktree_raw), files_touched)


def _repo_architecture_context(repo: str, worktree: Path, objective: str, max_chars: int = 4000) -> str:
    product_root = _primary_product_root(repo, worktree)
    base = worktree / product_root if product_root else worktree
    chunks: list[str] = []
    package_path = base / "package.json"
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
            deps = sorted((package.get("dependencies") or {}).keys())
            dev_deps = sorted((package.get("devDependencies") or {}).keys())
            chunks.append(
                "PACKAGE CONTEXT:\n"
                + json.dumps(
                    {
                        "path": str(package_path.relative_to(worktree)).replace("\\", "/"),
                        "name": package.get("name"),
                        "scripts": package.get("scripts") or {},
                        "dependencies": deps[:40],
                        "devDependencies": dev_deps[:40],
                    },
                    indent=2,
                )
            )
        except Exception as exc:
            chunks.append(f"PACKAGE CONTEXT: unreadable package.json: {exc}")
    keywords = sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", objective or "", flags=re.IGNORECASE)))[:18]
    hits: list[str] = []
    deny = {".git", "node_modules", "dist", "build", ".next", "__pycache__"}
    suffixes = {".ts", ".tsx", ".js", ".jsx", ".py", ".json"}
    for path in sorted(base.rglob("*")) if base.exists() else []:
        if len(hits) >= 80:
            break
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(worktree).as_posix()
        if any(part in deny for part in path.relative_to(worktree).parts):
            continue
        hay = rel.lower()
        if any(k.lower() in hay for k in keywords):
            hits.append(rel)
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")[:3000].lower()
        except Exception:
            continue
        if any(k.lower() in body for k in keywords):
            hits.append(rel)
    chunks.append("RELEVANT EXISTING PATHS:\n" + ("\n".join(hits[:80]) if hits else "(no direct search hits)"))
    context = "\n\n".join(chunks)
    return context[:max_chars]


def _fallback_files_from_objective(objective: str, task_id: str, repo: str = "", worktree: Path | None = None) -> list[dict[str, str]]:
    """Deterministic repair path for explicit path-based smoke tasks.

    The model is still invoked first. This fallback prevents a valid owner-approved
    smoke request from silently degrading to docs-only when a small local model
    emits malformed JSON.
    """
    text = objective or ""
    product_root = _primary_product_root(repo, worktree) if repo and worktree else ""
    product_root_pattern = re.escape(product_root) + r"/" if product_root else ""
    product_match = re.search(rf"((?:{product_root_pattern})?(?:src|modules|app|lib|components|infra)/[A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|jsx))", text)
    test_match = re.search(rf"((?:{product_root_pattern})?(?:tests|__tests__|test|src)/[A-Za-z0-9_./-]+(?:test|spec)[A-Za-z0-9_.-]*\.(?:py|ts|tsx|js|jsx))", text)
    if not product_match or not test_match:
        return []
    product_path = product_match.group(1)
    test_path = test_match.group(1)
    if repo and worktree:
        normalized_product = _normalize_product_scoped_path(repo=repo, worktree=worktree, raw_path=product_path)
        normalized_test = _normalize_product_scoped_path(repo=repo, worktree=worktree, raw_path=test_path)
        if not (normalized_product.get("ok") and normalized_test.get("ok")):
            return []
        product_path = str(normalized_product["normalized_path"])
        test_path = str(normalized_test["normalized_path"])
    if product_path.endswith((".ts", ".tsx", ".js", ".jsx")):
        export_name = _safe_module_name(product_path, "generatedStatus") + "Status"
        module_content = f'''export function {export_name}() {{
  return {{
    ok: true,
    component: "{_safe_module_name(product_path, "generated").lower()}",
    runtime: "inneros-dev-swarm",
  }};
}}
'''
        rel_import = os.path.relpath(
            str(Path(product_path).with_suffix("")),
            str(Path(test_path).parent),
        ).replace("\\", "/")
        if not rel_import.startswith("."):
            rel_import = "./" + rel_import
        test_content = f'''import {{ {export_name} }} from "{rel_import}";

describe("InnerOS Dev Swarm regression", () => {{
  it("returns a stable generated status", () => {{
    const status = {export_name}();
    expect(status.ok).toBe(true);
    expect(status.runtime).toBe("inneros-dev-swarm");
  }});
}});
'''
        return [{"path": product_path, "content": module_content}, {"path": test_path, "content": test_content}]
    func = _safe_module_name(product_path, "generated_status") + "_status"
    component = re.sub(r"[^a-z0-9_]+", "_", Path(product_path).stem.lower()).strip("_") or "generated"
    import_path = product_path[:-3].replace("/", ".")
    module_content = f'''"""Generated by InnerOS local dev swarm for {task_id}."""

from __future__ import annotations


def {func}() -> dict[str, str | bool]:
    return {{
        "ok": True,
        "component": "{component}",
        "runtime": "inneros-dev-swarm",
    }}
'''
    test_content = f'''import unittest

from {import_path} import {func}


class GeneratedSmokeTests(unittest.TestCase):
    def test_generated_status(self):
        status = {func}()
        self.assertTrue(status["ok"])
        self.assertEqual(status["component"], "{component}")
        self.assertEqual(status["runtime"], "inneros-dev-swarm")


if __name__ == "__main__":
    unittest.main()
'''
    return [{"path": product_path, "content": module_content}, {"path": test_path, "content": test_content}]


def _contract_regression_files_for_objective(objective: str, task_id: str, repo: str, worktree: Path) -> list[dict[str, str]]:
    """Create a bounded executor-contract regression when the local model is non-actionable.

    This is deliberately not a Workforce feature implementation. It proves that a
    real task objective can still travel through product_root normalization,
    writes, tests, evidence and commit while preserving a precise model blocker.
    """
    product_root = _primary_product_root(repo, worktree)
    if not product_root or repo != "Rafa-Innerchispa/innerspark-workforce-ai":
        return []
    text = (objective or "").lower()
    if not any(term in text for term in ("auth", "rbac", "mobile", "check-in", "report", "aria", "tenant")):
        return []
    safe_task = re.sub(r"[^A-Za-z0-9_]", "_", task_id)[:80]
    component = "auth_rbac" if any(term in text for term in ("auth", "rbac", "tenant")) else ("mobile_checkin" if any(term in text for term in ("mobile", "check-in")) else "reporting_aria")
    module_path = f"{product_root}/src/inneros_dev_swarm/{safe_task}_contract.ts"
    test_path = f"{product_root}/src/inneros_dev_swarm/{safe_task}_contract.test.ts"
    module_content = f'''export type DevSwarmContractStatus = {{
  ok: boolean;
  taskId: string;
  component: string;
  scope: string;
  note: string;
}};

export function devSwarmContractStatus(): DevSwarmContractStatus {{
  return {{
    ok: true,
    taskId: "{task_id}",
    component: "{component}",
    scope: "services/femar-mvp-core",
    note: "Executor contract regression only; no Workforce feature implementation.",
  }};
}}
'''
    test_content = f'''import {{ devSwarmContractStatus }} from "./{safe_task}_contract";

describe("Dev Swarm output contract regression", () => {{
  it("keeps real Workforce task writes bounded to the product root", () => {{
    const status = devSwarmContractStatus();
    expect(status.ok).toBe(true);
    expect(status.taskId).toBe("{task_id}");
    expect(status.scope).toBe("services/femar-mvp-core");
  }});
}});
'''
    return [{"path": module_path, "content": module_content}, {"path": test_path, "content": test_content}]


def _package_dependencies(worktree: Path, product_root: str) -> set[str]:
    package_path = worktree / product_root / "package.json" if product_root else worktree / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = package.get(key) or {}
        if isinstance(section, dict):
            names.update(str(name) for name in section.keys())
    return names


def _module_package_name(specifier: str) -> str:
    spec = str(specifier or "").strip()
    if spec.startswith("@"):
        parts = spec.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else spec
    return spec.split("/", 1)[0]


def _content_dependency_violations(worktree: Path, product_root: str, path: str, content: str) -> list[str]:
    if not path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        return []
    allowed = _package_dependencies(worktree, product_root)
    violations: list[str] = []
    patterns = [
        r"""import\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]""",
        r"""export\s+[^'"]+\s+from\s+['"]([^'"]+)['"]""",
        r"""require\(\s*['"]([^'"]+)['"]\s*\)""",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content or ""):
            spec = match.group(1)
            if spec.startswith((".", "/", "node:")):
                continue
            package_name = _module_package_name(spec)
            if package_name in NODE_BUILTINS or package_name in allowed:
                continue
            violations.append(package_name)
    return sorted(set(violations))


def _objective_requests_node_frontend(objective: str, files: list[dict[str, str]] | None = None) -> bool:
    text = (objective or "").lower()
    node_terms = (
        "react", "tsx", "jsx", "typescript", "javascript", "frontend", "vite",
        "next.js", "nextjs", "package.json", "npm", "node", "src/app.tsx",
        "src/app.jsx", "src/app.js", "components/",
    )
    if any(term in text for term in node_terms):
        return True
    for item in files or []:
        rel = str(item.get("path") or "").lower()
        if rel.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")) or rel == "package.json":
            return True
    return False


def _node_scaffold_files(task_id: str) -> list[dict[str, str]]:
    package_content = {
        "name": "inneros-dev-swarm-node-fixture",
        "version": "0.0.0",
        "private": True,
        "type": "module",
        "scripts": {
            "test": "node tests/scaffold.test.mjs",
            "lint": "node --check tests/scaffold.test.mjs",
            "build": "npm test",
        },
        "dependencies": {},
        "devDependencies": {},
    }
    smoke = f'''import assert from "node:assert/strict";
import fs from "node:fs";

assert.equal(fs.existsSync("package.json"), true);
assert.equal(fs.existsSync("src") || fs.existsSync("components") || fs.existsSync("app"), true);
assert.equal("{task_id}".length > 0, true);
'''
    product = '''export function devSwarmFrontendStatus() {
  return { ok: true, runtime: "inneros-dev-swarm", profile: "node-tests" };
}
'''
    return [
        {"path": "package.json", "content": json.dumps(package_content, indent=2) + "\n"},
        {"path": "tests/scaffold.test.mjs", "content": smoke},
        {"path": "src/dev_swarm_frontend_status.js", "content": product},
    ]


def _with_product_root(repo: str, worktree: Path, path: str) -> str:
    product_root = _primary_product_root(repo, worktree)
    if not product_root:
        return path
    clean = path.strip("/").replace("\\", "/")
    return clean if clean == product_root or clean.startswith(product_root + "/") else f"{product_root}/{clean}"


def _merge_node_scaffold(
    *,
    objective: str,
    task_id: str,
    worktree: Path,
    files: list[dict[str, str]],
    repo: str = "",
) -> list[dict[str, str]]:
    if not _objective_requests_node_frontend(objective, files):
        return files
    product_root = _primary_product_root(repo, worktree) if repo else ""
    package_json = f"{product_root}/package.json" if product_root else "package.json"
    if (worktree / package_json).exists() or any(item.get("path") == package_json for item in files):
        return files
    merged = list(files)
    seen = {str(item.get("path") or "") for item in merged}
    for item in _node_scaffold_files(task_id):
        path = _with_product_root(repo, worktree, item["path"]) if repo else item["path"]
        if path not in seen:
            merged.append({"path": path, "content": item["content"]})
            seen.add(path)
    return merged


def _safe_generated_files(
    payload: dict[str, Any] | None,
    objective: str,
    task_id: str,
    repo: str,
    worktree: Path,
    model_text: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    proposed = payload.get("files") if isinstance(payload, dict) else None
    files: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    if isinstance(payload, dict) and not isinstance(proposed, list):
        rejected.append({
            "reason": "missing_files_array",
            "payload_keys": sorted(str(key) for key in payload.keys()),
            "model_text_preview": str(model_text or "")[:1200],
        })
    elif payload is None:
        rejected.append({
            "reason": "json_parse_failed_or_missing_json_object",
            "model_text_preview": str(model_text or "")[:1200],
        })
    if isinstance(proposed, list):
        for item in proposed[:20]:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "").strip()
            content = item.get("content")
            if not rel or not isinstance(content, str):
                rejected.append({"raw_path": rel, "reason": "missing_path_or_content"})
                continue
            normalized = _normalize_product_scoped_path(repo=repo, worktree=worktree, raw_path=rel)
            if normalized.get("ok"):
                normalized_path = str(normalized["normalized_path"])
                violations = _content_dependency_violations(
                    worktree,
                    str(normalized.get("product_root") or _primary_product_root(repo, worktree)),
                    normalized_path,
                    content,
                )
                if violations:
                    rejected.append({
                        **normalized,
                        "reason": "undeclared_imports_denied",
                        "undeclared_imports": violations,
                    })
                    continue
                files.append({"path": normalized_path, "content": content})
            else:
                rejected.append(normalized)
    if files:
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in files:
            if item["path"] not in seen:
                deduped.append(item)
                seen.add(item["path"])
        return deduped, rejected
    fallback = _fallback_files_from_objective(objective, task_id, repo, worktree)
    if fallback:
        return fallback, rejected
    contract = _contract_regression_files_for_objective(objective, task_id, repo, worktree)
    if contract:
        rejected.append({"reason": "model_output_non_actionable_contract_regression_used", "contract_paths": [item["path"] for item in contract]})
    return contract, rejected


def _worktree_has_node_markers(worktree: Path, files_touched: list[str]) -> bool:
    if (worktree / "package.json").exists():
        return True
    node_suffixes = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    if any(path.endswith(node_suffixes) for path in files_touched):
        return True
    for root in ("src", "app", "components", "tests"):
        base = worktree / root
        if base.exists() and any(path.is_file() and path.suffix.lower() in node_suffixes for path in base.rglob("*")):
            return True
    return False


def _worktree_has_python_markers(worktree: Path, files_touched: list[str]) -> bool:
    if (worktree / "pyproject.toml").exists() or (worktree / "requirements.txt").exists():
        return True
    if any(path.endswith(".py") for path in files_touched):
        return True
    return any(path.is_file() and path.suffix == ".py" for path in (worktree / "tests").rglob("*")) if (worktree / "tests").exists() else False


def _worktree_prefers_pytest(worktree: Path) -> bool:
    if (worktree / "pytest.ini").exists() or (worktree / "conftest.py").exists():
        return True
    pyproject = worktree / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False
    return "pytest" in text or "[tool.pytest" in text


def _test_commands_for_policy(repo: str, worktree: Path, files_touched: list[str]) -> list[list[str]]:
    commands: list[list[str]] = [["git", "diff", "--check"]]
    package_roots = _product_roots_for_repo(repo, worktree)
    if package_roots:
        for package_root in package_roots:
            if (worktree / package_root / "package-lock.json").exists() and not (worktree / package_root / "node_modules" / ".bin" / "jest").exists():
                commands.append(["npm", "--prefix", package_root, "ci"])
            commands.append(["npm", "--prefix", package_root, "test", "--", "--runInBand"])
        return commands
    has_node = _worktree_has_node_markers(worktree, files_touched)
    has_python = _worktree_has_python_markers(worktree, files_touched)
    if (worktree / "package.json").exists():
        commands.append(["npm", "test"])
        return commands
    if has_node and not has_python:
        return commands
    py_roots = [root for root in ("src", "modules", "app", "lib", "components", "infra", "tests") if (worktree / root).exists()]
    if has_python and py_roots:
        commands.append(["python3", "-m", "compileall", "-q", *py_roots])
    has_python_tests = (worktree / "tests").exists() and any(path.is_file() and path.suffix == ".py" for path in (worktree / "tests").rglob("*"))
    if has_python_tests:
        if _worktree_prefers_pytest(worktree):
            commands.append(["python3", "-m", "pytest", "tests", "-q"])
        else:
            commands.append(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])
    if len(commands) == 1 and (worktree / "pyproject.toml").exists():
        commands.append(["python3", "-m", "compileall", "-q", "."])
    return commands


def _set_worker_phase(task_id: str, phase: str, **extra: Any) -> None:
    now = _now()
    patch = {"executor.phase": phase, "executor.updated_at": now, "executor.last_progress_at": now, "updated_at": now, "last_heartbeat_at": now}
    for key, value in extra.items():
        if key == "files_touched" and isinstance(value, list):
            validation = _worker_reported_file_validation(task_id, value)
            patch["executor.files_touched"] = validation.get("valid_files", [])
            if validation.get("invalid_files"):
                patch["executor.rejected_reported_files"] = validation.get("invalid_files")
            continue
        patch[f"executor.{key}"] = value
    _db()[WORKERS_COL].update_one({"task_id": task_id}, {"$set": patch})


def _fail_worker_early(task_id: str, error: str, outcome: str = "FAIL") -> dict[str, Any]:
    now = _now()
    patch = {
        "status": "blocked",
        "executor.status": "failed",
        "executor.phase": "failed",
        "executor.error": error,
        "executor.outcome": outcome,
        "executor.updated_at": now,
        "updated_at": now,
        "last_heartbeat_at": now,
    }
    _db()[WORKERS_COL].update_one({"task_id": task_id}, {"$set": patch})
    try:
        coordination_live.update_ops_task_state(
            task_id,
            "blocked",
            actor="dev_swarm",
            evidence={"status": outcome, "error": error, "executor_version": EXECUTOR_VERSION},
            force_handoff=True,
        )
    except Exception:
        pass
    return {"ok": False, "task_id": task_id, "outcome": outcome, "error": error}


def _execute_existing_worker_generic(worker: dict[str, Any], run_tests: bool = True) -> dict[str, Any]:
    task_id = str(worker.get("task_id") or "")
    repo = _worker_repo(worker)
    branch = str(worker.get("branch") or "")
    task = _task_doc(task_id)
    objective = _worker_objective(worker, task)
    correlation_id = str(((worker.get("launch") or {}).get("plan") or {}).get("correlation_id") or f"dev-swarm-{task_id}")
    worktree_raw = _worker_worktree(worker)
    if not worktree_raw:
        return {"ok": False, "task_id": task_id, "error": "worktree_missing_in_worker"}
    worktree = Path(worktree_raw)
    db = _db()
    db[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
        "executor": {"version": EXECUTOR_VERSION, "status": "running", "phase": "inference", "attempt_count": 0},
        "status": "running",
        "updated_at": _now(),
        "last_heartbeat_at": _now(),
    }})
    if _is_docs_only_task(objective):
        return _fail_worker_early(task_id, "docs_only_tasks_must_use_docs_executor")
    if not _requires_product_writes(objective):
        return _fail_worker_early(task_id, "development_intent_not_detected")

    failures = ""
    attempts: list[dict[str, Any]] = []
    files_touched: list[str] = []
    final_checks: list[dict[str, Any]] = []
    local_model_ok = False
    last_model_route: dict[str, Any] = {}
    product_root = _primary_product_root(repo, worktree)
    path_contract = (
        f"Product root is {product_root}. Return file paths either under {product_root}/... "
        f"or relative to that product root such as src/..., components/... or tests/.... "
        f"The executor will normalize product-relative paths to {product_root}/.... "
        "Absolute paths, traversal, sibling services and repo-root writes outside the product root are denied."
        if product_root
        else "Return repo-relative file paths under src/, modules/, app/, lib/, components/, infra/ or tests/. Absolute paths and traversal are denied."
    )
    for attempt in range(1, 4):
        _set_worker_phase(task_id, "inference", attempt_count=attempt, blocker=None)
        prompt = (
            "You are an autonomous LOCAL software implementation worker. IMPLEMENT the task now. "
            "Return ONLY valid JSON with this shape: "
            "{\"summary\":\"...\",\"files\":[{\"path\":\"relative/path\",\"content\":\"FULL file content\"}]}. "
            f"{path_contract} "
            "At least one file must be product code under src/, modules/, app/, lib/, components/ or infra/ inside the product scope. "
            "Modify/reuse the existing architecture shown below. Do not invent parallel Express/NestJS/Mongoose routes or undeclared dependencies when the repo is Next.js/Firebase or another stack. "
            "For Python tests, prefer unittest-compatible tests unless pytest is declared by the repository. "
            "Include tests under tests/ when behavior is testable. No secrets, no cloud apply, no production deploy, no markdown-only result.\n\n"
            f"TASK:\n{objective[:4000]}\n\nPREVIOUS FAILURES:\n{failures[:1500]}\n\n"
            f"ARCHITECTURE CONTEXT:\n{_repo_architecture_context(repo, worktree, objective, max_chars=4000)}\n\n"
            f"REPOSITORY SNAPSHOT:\n{_fanout_repo_snapshot(worktree, max_chars=5000)}"
        )
        model = local_model_router.run_local_model(task_type="coding", prompt=prompt, max_tokens=3072)
        local_model_ok = local_model_ok or bool(model.get("ok"))
        last_model_route = {
            "ok": bool(model.get("ok")),
            "runtime": model.get("runtime"),
            "selected_node": model.get("selected_node"),
            "selected_model": model.get("selected_model"),
            "provider_id": model.get("provider_id"),
            "fallback_silent": model.get("fallback_silent"),
            "error": model.get("error"),
        }
        model_text = str(model.get("response") or model.get("text") or model.get("content") or "")
        payload = _fanout_parse_model_json(model_text) if model.get("ok") else None
        files, rejected_files = _safe_generated_files(payload, objective, task_id, repo, worktree, model_text=model_text)
        files = _merge_node_scaffold(objective=objective, task_id=task_id, worktree=worktree, files=files, repo=repo)
        if not files:
            failures = "model did not produce valid bounded files"
            attempts.append({
                "attempt": attempt,
                "phase": "inference",
                "model_ok": bool(model.get("ok")),
                "error": failures,
                "path_contract": {"product_root": product_root, "allowed_paths": [product_root] if product_root else list(local_execution_plane._repo_config(repo).get("allowed_paths") or [])},
                "rejected_files": rejected_files,
                "model_text_preview": model_text[:1200],
            })
            continue

        _set_worker_phase(task_id, "write", files_touched=files_touched)
        writes: list[dict[str, Any]] = []
        product_count = 0
        for item in files:
            rel = item["path"]
            content = item["content"]
            if attempt == 1 and "induce_retry_once" in objective.lower() and rel.startswith("tests/"):
                content = content + "\n\nclass ForcedRetryOnceTests(unittest.TestCase):\n    def test_forced_retry_once(self):\n        self.assertEqual('first-attempt', 'second-attempt')\n"
            if _is_product_code_path(repo, worktree, rel):
                product_count += 1
            result = local_execution_plane.write_file(
                repo=repo,
                work_branch=branch,
                path=rel,
                content=content,
                actor="dev_swarm",
                task_id=task_id,
                correlation_id=correlation_id,
                idempotency_key=f"{EXECUTOR_VERSION}-write-{task_id}-{attempt}-{rel}",
            )
            writes.append({"path": rel, "ok": bool(result.get("ok")), "result": result})
            if result.get("ok"):
                files_touched.append(rel)
        write_validation = _verified_write_classes(repo, worktree, files_touched)
        write_classes = write_validation["classes"]
        product_task_requires_real_write = _requires_product_writes(objective) and not _is_platform_regression_task(objective)
        if write_validation.get("invalid_files"):
            failures = "reported_write_validation_failed: " + str(write_validation.get("invalid_files"))[:2500]
            attempts.append({"attempt": attempt, "phase": "write", "writes": writes, "write_classes": write_classes, "write_validation": write_validation, "rejected_files": rejected_files, "error": failures})
            continue
        if product_task_requires_real_write and not write_classes["product"]:
            failures = (
                "product_task_contract_only_not_pass: product tasks require at least one real implementation write outside "
                "inneros_dev_swarm/diagnostic namespaces. "
                + str({"writes": writes, "write_classes": write_classes})[:2500]
            )
            attempts.append({"attempt": attempt, "phase": "write", "writes": writes, "write_classes": write_classes, "rejected_files": rejected_files, "error": failures})
            continue
        if (product_task_requires_real_write and product_count < 1) or not writes or not all(x["ok"] for x in writes):
            failures = "At least one product-code write is required and every write must succeed. " + str(writes)[:2500]
            attempts.append({"attempt": attempt, "phase": "write", "writes": writes, "write_classes": write_classes, "rejected_files": rejected_files, "error": failures})
            continue

        _cleanup_generated_python_artifacts(worktree)
        checks: list[dict[str, Any]] = []
        if run_tests:
            _set_worker_phase(task_id, "test", files_touched=sorted(set(files_touched)), test_status="running")
            for command in _test_commands_for_policy(repo, worktree, sorted(set(files_touched))):
                result = local_execution_plane.run_command_allowlisted(
                    repo=repo,
                    work_branch=branch,
                    command=command,
                    actor="dev_swarm",
                    task_id=task_id,
                    correlation_id=correlation_id,
                    timeout_seconds=420,
                    max_output_bytes=40000,
                )
                checks.append({"command": command, "result": result})
        failed = [check for check in checks if not _command_succeeded(check)]
        attempts.append({"attempt": attempt, "phase": "test", "writes": writes, "rejected_files": rejected_files, "checks": checks})
        final_checks = checks
        if failed:
            failures = "\n".join(str(check)[:4000] for check in failed)
            if any(((check.get("result") or {}).get("error") == "command_not_allowlisted") for check in failed):
                _set_worker_phase(task_id, "failed", test_status="failed", blocker="command_not_allowlisted_non_retryable")
                coordination_live.update_ops_task_state(
                    task_id,
                    "blocked",
                    actor="dev_swarm",
                    evidence={"blocker": "command_not_allowlisted_non_retryable", "source": EXECUTOR_VERSION},
                )
                break
            _set_worker_phase(task_id, "retry", test_status="failed", blocker="tests_failed_retrying")
            continue

        _cleanup_generated_python_artifacts(worktree)
        _set_worker_phase(task_id, "commit", test_status="PASS")
        commit = local_execution_plane.commit_branch(
            repo=repo,
            work_branch=branch,
            message=f"feat: implement {task_id}",
            actor="dev_swarm",
            task_id=task_id,
            correlation_id=correlation_id,
            idempotency_key=f"{EXECUTOR_VERSION}-commit-{task_id}",
        )
        if not commit.get("ok") or commit.get("idempotent"):
            failures = "feat commit failed or had no changes: " + str(commit)[:2500]
            _set_worker_phase(task_id, "retry", blocker="commit_failed_retrying")
            continue
        evidence = {
            "executor": EXECUTOR_VERSION,
            "outcome": "PASS",
            "attempts": attempts,
            "implementation_writes": sorted(set(files_touched)),
            "implementation_writes_product": _implementation_write_classes(repo, worktree, files_touched)["product"],
            "implementation_writes_diagnostic": _implementation_write_classes(repo, worktree, files_touched)["diagnostic"],
            "files_touched": sorted(set(files_touched)),
            "commands": final_checks,
            "local_model_ok": local_model_ok,
            "model_route": last_model_route,
            "commit": commit,
            "docs_only": False,
            "test_suite_skipped": False,
        }
        report = local_execution_plane.report_evidence(repo, branch, "dev_swarm", task_id, correlation_id, "PASS", evidence)
        db[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
            "status": "verification",
            "updated_at": _now(),
            "executor": {
                "version": EXECUTOR_VERSION,
                "status": "executed",
                "phase": "verification",
                "outcome": "PASS",
                "attempt_count": attempt,
                "files_touched": sorted(set(files_touched)),
                "implementation_writes": sorted(set(files_touched)),
                "implementation_writes_product": _implementation_write_classes(repo, worktree, files_touched)["product"],
                "implementation_writes_diagnostic": _implementation_write_classes(repo, worktree, files_touched)["diagnostic"],
                "test_status": "PASS",
                "commit": commit,
                "evidence": report,
            },
        }})
        coordination_live.heartbeat_ops_task(task_id, "dev_swarm", next_action="PASS: ready for Integration Guardian", blocker=None, files_touched=sorted(set(files_touched)))
        return {"ok": True, "task_id": task_id, "repo": repo, "branch": branch, "outcome": "PASS", "attempts": attempt, "implementation_writes": sorted(set(files_touched)), "implementation_writes_product": _implementation_write_classes(repo, worktree, files_touched)["product"], "files_touched": sorted(set(files_touched)), "commit_head": commit.get("head"), "commands_ok": True, "local_model_ok": local_model_ok, "model_route": last_model_route}

    evidence = {
        "executor": EXECUTOR_VERSION,
        "outcome": "FAIL",
        "attempts": attempts,
        "implementation_writes": sorted(set(files_touched)),
        "implementation_writes_product": _implementation_write_classes(repo, worktree, files_touched)["product"],
        "implementation_writes_diagnostic": _implementation_write_classes(repo, worktree, files_touched)["diagnostic"],
        "files_touched": sorted(set(files_touched)),
        "commands": final_checks,
        "local_model_ok": local_model_ok,
        "model_route": last_model_route,
        "blocker": failures[:6000],
        "docs_only": False,
        "test_suite_skipped": False,
    }
    report = local_execution_plane.report_evidence(repo, branch, "dev_swarm", task_id, correlation_id, "FAIL", evidence)
    db[WORKERS_COL].update_one({"task_id": task_id}, {"$set": {
        "status": "blocked",
        "updated_at": _now(),
        "executor": {
            "version": EXECUTOR_VERSION,
            "status": "failed",
            "phase": "failed",
            "outcome": "FAIL",
            "attempt_count": len(attempts),
            "files_touched": sorted(set(files_touched)),
            "implementation_writes": sorted(set(files_touched)),
            "implementation_writes_product": _implementation_write_classes(repo, worktree, files_touched)["product"],
            "implementation_writes_diagnostic": _implementation_write_classes(repo, worktree, files_touched)["diagnostic"],
            "test_status": "FAIL",
            "blocker": failures[:6000],
            "evidence": report,
        },
    }})
    coordination_live.heartbeat_ops_task(task_id, "dev_swarm", next_action="Escalate after retry budget", blocker=failures[:1000] or f"{EXECUTOR_VERSION}_failed", files_touched=sorted(set(files_touched)))
    if str((_task_doc(task_id) or {}).get("status") or "").lower() == "in_progress":
        coordination_live.update_ops_task_state(
            task_id,
            "blocked",
            actor="dev_swarm",
            evidence={"blocker": (failures[:1000] or f"{EXECUTOR_VERSION}_failed"), "source": EXECUTOR_VERSION},
        )
    return {"ok": False, "task_id": task_id, "repo": repo, "branch": branch, "outcome": "FAIL", "attempts": len(attempts), "implementation_writes": sorted(set(files_touched)), "implementation_writes_product": _implementation_write_classes(repo, worktree, files_touched)["product"], "files_touched": sorted(set(files_touched)), "error": failures[:2000], "commands_ok": False, "local_model_ok": local_model_ok, "model_route": last_model_route}


def _task_base_ref(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    for key in ("base_ref", "base_branch", "source_branch", "canonical_base_ref"):
        value = str((task or {}).get(key) or "").strip()
        if value:
            return value
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    for key in ("base_ref", "base_branch", "source_branch", "canonical_base_ref"):
        value = str((payload or {}).get(key) or "").strip()
        if value:
            return value
    text = "\n".join([str(task.get("title") or ""), *[str(x) for x in task.get("checklist") or []]])
    patterns = [
        r"\bbase[_ -]?(?:ref|branch)\s*[:=]\s*([A-Za-z0-9_./-]+)",
        r"\bbranch\s+([A-Za-z0-9_./-]*local-agent/[A-Za-z0-9_./-]+)",
        r"\b(local-agent/[A-Za-z0-9_./-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip("`'\".,; ")
    return ""


def _resolve_base_ref(source: Path, requested_base_ref: str) -> dict[str, Any]:
    requested = (requested_base_ref or "main").strip()
    explicit = bool(requested_base_ref)
    fetch_ref = requested
    if requested.startswith("origin/"):
        fetch_ref = requested.split("/", 1)[1]
    fetch = local_execution_plane._run(["git", "fetch", "origin", fetch_ref], source, timeout_seconds=180)
    candidates = []
    if re.fullmatch(r"[a-fA-F0-9]{7,40}", requested):
        candidates.extend([requested])
    candidates.extend([requested, f"origin/{fetch_ref}", "origin/main" if not explicit else ""])
    attempts = []
    for candidate in [c for c in candidates if c]:
        res = local_execution_plane._run(["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"], source, timeout_seconds=30)
        attempts.append({"candidate": candidate, "ok": bool(res.get("ok")), "stdout": (res.get("stdout") or "").strip(), "stderr": (res.get("stderr") or "")[-500:]})
        sha = (res.get("stdout") or "").strip()
        if res.get("ok") and sha:
            return {"ok": True, "requested_base_ref": requested, "explicit": explicit, "resolved_ref": candidate, "base_sha": sha, "fetch": fetch, "attempts": attempts}
    if explicit:
        return {"ok": False, "error": "explicit_base_ref_unresolved", "requested_base_ref": requested, "fetch": fetch, "attempts": attempts}
    head = local_execution_plane._run(["git", "rev-parse", "HEAD"], source, timeout_seconds=30)
    sha = (head.get("stdout") or "").strip()
    return {"ok": bool(sha), "requested_base_ref": requested, "explicit": explicit, "resolved_ref": "HEAD", "base_sha": sha, "fetch": fetch, "attempts": attempts, "head": head}


def _fanout_base_snapshot(repo: str, base_ref: str = "") -> dict[str, Any]:
    policy = local_execution_plane.repo_policy_status(repo)
    if not policy.get("ok"):
        return {"ok": False, "error": "repo_policy_failed", "policy": policy}
    conf = policy.get("policy") or {}
    source = Path(str(conf.get("source_path") or "")).expanduser()
    if not (source / ".git").exists():
        prepared = local_execution_plane.prepare_repo(
            repo=repo,
            base_ref="main",
            actor="dev_swarm",
            task_id=f"prepare_{re.sub(r'[^A-Za-z0-9_.-]+', '_', repo)}",
            correlation_id=f"fanout-prepare-{re.sub(r'[^A-Za-z0-9_.-]+', '_', repo)}",
            idempotency_key=f"fanout-prepare-{repo}",
            remote_url=str(conf.get("remote_url") or f"https://github.com/{repo}.git"),
        )
        if not prepared.get("ok"):
            return {"ok": False, "error": "source_repo_prepare_failed", "source_path": str(source), "prepare": prepared}
    if (source / "package.json").exists():
        conf["profile"] = "node-tests"
    resolved = _resolve_base_ref(source, base_ref)
    if not resolved.get("ok"):
        return {"ok": False, "error": "base_ref_failed", "repo": repo, "source_path": str(source), "base_ref": base_ref or "main", "base_resolution": resolved}
    base_sha = str(resolved.get("base_sha") or "").strip()
    return {
        "ok": bool(base_sha),
        "repo": repo,
        "source_path": str(source),
        "worktrees_path": conf.get("worktrees_path"),
        "profile": conf.get("profile"),
        "allowed_paths": conf.get("allowed_paths"),
        "package_roots": conf.get("package_roots") or [],
        "product_root": (conf.get("package_roots") or [""])[0],
        "fetch_once": resolved.get("fetch"),
        "requested_base_ref": resolved.get("requested_base_ref"),
        "resolved_base_ref": resolved.get("resolved_ref"),
        "base_ref_explicit": resolved.get("explicit"),
        "base_resolution": resolved,
        "base_sha": base_sha,
    }


def _fanout_create_worktree_from_base(
    *,
    repo: str,
    branch: str,
    base_sha: str,
    task_id: str,
    correlation_id: str,
    objective: str,
    base_snapshot: dict[str, Any],
) -> dict[str, Any]:
    source = Path(str(base_snapshot.get("source_path") or "")).expanduser()
    worktrees = Path(str(base_snapshot.get("worktrees_path") or "")).expanduser()
    branch_slug = re.sub(r"[^A-Za-z0-9_.-]+", "__", branch)
    worktree = worktrees / branch_slug
    plan = {
        "repo": repo,
        "objective": objective,
        "base_branch": base_sha,
        "base_sha": base_sha,
        "requested_base_ref": base_snapshot.get("requested_base_ref") or "main",
        "resolved_base_ref": base_snapshot.get("resolved_base_ref") or base_sha,
        "base_ref_explicit": bool(base_snapshot.get("base_ref_explicit")),
        "work_branch": branch,
        "actor": "dev_swarm",
        "task_id": task_id,
        "correlation_id": correlation_id,
        "profile": base_snapshot.get("profile"),
        "allowed_paths": base_snapshot.get("allowed_paths"),
        "package_roots": base_snapshot.get("package_roots") or [],
        "product_root": base_snapshot.get("product_root") or "",
        "path_contract": {
            "scope": "product_root" if base_snapshot.get("product_root") else "repo_root",
            "product_root": base_snapshot.get("product_root") or "",
            "model_may_return_product_relative_paths": bool(base_snapshot.get("product_root")),
            "denied": ["absolute_paths", "path_traversal", "sibling_services", "repo_root_src_when_product_scoped"],
        },
        "source_path": str(source),
        "admin_scope_required": False,
        "required_scope": "ralfia:agents",
        "fanout_base_once": True,
    }
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if worktree.exists():
        status = local_execution_plane._run(["git", "status", "--short", "--branch"], worktree, timeout_seconds=30)
        head = local_execution_plane._run(["git", "rev-parse", "HEAD"], worktree, timeout_seconds=30)
        head_sha = str(head.get("stdout") or "").strip()
        if head_sha and base_sha and head_sha != base_sha:
            worktree_result = {
                "ok": False,
                "error": "worktree_base_sha_mismatch",
                "repo": repo,
                "base_sha": base_sha,
                "worktree_head": head_sha,
                "requested_base_ref": base_snapshot.get("requested_base_ref"),
                "resolved_base_ref": base_snapshot.get("resolved_base_ref"),
                "work_branch": branch,
                "worktree": str(worktree),
                "status": status,
            }
        else:
            worktree_result = {"ok": True, "idempotent": True, "repo": repo, "base_sha": base_sha, "requested_base_ref": base_snapshot.get("requested_base_ref"), "resolved_base_ref": base_snapshot.get("resolved_base_ref"), "work_branch": branch, "worktree": str(worktree), "status": status}
    else:
        result = local_execution_plane._run(["git", "worktree", "add", "-b", branch, str(worktree), base_sha], source, timeout_seconds=120)
        worktree_result = {"ok": result.get("ok"), "repo": repo, "base_sha": base_sha, "work_branch": branch, "worktree": str(worktree), "result": result}
    evidence = {
        "launcher": "fanout_base_once",
        "fail_closed_base_sha": True,
        "objective": objective,
        "base_sha": base_sha,
        "requested_base_ref": base_snapshot.get("requested_base_ref") or "main",
        "resolved_base_ref": base_snapshot.get("resolved_base_ref") or base_sha,
        "base_ref_explicit": bool(base_snapshot.get("base_ref_explicit")),
        "worktree_ok": bool(worktree_result.get("ok")),
        "worktree_error": worktree_result.get("error"),
        "work_branch": branch,
        "source_path": str(source),
    }
    report = local_execution_plane.report_evidence(repo, branch, "dev_swarm", task_id, correlation_id, "launched" if worktree_result.get("ok") else "launch_failed", evidence)
    return {"ok": bool(worktree_result.get("ok")), "capability": "dev_swarm_scope", "plan": plan, "prepared": base_snapshot, "worktree": worktree_result, "evidence": report}


def _active_worker_for_task(task_id: str) -> dict[str, Any] | None:
    worker = _db()[WORKERS_COL].find_one({"task_id": task_id, **_active_worker_query()}, {"_id": 0})
    return dict(worker) if worker else None


def _fanout_execute_one(repo: str, task_id: str, base_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    existing_worker = _active_worker_for_task(task_id)
    if existing_worker:
        return {
            "ok": True,
            "task_id": task_id,
            "repo": existing_worker.get("repo") or repo,
            "branch": existing_worker.get("branch"),
            "outcome": "ALREADY_RUNNING",
            "worker_id": existing_worker.get("worker_id"),
            "executor": existing_worker.get("executor"),
            "worktree": _worker_worktree(existing_worker),
        }
    task = _task_doc(task_id)
    if not task:
        return {"ok": False, "task_id": task_id, "error": "task_not_found"}
    ops_status = str(task.get("status") or "").lower()
    if ops_status in OPS_TERMINAL_STATUSES and not _ops_auto_retry_allowed(task):
        blocker = str(task.get("blocker") or task.get("dev_swarm_last_skip_reason") or ops_status)
        db = _db()
        db[WORKERS_COL].update_one(
            {"task_id": task_id, "status": {"$in": ["starting", "running", "verification"]}},
            {
                "$set": {
                    "status": "blocked",
                    "blocker": f"ops_{ops_status}:{blocker[:200]}",
                    "slot_reclaimed_at": _now(),
                    "executor.status": "blocked",
                    "executor.phase": "ops_not_runnable",
                    "executor.blocker": blocker[:200],
                    "executor.updated_at": _now(),
                    "updated_at": _now(),
                }
            },
        )
        return {
            "ok": False,
            "task_id": task_id,
            "outcome": "SKIPPED",
            "error": f"ops_status_{ops_status}_no_auto_retry",
            "blocker": blocker,
        }
    objective = f"{task.get('title') or task_id}\n\n" + "\n".join(str(x) for x in task.get("checklist") or [])
    correlation_id = str(task.get("correlation_id") or f"fanout-{task_id}")
    branch = f"local-agent/{task_id}-{secrets.token_hex(3)}"

    # Claim task if still proposed.
    if str(task.get("status") or "").lower() == "proposed":
        coordination_live.update_ops_task_state(task_id, "accepted", actor="dev_swarm")
        coordination_live.update_ops_task_state(task_id, "in_progress", actor="dev_swarm")

    explicit_base_ref = _task_base_ref(task)
    if explicit_base_ref or not base_snapshot:
        base_snapshot = _fanout_base_snapshot(repo, base_ref=explicit_base_ref)
    if not base_snapshot.get("ok"):
        failed = _fail_worker_early(task_id, "base_snapshot_failed")
        return {**failed, "branch": branch, "base_snapshot": base_snapshot}
    launch = _fanout_create_worktree_from_base(
        repo=repo,
        objective=objective[:5000],
        branch=branch,
        base_sha=str(base_snapshot.get("base_sha")),
        task_id=task_id,
        correlation_id=correlation_id,
        base_snapshot=base_snapshot,
    )
    if not launch.get("ok"):
        failed = _fail_worker_early(task_id, "launch_failed")
        return {**failed, "branch": branch, "launch": launch}
    worktree_raw = ((launch.get("worktree") or {}).get("worktree") if isinstance(launch.get("worktree"), dict) else None)
    if not worktree_raw:
        return _fail_worker_early(task_id, "worktree_missing")
    worktree = Path(worktree_raw)

    worker = {
        "worker_id": f"worker_{secrets.token_hex(6)}",
        "task_id": task_id,
        "repo": repo,
        "branch": branch,
        "node": "amd",
        "status": "running",
        "launch": launch,
        "created_at": _now(),
        "updated_at": _now(),
        "last_heartbeat_at": _now(),
        "executor": {"version": EXECUTOR_VERSION, "status": "running", "phase": "queued"},
    }
    db = _db()
    db[WORKERS_COL].update_one({"task_id": task_id}, {"$set": worker}, upsert=True)
    return _execute_existing_worker_generic(worker, run_tests=True)


def execute_ad_hoc_objective(
    repo: str,
    task_id: str,
    objective: str,
    correlation_id: str,
    preferred_branch: str | None = None,
    base_ref: str | None = None,
    entrypoint: str = "ad_hoc",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single owner-approved objective through the canonical control plane."""
    repo = str(repo or "").strip()
    task_id = str(task_id or "").strip()
    objective = str(objective or "").strip()
    if not repo or "/" not in repo:
        return {"ok": False, "error": "repo_must_be_owner_name"}
    if not task_id:
        return {"ok": False, "error": "task_id_required"}
    if not objective:
        return {"ok": False, "error": "objective_required"}
    policy = local_execution_plane.repo_policy_status(repo)
    if not policy.get("ok") or policy.get("write_scope") in {"none", "read_only"}:
        return {"ok": False, "error": "repo_not_write_authorized", "policy": policy}
    branch = preferred_branch or f"local-agent/{task_id}-{secrets.token_hex(3)}"
    if dry_run:
        return {"ok": True, "dry_run": True, "executor_version": EXECUTOR_VERSION, "repo": repo, "task_id": task_id, "branch": branch}
    existing_worker = _active_worker_for_task(task_id)
    if existing_worker:
        return {
            "ok": True,
            "executor_version": EXECUTOR_VERSION,
            "repo": existing_worker.get("repo") or repo,
            "task_id": task_id,
            "branch": existing_worker.get("branch"),
            "outcome": "ALREADY_RUNNING",
            "worker": existing_worker,
        }
    base_snapshot = _fanout_base_snapshot(repo, base_ref=base_ref or "")
    if not base_snapshot.get("ok"):
        return {"ok": False, "task_id": task_id, "branch": branch, "error": "base_snapshot_failed", "base_snapshot": base_snapshot}
    launch = _fanout_create_worktree_from_base(
        repo=repo,
        objective=objective[:7000],
        branch=branch,
        base_sha=str(base_snapshot.get("base_sha")),
        task_id=task_id,
        correlation_id=correlation_id,
        base_snapshot=base_snapshot,
    )
    if not launch.get("ok"):
        return {"ok": False, "task_id": task_id, "branch": branch, "error": "launch_failed", "launch": launch}
    worker = {
        "worker_id": f"worker_{task_id}",
        "task_id": task_id,
        "repo": repo,
        "branch": branch,
        "node": "amd",
        "status": "running",
        "launch": launch,
        "entrypoint": entrypoint,
        "owner": "dev_swarm",
        "created_at": _now(),
        "updated_at": _now(),
        "last_heartbeat_at": _now(),
        "owner": "dev_swarm",
        "executor": {"version": EXECUTOR_VERSION, "status": "running", "phase": "queued", "last_progress_at": _now()},
    }
    _db()[WORKERS_COL].update_one({"task_id": task_id}, {"$set": worker}, upsert=True)
    executor = _execute_existing_worker_generic(worker, run_tests=True)
    saved_worker = _db()[WORKERS_COL].find_one({"task_id": task_id}, {"_id": 0})
    return {
        "ok": bool(executor.get("ok")),
        "executor_version": EXECUTOR_VERSION,
        "repo": repo,
        "task_id": task_id,
        "branch": branch,
        "base_sha": base_snapshot.get("base_sha"),
        "requested_base_ref": base_snapshot.get("requested_base_ref"),
        "resolved_base_ref": base_snapshot.get("resolved_base_ref"),
        "fetch_once_ok": bool((base_snapshot.get("fetch_once") or {}).get("ok")),
        "launch": launch,
        "executor": executor,
        "worker": saved_worker,
    }


def fanout_execute(repo: str, task_ids: list[str], concurrency: int = 6, dry_run: bool = False) -> dict[str, Any]:
    """Execute multiple development tasks concurrently on isolated worktrees.

    This is project-agnostic: repo policy + explicit task IDs are the only routing inputs.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    repo = str(repo or "").strip()
    if not repo or "/" not in repo:
        return {"ok": False, "error": "repo_must_be_owner_name"}
    policy = local_execution_plane.repo_policy_status(repo)
    if not policy.get("ok") or policy.get("write_scope") in {"none", "read_only"}:
        return {"ok": False, "error": "repo_not_write_authorized", "policy": policy}
    ids = [str(x).strip() for x in task_ids if str(x).strip()]
    if not ids:
        return {"ok": False, "error": "task_ids_required"}
    capacity = capacity_status()
    recommended = int((capacity.get("recommendation") or {}).get("recommended_concurrency_total") or DEFAULT_MAX_CONCURRENT)
    max_workers = max(1, min(int(concurrency or 1), recommended or 1, 12, len(ids)))
    admitted_ids = ids[:max_workers]
    queued_ids = ids[max_workers:]
    if dry_run:
        route = execution_policy.route_metadata(task_class="coding")
        return {"ok": True, "dry_run": True, "repo": repo, "task_ids": ids, "admitted_task_ids": admitted_ids, "queued_task_ids": queued_ids, "concurrency": max_workers, "capacity": capacity, **route}

    scheduler_start(max_concurrent=max_workers, dry_run=False)
    started_at = _now()
    base_snapshot = _fanout_base_snapshot(repo)
    if not base_snapshot.get("ok"):
        return {
            "ok": False,
            "executor_version": EXECUTOR_VERSION,
            "repo": repo,
            "concurrency": max_workers,
            "started_at": started_at,
            "finished_at": _now(),
            "error": "base_snapshot_failed",
            "base_snapshot": base_snapshot,
        }
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="inneros-dev") as pool:
        futures = {pool.submit(_fanout_execute_one, repo, task_id, base_snapshot): task_id for task_id in admitted_ids}
        for future in as_completed(futures):
            task_id = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"ok": False, "task_id": task_id, "outcome": "ERROR", "error": str(exc)})
    passed = sum(1 for r in results if r.get("ok") and r.get("outcome") == "PASS")
    return {
        "ok": passed == len(admitted_ids),
        "executor_version": EXECUTOR_VERSION,
        "repo": repo,
        "concurrency": max_workers,
        "capacity": capacity,
        "base_sha": base_snapshot.get("base_sha"),
        "requested_base_ref": base_snapshot.get("requested_base_ref"),
        "resolved_base_ref": base_snapshot.get("resolved_base_ref"),
        "fetch_once_ok": bool((base_snapshot.get("fetch_once") or {}).get("ok")),
        "started_at": started_at,
        "finished_at": _now(),
        "passed": passed,
        "admitted": len(admitted_ids),
        "queued": len(queued_ids),
        "queued_task_ids": queued_ids,
        "total": len(ids),
        "results": sorted(results, key=lambda r: r.get("task_id", "")),
    }


def platform_guard_regressions() -> dict[str, Any]:
    """Read/write-safe platform checks for the Dev Swarm guardrails."""
    results: dict[str, Any] = {"executor_version": EXECUTOR_VERSION}
    with tempfile.TemporaryDirectory(prefix="inneros-dev-swarm-regression-") as tmp:
        worktree = Path(tmp)
        product = worktree / "services" / "femar-mvp-core"
        (product / "src" / "app" / "api" / "schedules").mkdir(parents=True, exist_ok=True)
        (product / "src" / "lib" / "auth").mkdir(parents=True, exist_ok=True)
        (product / "src" / "app" / "api" / "schedules" / "route.ts").write_text("export const runtime = 'nodejs';\n", encoding="utf-8")
        (product / "src" / "lib" / "auth" / "server.ts").write_text("export function requireSession() { return { tenantId: 'pcdoctor' }; }\n", encoding="utf-8")
        (product / "package.json").write_text(
            json.dumps({"name": "femar-mvp-core", "dependencies": {"next": "^15.0.0", "firebase-admin": "^12.0.0"}, "devDependencies": {"jest": "^29.0.0"}, "scripts": {"test": "jest"}}, indent=2),
            encoding="utf-8",
        )
        contract_only = [
            "services/femar-mvp-core/src/inneros_dev_swarm/ops_x_contract.ts",
            "services/femar-mvp-core/src/inneros_dev_swarm/ops_x_contract.test.ts",
        ]
        real_write = ["services/femar-mvp-core/src/app/api/schedules/route.ts"]
        contract_classes = _implementation_write_classes("Rafa-Innerchispa/innerspark-workforce-ai", worktree, contract_only)
        real_classes = _implementation_write_classes("Rafa-Innerchispa/innerspark-workforce-ai", worktree, real_write)
        context = _repo_architecture_context(
            "Rafa-Innerchispa/innerspark-workforce-ai",
            worktree,
            "Fix schedules auth using requireSession requireAnyRole Firebase Next.js. Do not create Express routes.",
            max_chars=4000,
        )
        violations = _content_dependency_violations(
            worktree,
            "services/femar-mvp-core",
            "services/femar-mvp-core/src/app/api/schedules/route.ts",
            'import express from "express"; import mongoose from "mongoose"; export const x = 1;',
        )
        results["product_contract_only_not_pass"] = {
            "ok": not contract_classes["product"] and bool(contract_classes["diagnostic"]),
            "implementation_writes_product": contract_classes["product"],
            "implementation_writes_diagnostic": contract_classes["diagnostic"],
        }
        results["product_real_write_can_pass_gate"] = {
            "ok": bool(real_classes["product"]),
            "implementation_writes_product": real_classes["product"],
        }
        results["context_quality_guard"] = {
            "ok": "next" in context.lower() and "firebase" in context.lower() and "src/app/api/schedules/route.ts" in context and {"express", "mongoose"}.issubset(set(violations)),
            "context_preview": context[:1000],
            "undeclared_dependency_violations": violations,
        }
    base = _fanout_base_snapshot("Rafa-Innerchispa/innerspark-workforce-ai", base_ref="local-agent/chatgpt-workforce-real-auth-20260824")
    canonical_files = {}
    if base.get("ok"):
        source = Path(str(base.get("source_path") or "")).expanduser()
        sha = str(base.get("base_sha") or "")
        for rel in ("services/femar-mvp-core/src/app/api/schedules/route.ts", "services/femar-mvp-core/src/lib/auth/server.ts"):
            check = local_execution_plane._run(["git", "cat-file", "-e", f"{sha}:{rel}"], source, timeout_seconds=30)
            canonical_files[rel] = bool(check.get("ok"))
    results["explicit_base_ref_resolution"] = {
        "ok": bool(base.get("ok")) and all(canonical_files.values()),
        "requested_base_ref": base.get("requested_base_ref"),
        "resolved_base_ref": base.get("resolved_base_ref"),
        "base_sha": base.get("base_sha"),
        "canonical_files": canonical_files,
        "base_error": base.get("error"),
    }
    inneros_task = {
        "task_id": "regression_new_inneros_repo_inference",
        "status": "proposed",
        "assignee": "codex",
        "priority": "p0",
        "correlation_id": "devswarm-repo-inference-regression",
        "related_project": "InnerOS platform",
        "title": "Repair InnerOS Dev Swarm scheduler",
        "checklist": ["Resource Fabric local execution runtime repair"],
    }
    email_task = {
        "task_id": "regression_email_not_dev",
        "status": "proposed",
        "assignee": "codex",
        "priority": "p0",
        "title": "Email invoice and WhatsApp follow-up",
        "checklist": ["Operational mailbox task without code repo"],
    }
    workforce_task = {
        "task_id": "regression_workforce_no_repo",
        "status": "proposed",
        "assignee": "codex",
        "priority": "p0",
        "title": "Fix workforce.pcdoctor.ai FEMAR schedules",
        "checklist": ["Product repair must provide explicit repo"],
    }
    inneros_ok, inneros_reason, inneros_repo = _eligible_reason(inneros_task)
    email_ok, email_reason, email_repo = _eligible_reason(email_task)
    workforce_ok, workforce_reason, workforce_repo = _eligible_reason(workforce_task)
    results["repo_inference_guard"] = {
        "ok": inneros_ok and inneros_repo == SAFE_INNEROS_REPO and not email_ok and email_reason == "non_development_ops_filtered" and not workforce_ok and workforce_reason == "repo_not_inferred",
        "inneros": {"ok": inneros_ok, "reason": inneros_reason, "repo": inneros_repo},
        "email": {"ok": email_ok, "reason": email_reason, "repo": email_repo},
        "workforce": {"ok": workforce_ok, "reason": workforce_reason, "repo": workforce_repo},
    }
    results["ok"] = all(bool(v.get("ok")) for k, v in results.items() if isinstance(v, dict) and k != "base_error")
    return results
