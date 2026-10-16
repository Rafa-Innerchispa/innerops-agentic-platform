#!/usr/bin/env python3
"""Staged concurrency E2E (2/4/8) — real Dev Swarm workers + safe smoke objectives."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import dev_swarm_scheduler as ds
from inneros_core_runtime.coordination_live import create_ops_task, OPS_TASKS_COL
from raphiia_openai import mongo_store

SAFE_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
STAGES = (2, 4, 8)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_task(idx: int) -> dict:
    objective = f"TEST CONCURRENCY_E2E #{idx}: compute sha256 of platform/README.md and exit 0."
    out = create_ops_task(
        assignee="dev_swarm",
        title=f"[TEST CONCURRENCY_E2E] lane smoke {idx}",
        checklist=[objective, "tags: concurrency_e2e"],
        evidence_required=["worker_started_at", "test_results"],
        priority="p1",
        from_agent="concurrency_harness",
        correlation_id=f"concurrency-e2e-{idx}-{_now()}",
        related_project=SAFE_REPO,
        repo=SAFE_REPO,
        base_ref="main",
        work_branch=f"local-agent/concurrency-e2e-{idx}",
        task_class="coding",
        execution_lane="local_dev_swarm",
        preferred_provider="local-amd-5",
    )
    tid = str(out.get("task_id") or "")
    db = mongo_store.get_db()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {
                "owner": "dev_swarm",
                "status": "proposed",
                "dev_swarm_retry_requested": True,
                "tags": ["concurrency_e2e"],
            }
        },
    )
    return {"task_id": tid, "create": out}


def _observe(task_ids: list[str], timeout: int = 300) -> list[dict]:
    db = mongo_store.get_db()
    deadline = time.time() + timeout
    rows: list[dict] = []
    while time.time() < deadline:
        done = 0
        for tid in task_ids:
            t = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
            w = db[ds.WORKERS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
            st = str(t.get("status") or "")
            if st in {"completed", "failed", "blocked", "cancelled"}:
                done += 1
            rows.append(
                {
                    "task_id": tid,
                    "status": st,
                    "worker_id": w.get("worker_id"),
                    "worker_status": w.get("status"),
                    "worker_started_at": t.get("worker_started_at"),
                    "lifecycle_notifications": t.get("lifecycle_notifications"),
                    "blocker": t.get("blocker"),
                }
            )
        if done >= len(task_ids):
            break
        ds.scheduler_tick(limit=len(task_ids))
        time.sleep(8)
    cap = ds.capacity_status()
    return {"tasks": rows, "capacity": cap, "active_workers": ds.scheduler_status().get("active_worker_count")}


def main() -> int:
    report: dict = {"stages": [], "started_at": _now()}
    readme = ROOT / "README.md"
    report["readme_sha256"] = _sha256_file(readme) if readme.is_file() else None
    for n in STAGES:
        batch = [_make_task(i) for i in range(1, n + 1)]
        ids = [b["task_id"] for b in batch]
        obs = _observe(ids, timeout=420 if n >= 8 else 240)
        report["stages"].append({"n": n, "task_ids": ids, "observation": obs})
        # stop if capacity shows hard pressure
        rec = int(((obs.get("capacity") or {}).get("recommendation") or {}).get("admittable_now") or 0)
        if n >= 4 and rec <= 0:
            report["stopped_early"] = "backpressure_admittable_zero"
            break
    out = ROOT.parent / "var" / "evidence" / "concurrency_e2e_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "report_path": str(out), "stages": len(report["stages"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
