#!/usr/bin/env python3
"""Smoke cruzado sin créditos IDE: competencia Alexa (externos + 8 carriles) con nonce."""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parent / "var" / "evidence" / "coordination_cross_test_report.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXTERNALS = [
    ("antigravity", "amd", "01"),
    ("antigravity", "intel", "02"),
    ("codex", "amd", "03"),
    ("codex", "intel", "04"),
    ("cursor", "amd", "05"),
    ("cursor", "intel", "06"),
]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_node() -> str:
    import socket

    h = socket.gethostname().lower()
    if "amd" in h or "ralfiia-amd" in h:
        return "amd"
    return "intel"


def _ssh(node: str, remote_cmd: str, timeout: int = 180) -> dict:
    if node == _local_node():
        proc = subprocess.run(remote_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    else:
        host = "192.168.1.5" if node == "amd" else "192.168.1.4"
        cmd = ["ssh", "-o", "BatchMode=yes", f"rlopez@{host}", remote_cmd]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "").strip()
    parsed = None
    if out:
        try:
            parsed = json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            parsed = None
    return {"returncode": proc.returncode, "json": parsed, "stdout": out[-1500:], "stderr": (proc.stderr or "")[-500:]}


def _run_competition_on_node(node: str, task_id: str) -> dict:
    remote = (
        f"cd {ROOT} && PYTHONPATH=. venv/bin/python3 scripts/competition_execute_one.py --task-id {task_id}"
    )
    return _ssh(node, remote)


def _owner_order_on_node(node: str, provider: str, task_id: str) -> dict:
    py = (
        "import json; from inneros_core_runtime import interactive_ops_orchestrator as o; "
        f"print(json.dumps(o.owner_order_execute({provider!r}, task_id={task_id!r}, owner_actor='COORD_AUTO'), default=str))"
    )
    remote = f"cd {ROOT} && PYTHONPATH=. venv/bin/python3 -c {json.dumps(py)}"
    return _ssh(node, remote)


def main() -> int:
    from inneros_core_runtime import coordination_live as cl

    report: dict = {"ok": True, "started_at": _utc(), "externals": [], "carriles": []}

    for provider, node, step in EXTERNALS:
        nonce = secrets.token_hex(3)
        phrase = f"Hola, soy {provider} {node.upper()} nonce {nonce}"
        cid = f"cross-smoke-{step}-{provider}-{nonce}-{int(time.time())}"
        title = f"[Competencia/Externo/{provider.upper()}] cross-smoke {step}"
        cr = cl.create_ops_task(
            provider,
            title,
            objective=phrase,
            correlation_id=cid,
            idempotency_key=cid,
            do_not_auto_dispatch=True,
            payload={
                "parade_phrase": phrase,
                "parade_step": step,
                "preferred_execution_host": node,
                "nonce": nonce,
            },
        )
        tid = str(cr.get("task_id") or "")
        entry = {"step": step, "provider": provider, "node": node, "task_id": tid, "nonce": nonce, "create_ok": cr.get("ok")}
        if not tid:
            entry["ok"] = False
            report["externals"].append(entry)
            report["ok"] = False
            continue
        time.sleep(1)
        order = _owner_order_on_node(node, provider, tid)
        entry["owner_order"] = order
        time.sleep(8)
        exec_out = _run_competition_on_node(node, tid)
        entry["competition"] = exec_out
        run = (exec_out.get("json") or {}).get("run") or {}
        stdout = run.get("stdout_json") if isinstance(run, dict) else {}
        spoken = str((stdout or {}).get("phrase") or "")
        entry["ok"] = bool(exec_out.get("returncode") == 0 and nonce in spoken)
        if not entry["ok"]:
            report["ok"] = False
        report["externals"].append(entry)

    for letter in "ABCDEFGH":
        nonce = secrets.token_hex(3)
        phrase = f"Carril {letter} nonce {nonce}"
        cid = f"cross-carril-{letter}-{nonce}-{int(time.time())}"
        cr = cl.create_ops_task(
            "dev_swarm",
            f"[Carril {letter} · interno] cross-smoke",
            objective=phrase,
            correlation_id=cid,
            idempotency_key=cid,
            do_not_auto_dispatch=True,
            payload={"parade_phrase": phrase, "parade_step": f"11-{letter}", "nonce": nonce},
        )
        tid = str(cr.get("task_id") or "")
        entry = {"carril": letter, "task_id": tid, "nonce": nonce, "create_ok": cr.get("ok")}
        if tid:
            ex = _run_competition_on_node("amd", tid)
            entry["competition"] = ex
            run = (ex.get("json") or {}).get("run") or {}
            stdout = run.get("stdout_json") if isinstance(run, dict) else {}
            spoken = str((stdout or {}).get("phrase") or "")
            entry["ok"] = bool(ex.get("returncode") == 0 and nonce in spoken)
        else:
            entry["ok"] = False
        if not entry.get("ok"):
            report["ok"] = False
        report["carriles"].append(entry)

    report["finished_at"] = _utc()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "externals_ok": sum(1 for x in report["externals"] if x.get("ok")), "carriles_ok": sum(1 for x in report["carriles"] if x.get("ok"))}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
