#!/usr/bin/env python3
"""Cursor HA E2E: temporal worker health + read-only Cursor ops canary."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REPO = "Rafa-Innerchispa/innerops-agentic-platform"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host() -> str:
    return socket.gethostname().lower()


def _worker_running() -> bool:
    proc = subprocess.run(["pgrep", "-f", "inneros_core_runtime.temporal_worker"], capture_output=True, text=True, check=False)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _temporal_port() -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", 7233)) == 0


def _run_cursor_readonly_canary(*, correlation_id: str) -> dict[str, Any]:
    from inneros_core_runtime import coordination_live as cl
    from inneros_core_runtime import interactive_ops_runner as ior
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    objective = (
        "Solo lectura: git rev-parse HEAD en el worktree; entregar commit_sha en evidencia. "
        "Prohibido modificar archivos."
    )
    created = cl.create_ops_task(
        assignee="cursor",
        title=f"[cursor-ha-e2e] read-only HEAD @ {_host()}",
        correlation_id=correlation_id,
        repo=DEFAULT_REPO,
        objective=objective,
        task_class="verification",
        execution_lane="cursor_interactive",
        preferred_provider="cursor",
        do_not_auto_dispatch=True,
        idempotency_key=f"{correlation_id}|cursor",
        evidence_required=["commit_sha"],
        from_agent="cursor_ha_e2e_probe",
    )
    if not created.get("ok"):
        return {"ok": False, "stage": "create", "create": created}

    task_id = str(created.get("task_id") or (created.get("task") or {}).get("task_id") or "")
    ior.authorize_ops_task("cursor", task_id, owner_actor="RAFAEL", channel="cursor_ha_e2e")
    claim = ior.claim_ops_task("cursor", task_id=task_id, owner_approved=True)
    if not claim.get("ok"):
        return {"ok": False, "stage": "claim", "task_id": task_id, "claim": claim}

    wt = str(claim.get("worktree") or ROOT)
    proc = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "stage": "git", "task_id": task_id, "stderr": proc.stderr.strip()}

    commit_sha = proc.stdout.strip()
    done = ior.complete_ops_task(
        "cursor",
        task_id,
        claim_token=str(claim.get("claim_token") or ""),
        status="completed",
        evidence={"commit_sha": commit_sha, "notes": f"cursor-ha-e2e readonly @ {wt}", "probe_host": _host()},
    )

    db = mongo_store.get_db()
    deadline = time.time() + 180
    final: dict[str, Any] = {}
    while time.time() < deadline:
        final = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
        if str(final.get("status") or "") in {"completed", "failed", "cancelled", "superseded"}:
            break
        time.sleep(2)

    ok = bool(done.get("ok")) and str(final.get("status") or "") == "completed"
    return {
        "ok": ok,
        "task_id": task_id,
        "correlation_id": correlation_id,
        "claim": claim,
        "complete": done,
        "final_status": final.get("status"),
        "commit_sha": commit_sha,
        "temporal_handoff": claim.get("temporal_handoff"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-node", choices=("amd", "intel", "local"), default="local")
    parser.add_argument("--run-autopilot", action="store_true")
    args = parser.parse_args()

    node = args.target_node
    if node == "local":
        node = "amd" if "amd" in _host() else ("intel" if "intel" in _host() or "ver-10" in _host() else "local")

    correlation_id = f"cursor-ha-e2e-{node}-{uuid.uuid4().hex[:10]}"
    report: dict[str, Any] = {
        "ok": False,
        "target_node": node,
        "host": _host(),
        "started_at": _utc(),
        "temporal_port_open": _temporal_port(),
        "temporal_worker_running": _worker_running(),
        "correlation_id": correlation_id,
    }

    if not report["temporal_port_open"] or not report["temporal_worker_running"]:
        report["error"] = "temporal_not_ready"
        print(json.dumps(report, indent=2, default=str))
        return 2

    report["canary"] = _run_cursor_readonly_canary(correlation_id=correlation_id)
    report["ok"] = bool(report["canary"].get("ok"))
    report["finished_at"] = _utc()

    out_dir = Path("/home/rlopez/inneros/inneros_core/var/evidence")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"cursor_ha_e2e_{node}_{correlation_id.split('-')[-1]}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["evidence_path"] = str(out_path)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
