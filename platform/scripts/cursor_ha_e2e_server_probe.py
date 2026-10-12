#!/usr/bin/env python3
"""Create + drive one Cursor HA e2e mini-task bound to amd or intel (server-side proof)."""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime import cursor_headless_lanes as lanes
from inneros_core_runtime.coordination_live import OPS_TASKS_COL, create_ops_task
from inneros_core_runtime.memory import agent_messages as am
from raphiia_openai import mongo_store


def _wait_task(tid: str, *, timeout: int = 420) -> dict:
    db = mongo_store.get_db()
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
        if last.get("headless_execution_finished_at"):
            return last
        if last.get("status") in {"verification", "completed", "failed", "blocked"}:
            return last
        time.sleep(5)
    return last


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target-node", choices=("amd", "intel"), required=True)
    p.add_argument("--run-autopilot", action="store_true", help="Run one autopilot tick after create")
    args = p.parse_args()
    here = lanes.node_role()
    if args.run_autopilot and here != args.target_node:
        print(json.dumps({"ok": False, "error": "wrong_node_for_autopilot", "here": here, "want": args.target_node}))
        return 2

    stamp = uuid.uuid4().hex[:8]
    corr = f"co_cursor_ha_e2e_{args.target_node}_{stamp}"
    objective = (
        f"Prueba E2E InnerOS Cursor en servidor {args.target_node}. "
        f"En el worktree del repo crea docs/CURSOR_HA_E2E_{args.target_node.upper()}_{stamp}.md "
        f"con una sola línea: CURSOR_E2E host=$(hostname) node={args.target_node} ts=UTC_NOW. "
        "Guarda el archivo; commit opcional si el repo lo permite."
    )
    created = create_ops_task(
        "cursor",
        f"HA E2E probe {args.target_node} {stamp}",
        objective=objective,
        from_agent="cursor",
        correlation_id=corr,
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        preferred_provider="cursor",
        preferred_model=cor.CURSOR_PINNED_MODEL,
        do_not_auto_dispatch=False,
        payload={
            "cursor_auto_execute": True,
            "headless_auto": True,
            "preferred_execution_host": args.target_node,
            "canary_test_type": "cursor_ha_e2e",
        },
        idempotency_key=f"cursor-ha-e2e-{args.target_node}-{stamp}",
    )
    tid = str(created.get("task_id") or created.get("id") or "")
    if not tid:
        print(json.dumps({"ok": False, "create": created}))
        return 1
    auth = cor.authorize_ops_task_for_cursor(tid, owner_actor="INNEROS_E2E", channel="e2e_probe")
    am.create_agent_message(
        from_agent="chatgpt",
        target_agent="cursor",
        title=f"E2E probe {args.target_node}",
        body=objective[:2000],
        correlation_id=corr,
        message_type="task",
        payload={"task_id": tid, "preferred_execution_host": args.target_node},
        idempotency_key=f"e2e-inbox-{tid}",
    )
    out = {"ok": True, "task_id": tid, "correlation_id": corr, "create": created, "authorize": auth, "host": lanes.hostname(), "role": here}
    if args.run_autopilot:
        import subprocess

        proc = subprocess.run(
            [str(ROOT / "venv/bin/python3"), str(ROOT / "scripts/cursor_ops_headless_autopilot.py")],
            cwd=str(ROOT),
            env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=120,
        )
        out["autopilot_rc"] = proc.returncode
        try:
            out["autopilot"] = json.loads(proc.stdout)
        except Exception:
            out["autopilot_stdout"] = proc.stdout[:2000]
        ap = out.get("autopilot") or {}
        spawned_ok = any(s.get("ok") for s in (ap.get("spawned") or []))
        if not spawned_ok:
            for cl in ap.get("claims") or []:
                if cl.get("ok") and cl.get("task_id") == tid:
                    import subprocess as sp

                    sp.run(
                        [str(ROOT / "venv/bin/python3"), str(ROOT / "scripts/cursor_ops_headless_execute_one.py"), "--task-id", tid],
                        cwd=str(ROOT),
                        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
                        timeout=600,
                    )
                    break
        final = _wait_task(tid, timeout=360)
        out["final_task"] = {
            "status": final.get("status"),
            "headless_execution_host": final.get("headless_execution_host"),
            "headless_last_result": final.get("headless_last_result"),
            "worktree": final.get("worktree") or final.get("local_worktree"),
        }
        wt = final.get("worktree") or final.get("local_worktree")
        marker_glob = f"CURSOR_HA_E2E_{args.target_node.upper()}_{stamp}.md"
        if wt:
            hits = list(Path(wt).glob(f"docs/{marker_glob}"))
            out["marker_found"] = bool(hits)
            if hits:
                out["marker_content"] = hits[0].read_text(encoding="utf-8")[:200]
    print(json.dumps(out, indent=2, default=str))
    ok = out.get("ok") and (not args.run_autopilot or out.get("final_task", {}).get("headless_execution_host"))
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
