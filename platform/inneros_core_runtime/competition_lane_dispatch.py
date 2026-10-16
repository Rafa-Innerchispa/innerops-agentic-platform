"""Competition Alexa lane: run entry script and close ops task with HA evidence."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

ROOT = Path(__file__).resolve().parents[1]

_CARRIL_RE = re.compile(r"\[Carril\s+([A-D])\s*·\s*interno\]", re.I)
_EXT_RE = re.compile(r"\[Competencia/Externo/([A-Z]+)\]", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def competition_entry_for_task(task: dict[str, Any]) -> Path | None:
    title = str(task.get("title") or "")
    m = _CARRIL_RE.search(title)
    if m:
        return ROOT / "competition" / "entries" / f"carril_{m.group(1).lower()}.py"
    m = _EXT_RE.search(title)
    if m:
        prov = m.group(1).lower()
        if prov in {"cursor", "codex", "antigravity"}:
            return ROOT / "competition" / "entries" / f"{prov}.py"
    return None


def is_competition_task(task: dict[str, Any]) -> bool:
    return competition_entry_for_task(task) is not None


def _run_entry(entry: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, str(entry)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stdout = (proc.stdout or "").strip()
    parsed: dict[str, Any] = {}
    if stdout:
        try:
            parsed = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            parsed = {"raw_stdout": stdout[:2000]}
    ok_flag = parsed.get("ok") if isinstance(parsed, dict) and "ok" in parsed else (proc.returncode == 0)
    return {
        "ok": proc.returncode == 0 and bool(ok_flag),
        "returncode": proc.returncode,
        "stdout_json": parsed,
        "stderr": (proc.stderr or "")[:2000],
    }


def execute_competition_task(task_id: str) -> dict[str, Any]:
    tid = (task_id or "").strip()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    entry = competition_entry_for_task(task)
    if not entry or not entry.is_file():
        return {"ok": False, "error": "not_competition_task", "task_id": tid}

    run = _run_entry(entry)
    stdout_json = run.get("stdout_json") if isinstance(run.get("stdout_json"), dict) else {}
    ha = stdout_json.get("ha")
    evidence = {
        "notes": f"Competition entry {entry.name} ok={run.get('ok')}",
        "ha_response": ha or stdout_json,
        "test_results": {"ok": run.get("ok"), "exit_code": 0 if run.get("ok") else 1},
        "competition_entry": str(entry.relative_to(ROOT)),
        "execution_host": __import__("socket").gethostname(),
    }

    assignee = str(task.get("assignee") or task.get("preferred_provider") or "").strip().lower()
    claim_token = str(task.get("claim_token") or "")

    if assignee in {"cursor", "codex", "antigravity", "gemini"} and claim_token:
        from inneros_core_runtime import interactive_ops_runner as ior

        done = ior.complete_ops_task(
            assignee,
            tid,
            claim_token=claim_token,
            status="completed",
            evidence=evidence,
        )
        return {"ok": bool(run.get("ok") and done.get("ok")), "task_id": tid, "run": run, "complete": done}

    if assignee == "dev_swarm" or "carril" in str(task.get("title") or "").lower():
        from inneros_core_runtime import durable_coordination_spine

        temporal = durable_coordination_spine.signal_task_workflow(
            tid,
            "cursor_execution_complete",
            {"submitted": True, "status": "completed", "evidence": evidence, "competition_lane": True},
        )
        now = _now()
        db[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {
                "$set": {
                    "status": "verification",
                    "updated_at": now,
                    "candidate_evidence": evidence,
                    "competition_executed_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        return {"ok": bool(run.get("ok")), "task_id": tid, "run": run, "temporal": temporal}

    return {"ok": False, "error": "unsupported_assignee", "assignee": assignee, "run": run}


def spawn_competition_execute(task_id: str) -> dict[str, Any]:
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    script = ROOT / "scripts" / "competition_execute_one.py"
    if not script.is_file():
        return {"ok": False, "error": "worker_script_missing", "path": str(script)}
    log_dir = ROOT.parent / "var" / "evidence" / "competition"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = _now().replace(":", "")
    log_path = log_dir / f"{tid.replace('/', '_')}-{safe_ts}.log"
    proc = subprocess.Popen(
        [sys.executable, str(script), "--task-id", tid],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=log_path.open("w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    mongo_store.get_db()[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {"$set": {"competition_spawn_pid": proc.pid, "competition_log_path": str(log_path), "updated_at": _now()}},
    )
    return {"ok": True, "task_id": tid, "pid": proc.pid, "log_path": str(log_path)}


def maybe_spawn_after_claim(task: dict[str, Any]) -> dict[str, Any] | None:
    if not is_competition_task(task):
        return None
    prov = str(task.get("assignee") or task.get("preferred_provider") or "").lower()
    if prov == "cursor":
        return None
    return spawn_competition_execute(str(task.get("task_id") or ""))
