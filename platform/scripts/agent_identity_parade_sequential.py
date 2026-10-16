#!/usr/bin/env python3
"""Parada secuencial de identidad: un agente a la vez, Alexa dice la frase, evidencia en Mongo.

Ejecutar en Intel (orquestador):
  cd platform && PYTHONPATH=. python3 scripts/agent_identity_parade_sequential.py
"""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PARADE_PYTHON = os.getenv("PARADE_PYTHON", "")
if not PARADE_PYTHON:
    _venv_py = ROOT / "venv" / "bin" / "python3"
    PARADE_PYTHON = str(_venv_py if _venv_py.is_file() else Path(sys.executable))

from inneros_core_runtime.coordination_live import OPS_TASKS_COL, create_ops_task
from inneros_core_runtime import cursor_headless_lanes as lanes
from raphiia_openai import mongo_store

REPORT_PATH = ROOT.parent / "var" / "evidence" / "agent_identity_parade_report.json"
MAX_ATTEMPTS = 5
POLL_SEC = 2
TIMEOUT_SEC = 180

# Orden fijo (18 pasos): AG AMD → AG Intel → Codex×2×2 nodos → Cursor×2×2 → carriles A–H (AMD)
STEPS: list[dict[str, Any]] = [
    {"step": "01", "kind": "interactive", "provider": "antigravity", "node": "amd", "phrase": "Hola, soy Antigravity AMD."},
    {"step": "02", "kind": "interactive", "provider": "antigravity", "node": "intel", "phrase": "Hola, soy Antigravity Intel."},
    {"step": "03", "kind": "interactive", "provider": "codex", "node": "amd", "phrase": "Hola, soy Codex AMD, agente uno."},
    {"step": "04", "kind": "interactive", "provider": "codex", "node": "amd", "phrase": "Hola, soy Codex AMD, agente dos."},
    {"step": "05", "kind": "interactive", "provider": "codex", "node": "intel", "phrase": "Hola, soy Codex Intel, agente uno."},
    {"step": "06", "kind": "interactive", "provider": "codex", "node": "intel", "phrase": "Hola, soy Codex Intel, agente dos."},
    {"step": "07", "kind": "interactive", "provider": "cursor", "node": "amd", "phrase": "Hola, soy Cursor AMD, agente uno."},
    {"step": "08", "kind": "interactive", "provider": "cursor", "node": "amd", "phrase": "Hola, soy Cursor AMD, agente dos."},
    {"step": "09", "kind": "interactive", "provider": "cursor", "node": "intel", "phrase": "Hola, soy Cursor Intel, agente uno."},
    {"step": "10", "kind": "interactive", "provider": "cursor", "node": "intel", "phrase": "Hola, soy Cursor Intel, agente dos."},
]
for letter in "ABCDEFGH":
    STEPS.append(
        {
            "step": f"{11 + ord(letter) - ord('A'):02d}",
            "kind": "carril",
            "provider": "dev_swarm",
            "node": "amd",
            "carril": letter,
            "phrase": f"Hola, soy carril {letter} AMD.",
        }
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_role() -> str:
    return lanes.node_role()


def _host_matches_node(host: str, node: str) -> bool:
    h = (host or "").lower()
    if node == "amd":
        return "amd" in h or "ralfiia-amd" in h
    return "intel" in h or "ralphi-ia" in h or "-ia-" in h


def _title_for(step: dict[str, Any]) -> str:
    if step["kind"] == "carril":
        return f"[Carril {step['carril']} · interno] Parada identidad {step['step']}"
    prov = step["provider"].upper()
    return f"[Competencia/Externo/{prov}] Parada identidad {step['step']}"


def _reset_task(tid: str) -> None:
    db = mongo_store.get_db()
    db[OPS_TASKS_COL].update_one(
        {"task_id": tid},
        {
            "$set": {"status": "queued", "updated_at": _now()},
            "$unset": {
                "claim_token": "",
                "claimed_at": "",
                "provider_execution_started_at": "",
                "provider_execution_host": "",
                "competition_spawn_pid": "",
                "competition_log_path": "",
                "candidate_evidence": "",
            },
        },
    )


def _create_step_task(step: dict[str, Any], attempt: int) -> dict[str, Any]:
    prov = step.get("provider") or "dev_swarm"
    title = _title_for(step)
    idem = f"parade_identity_{step['step']}_{step.get('provider') or step.get('carril')}_{attempt}_{int(time.time())}"
    return create_ops_task(
        prov,
        title,
        objective=step["phrase"],
        from_agent="PARADE_HARNESS",
        idempotency_key=idem,
        do_not_auto_dispatch=True,
        payload={
            "parade_phrase": step["phrase"],
            "parade_step": step["step"],
            "preferred_execution_host": step["node"],
            "execution_host": step["node"],
        },
    )


def _run_remote(node: str, snippet: str) -> dict[str, Any]:
    role = _local_role()
    if node == role:
        proc = subprocess.run(
            [PARADE_PYTHON, "-c", snippet],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
        out = (proc.stdout or "").strip()
        try:
            data = json.loads(out.splitlines()[-1]) if out else {}
        except json.JSONDecodeError:
            data = {"raw": out[:2000], "stderr": (proc.stderr or "")[:1000]}
        data["_returncode"] = proc.returncode
        return data
    host = os.getenv("PARADE_SSH_AMD" if node == "amd" else "PARADE_SSH_INTEL", "192.168.1.5" if node == "amd" else "192.168.1.4")
    payload = base64.b64encode(snippet.encode("utf-8")).decode("ascii")
    cmd = (
        f"cd {ROOT} && PYTHONPATH=. {PARADE_PYTHON} -c "
        f"\"import base64; exec(base64.b64decode('{payload}').decode('utf-8'), {{'__name__': '__main__'}})\""
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", f"rlopez@{host}", cmd],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SEC + 30,
    )
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else {}
    except json.JSONDecodeError:
        data = {"raw": out[:2000], "stderr": (proc.stderr or "")[:1000]}
    data["_ssh_rc"] = proc.returncode
    return data


def _dispatch_interactive(node: str, tid: str, provider: str) -> dict[str, Any]:
    snippet = f"""
import json
from inneros_core_runtime import interactive_ops_orchestrator as orch
from inneros_core_runtime import cursor_headless_lanes as lanes
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

tid = {tid!r}
prov = {provider!r}
task = mongo_store.get_db()[OPS_TASKS_COL].find_one({{"task_id": tid}}, {{"_id": 0}}) or {{}}
from inneros_core_runtime import interactive_provider_lanes as ipl
if prov == "cursor":
    allowed, reason = lanes.should_this_node_run_task(task)
else:
    allowed, reason = ipl.should_this_node_run_task(prov, task)
if not allowed:
    print(json.dumps({{"ok": False, "error": "wrong_node", "reason": reason, "role": lanes.node_role()}}))
else:
    out = orch.owner_order_execute(prov, task_id=tid, owner_actor="PARADE", channel="parade")
    print(json.dumps(out, default=str))
"""
    return _run_remote(node, snippet)


def _dispatch_carril(node: str, tid: str) -> dict[str, Any]:
    snippet = f"""
import json
from inneros_core_runtime import competition_lane_dispatch as cld
out = cld.execute_competition_task({tid!r})
print(json.dumps(out, default=str))
"""
    return _run_remote(node, snippet)


def _wait_task(tid: str, *, expect_interactive: bool) -> dict[str, Any]:
    db = mongo_store.get_db()
    deadline = time.time() + TIMEOUT_SEC
    last: dict[str, Any] = {}
    while time.time() < deadline:
        task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
        last = task
        st = str(task.get("status") or "").lower()
        if expect_interactive and st in {"completed", "failed", "blocked"}:
            return task
        if not expect_interactive and st in {"verification", "completed", "failed", "blocked"}:
            if task.get("candidate_evidence") or st == "completed":
                return task
        pid = task.get("competition_spawn_pid")
        if pid and not _pid_alive(int(pid)):
            time.sleep(POLL_SEC)
            task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
            if task.get("candidate_evidence") or str(task.get("status")).lower() in {"completed", "failed", "verification"}:
                return task
        time.sleep(POLL_SEC)
    return last


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_competition_log(task: dict[str, Any]) -> str:
    path = str(task.get("competition_log_path") or "")
    if not path:
        return ""
    local = Path(path)
    if local.is_file():
        return local.read_text(errors="replace")
    host = str(task.get("provider_execution_host") or task.get("claim_host") or "")
    node = "amd" if _host_matches_node(host, "amd") else "intel"
    ssh_host = os.getenv("PARADE_SSH_AMD" if node == "amd" else "PARADE_SSH_INTEL", "192.168.1.5" if node == "amd" else "192.168.1.4")
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"rlopez@{ssh_host}", f"tail -c 3500 {path}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (proc.stdout or proc.stderr or "")[-3500:]


def _verify(step: dict[str, Any], task: dict[str, Any]) -> tuple[bool, str]:
    st = str(task.get("status") or "").lower()
    if st in {"failed", "blocked"}:
        return False, f"status={st}"
    ev = task.get("candidate_evidence") or task.get("completion_evidence") or task.get("evidence") or {}
    if isinstance(ev, list):
        ev = ev[-1] if ev else {}
    if not isinstance(ev, dict):
        ev = {}
    host = str(ev.get("execution_host") or task.get("provider_execution_host") or task.get("claim_host") or "")
    if not _host_matches_node(host, step["node"]):
        return False, f"host_mismatch:{host}"
    phrase = step["phrase"]
    spoken = str(ev.get("spoken_phrase") or "")
    ha = ev.get("ha_response")
    if spoken and spoken.strip() != phrase.strip():
        return False, f"phrase_mismatch:{spoken}"
    if isinstance(ha, dict) and ha.get("ok") is False:
        return False, f"ha_failed:{ha.get('error')}"
    log_tail = _read_competition_log(task)
    if log_tail and phrase not in log_tail and st != "completed":
        if '"ok": true' not in log_tail.lower():
            return False, "log_missing_ok"
    if step["kind"] == "interactive" and st != "completed":
        if log_tail and phrase in log_tail and '"ha": {"ok": true' in log_tail.replace(" ", ""):
            return True, "ok_from_competition_log"
        return False, f"expected_completed_got_{st}"
    if step["kind"] == "carril" and st not in {"verification", "completed"}:
        return False, f"expected_verification_got_{st}"
    ha_ok = isinstance(ha, dict) and ha.get("ok") is True
    if not ha_ok and st == "completed":
        # Some completions nest ha inside ha_response service call
        if isinstance(ha, dict) and ha.get("status") == "sent":
            ha_ok = True
    if not ha_ok:
        return False, "ha_not_ok"
    return True, "ok"


def _try_fix(step: dict[str, Any], task: dict[str, Any], reason: str) -> str:
    if "ha_" in reason or "ha_not" in reason:
        try:
            from raphiia_openai import homeassistant_client as ha

            ping = ha.ping()
            if not ping.get("ok"):
                return "ha_ping_still_failing"
        except Exception as exc:
            return f"ha_exception:{exc}"
    if "wrong_node" in reason or "host_mismatch" in reason:
        return "retry_on_forced_node"
    if "worktree" in reason:
        return "drop_repo_on_recreate"
    return "generic_retry"


def run_parade() -> dict[str, Any]:
    report: dict[str, Any] = {
        "started_at": _now(),
        "orchestrator_host": socket.gethostname(),
        "steps": [],
        "ok": True,
    }
    start_from = (os.getenv("PARADE_FROM_STEP") or "").strip()
    for step in STEPS:
        if start_from and step["step"] < start_from:
            continue
        entry: dict[str, Any] = {"step": step["step"], "phrase": step["phrase"], "node": step["node"], "attempts": []}
        success = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            att: dict[str, Any] = {"attempt": attempt, "started_at": _now()}
            created = _create_step_task(step, attempt)
            att["create"] = created
            if not created.get("ok") and not created.get("task_id"):
                att["error"] = "create_failed"
                entry["attempts"].append(att)
                time.sleep(3)
                continue
            tid = str(created.get("task_id") or "")
            att["task_id"] = tid
            if step["kind"] == "interactive":
                disp = _dispatch_interactive(step["node"], tid, step["provider"])
            else:
                disp = _dispatch_carril(step["node"], tid)
            att["dispatch"] = disp
            task = _wait_task(tid, expect_interactive=(step["kind"] == "interactive"))
            att["final_status"] = task.get("status")
            att["task_snapshot"] = {
                "provider_execution_host": task.get("provider_execution_host"),
                "competition_log_path": task.get("competition_log_path"),
            }
            ok, reason = _verify(step, task)
            att["verify_ok"] = ok
            att["verify_reason"] = reason
            entry["attempts"].append(att)
            if ok:
                success = True
                entry["task_id"] = tid
                entry["ok"] = True
                break
            fix = _try_fix(step, task, reason)
            att["fix_strategy"] = fix
            if tid:
                _reset_task(tid)
            time.sleep(4)
        if not success:
            entry["ok"] = False
            report["ok"] = False
            report["failed_at_step"] = step["step"]
            report["steps"].append(entry)
            break
        report["steps"].append(entry)
    report["finished_at"] = _now()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    raise SystemExit(0 if run_parade().get("ok") else 1)
