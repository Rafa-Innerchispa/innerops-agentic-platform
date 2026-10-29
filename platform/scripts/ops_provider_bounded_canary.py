#!/usr/bin/env python3
"""Innocuous Codex/Antigravity bounded canaries: claim → spawn or inline exec → receipt."""
from __future__ import annotations

import argparse
import json
import os
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
MARKERS = {
    "codex": "docs/CODEX_CANARY.md",
    "antigravity": "docs/ANTIGRAVITY_CANARY.md",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_id(prefix: str) -> str:
    return f"ops_{prefix}{uuid.uuid4().hex[:10]}"


def _create_task(*, provider: str, correlation_id: str, repo: str) -> dict[str, Any]:
    from inneros_core_runtime import coordination_live as cl

    marker = MARKERS[provider]
    objective = (
        f"[{provider}_canary] Editar solo {marker} en worktree aislado. "
        "Sin producción, push ni secretos. Receipt = commit nuevo + unittest canary exit 0."
    )
    return cl.create_ops_task(
        assignee=provider,
        title=f"[provider_canary] {provider} bounded innocuous",
        correlation_id=correlation_id,
        repo=repo,
        objective=objective,
        task_class="coding",
        execution_lane=f"{provider}_interactive",
        preferred_provider=provider,
        payload={"provider_canary": provider, "suppress_owner_whatsapp_auth": True},
        idempotency_key=f"{correlation_id}|{provider}",
    )


def _authorize(task_id: str) -> None:
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    mongo_store.get_db()[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {
            "$set": {
                "owner_authorized_at": _utc(),
                "owner_actor": os.getenv("RALFIA_OWNER_ID") or "INNEROS_OPS_CANARY",
                "updated_at": _utc(),
            }
        },
    )


def _run_provider(
    provider: str,
    *,
    correlation_id: str,
    repo: str,
    mode: str,
    dry_run: bool,
) -> dict[str, Any]:
    if mode == "inline":
        os.environ["INNEROS_CODEX_SPAWN_ON_CLAIM"] = "0"
        os.environ["INNEROS_ANTIGRAVITY_SPAWN_ON_CLAIM"] = "0"
    elif mode == "spawn":
        os.environ["INNEROS_CODEX_SPAWN_ON_CLAIM"] = "1"
        os.environ["INNEROS_ANTIGRAVITY_SPAWN_ON_CLAIM"] = "1"
    from inneros_core_runtime import interactive_ops_runner as ior
    from inneros_core_runtime import interactive_provider_bounded_executor as ipbe
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    if dry_run:
        return {"ok": True, "dry_run": True, "provider": provider, "marker": MARKERS[provider]}

    created = _create_task(provider=provider, correlation_id=correlation_id, repo=repo)
    if not created.get("ok"):
        return {"ok": False, "provider": provider, "stage": "create", "detail": created}
    tid = str(created.get("task_id") or "")
    _authorize(tid)
    claim = ior.claim_ops_task(provider, task_id=tid, owner_approved=True, owner_actor="INNEROS_OPS_CANARY")
    if not claim.get("ok"):
        return {"ok": False, "provider": provider, "task_id": tid, "stage": "claim", "detail": claim}

    exec_out: dict[str, Any]
    spawn: dict[str, Any] | None = None
    if mode == "spawn":
        if provider == "codex":
            from inneros_core_runtime import codex_headless_dispatch as dispatch

            spawn = dispatch.spawn_headless_execute(tid, force_retry=True)
        else:
            from inneros_core_runtime import antigravity_headless_dispatch as dispatch

            spawn = dispatch.spawn_headless_execute(tid, force_retry=True)
        if not spawn.get("ok"):
            return {"ok": False, "provider": provider, "task_id": tid, "stage": "spawn", "detail": spawn}
        log_path = Path(str(spawn.get("log_path") or ""))
        deadline = time.time() + int(os.getenv("INNEROS_CANARY_SPAWN_TIMEOUT", "180"))
        task_doc: dict[str, Any] = {}
        while time.time() < deadline:
            task_doc = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
            if str(task_doc.get("status") or "") in {"completed", "failed", "blocked"}:
                break
            if log_path.is_file() and log_path.stat().st_size > 0 and not str(task_doc.get("status") or "").endswith("progress"):
                time.sleep(2)
                task_doc = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
                if str(task_doc.get("status") or "") in {"completed", "failed", "blocked"}:
                    break
            time.sleep(2)
        exec_out = {
            "ok": str(task_doc.get("status") or "") == "completed",
            "spawn": spawn,
            "terminal_status": task_doc.get("status"),
            "evidence": task_doc.get("evidence") or task_doc.get("candidate_evidence"),
            "log_path": str(log_path) if log_path else None,
        }
    else:
        exec_out = ipbe.execute_claimed_task(tid, provider)
    return {
        "ok": bool(exec_out.get("ok")),
        "provider": provider,
        "task_id": tid,
        "claim": claim,
        "execution": exec_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--correlation-id", default=f"ops-canary-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--providers", default="codex,antigravity")
    parser.add_argument("--mode", choices=("inline", "spawn"), default="inline")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    report: dict[str, Any] = {
        "ok": True,
        "generated_at": _utc(),
        "correlation_id": args.correlation_id,
        "mode": args.mode,
        "host": os.uname().nodename,
        "platform_root": str(ROOT),
        "results": [],
    }
    for prov in providers:
        if prov not in MARKERS:
            report["results"].append({"ok": False, "provider": prov, "error": "unknown_provider"})
            report["ok"] = False
            continue
        row = _run_provider(
            prov,
            correlation_id=args.correlation_id,
            repo=args.repo,
            mode=args.mode,
            dry_run=args.dry_run,
        )
        report["results"].append(row)
        if not row.get("ok"):
            report["ok"] = False

    out_path = ROOT.parent / "var" / "evidence" / f"ops_provider_bounded_canary_{args.correlation_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({**report, "path": str(out_path)}, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
