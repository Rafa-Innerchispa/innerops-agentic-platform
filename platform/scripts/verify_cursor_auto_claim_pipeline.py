#!/usr/bin/env python3
"""Verify Cursor auto-claim pipeline (timers, admission, peer obs, models)."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    from inneros_core_runtime.agents import ag41_peer_ops_executor as ag41
    from inneros_core_runtime import cursor_api_credentials as cac
    from inneros_core_runtime import cursor_headless_lanes as lanes
    from inneros_core_runtime import ops_auto_claim_admission as admission
    from raphiia_openai import mongo_store

    report: dict = {"ok": True, "generated_at": _utc(), "host": lanes.hostname(), "checks": []}

    def check(name: str, passed: bool, **extra):
        report["checks"].append({"name": name, "ok": passed, **extra})
        if not passed:
            report["ok"] = False

    role = lanes.node_role()
    check("temporal_port_7233", _port_open(7233))
    check("node_role", role in {"amd", "intel"}, role=role)
    check("cursor_api_key", bool(cac.cursor_api_key_status().get("present")))
    check("ha_execution_node", lanes.is_ha_execution_node())
    ls = lanes.lane_status()
    check("lane_status", bool(ls.get("ok")), lanes=ls)

    for node in ("amd", "intel"):
        snap = ag41.peer_observability_snapshot(node)
        check(f"peer_observability_{node}", bool(snap.get("ok")), error=snap.get("error"))

    import urllib.request

    def _http_json(url: str, data: bytes | None = None, timeout: int = 30) -> dict:
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    vllm_url = "http://127.0.0.1:8000/v1/chat/completions" if role == "amd" else "http://100.72.153.124:8000/v1/chat/completions"
    try:
        body = json.dumps(
            {
                "model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
                "messages": [{"role": "user", "content": "Say PING only."}],
                "max_tokens": 8,
                "temperature": 0,
            }
        ).encode()
        vllm = _http_json(vllm_url, body, timeout=45)
        vtxt = str(((vllm.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        check("vllm_chat_completion", bool(vtxt.strip()), snippet=vtxt[:60], url=vllm_url)
    except Exception as exc:
        check("vllm_chat_completion", False, error=type(exc).__name__, url=vllm_url)

    ollama_url = "http://127.0.0.1:11434/api/generate" if role == "intel" else "http://100.94.99.12:11434/api/generate"
    try:
        ob = json.dumps({"model": "qwen2.5-coder:7b", "prompt": "Say PING only.", "stream": False}).encode()
        intel = _http_json(ollama_url, ob, timeout=60)
        check("ollama_intel_generate", bool(str(intel.get("response") or "").strip()), snippet=str(intel.get("response") or "")[:60], url=ollama_url)
    except Exception as exc:
        check("ollama_intel_generate", False, error=type(exc).__name__, url=ollama_url)

    timers = subprocess.run(
        ["systemctl", "--user", "is-active", "inneros-cursor-headless-autopilot.timer"],
        capture_output=True,
        text=True,
    )
    check("autopilot_timer_active", timers.stdout.strip() == "active", detail=timers.stdout.strip())

    db = mongo_store.get_db()
    sample = list(
        db.ralfia_ops_tasks.find(
            {"assignee": "cursor", "status": {"$in": ["awaiting_cursor_claim", "queued", "waiting_for_binding"]}},
            {"_id": 0, "task_id": 1, "status": 1, "owner_authorized_at": 1},
        ).limit(5)
    )
    adm = admission.pending_admission_summary(sample, provider="cursor", ready=bool(ls.get("available_slots")))
    report["admission_sample"] = adm

    out = ROOT.parent / "var" / "evidence" / "cursor_auto_claim_pipeline_verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "path": str(out), "checks": len(report["checks"])}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
