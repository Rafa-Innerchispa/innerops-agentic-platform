#!/usr/bin/env python3
"""AMD-primary Cursor ops autopilot: session truth, claim, optional SDK execution.

The inbox consumer only ACKs Mongo mail; it does not run Composer. Headless execution
requires an interactive-capable plane: Private Worker heartbeat and/or Cursor SDK with
CURSOR_API_KEY. This tick runs only on the primary execution node (AMD by default).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import cursor_execution_plane as cep
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime.memory import agent_messages as am


def _hostname() -> str:
    return socket.gethostname().lower()


def _is_primary_execution_node() -> bool:
    role = (os.getenv("INNEROS_NODE_ROLE") or "").strip().lower()
    if role in {"amd", "gpu_worker", "primary"}:
        return True
    if role in {"intel", "secondary", "standby"}:
        return False
    forced = (os.getenv("INNEROS_CURSOR_EXECUTION_PRIMARY") or "").strip().lower()
    if forced in {"1", "true", "yes", "amd"}:
        return True
    if forced in {"0", "false", "intel", "secondary"}:
        return False
    return "amd" in _hostname() or "ralfiia-amd" in _hostname()


def _sdk_execute(*, prompt: str, cwd: Path, model: str) -> dict:
    api_key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "skipped": "CURSOR_API_KEY_missing"}
    try:
        from cursor_sdk import Agent  # type: ignore
    except ImportError:
        return {"ok": False, "skipped": "cursor_sdk_not_installed", "hint": "pip install cursor-sdk in platform venv"}
    try:
        result = Agent.prompt(
            prompt,
            api_key=api_key,
            model={"id": model.replace("-fast", "").replace("_", "-")},
            local={"cwd": str(cwd)},
        )
        return {
            "ok": True,
            "status": getattr(result, "status", None) or result.get("status"),
            "result": str(getattr(result, "result", None) or result.get("result") or "")[:8000],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


def _auto_claim_enabled() -> bool:
    return os.getenv("INNEROS_CURSOR_AUTO_CLAIM", "").strip().lower() in {"1", "true", "yes"}


def run(*, auto_claim: bool | None = None, execute: bool = False, limit: int = 3) -> dict:
    if auto_claim is None:
        auto_claim = _auto_claim_enabled()
    if not _is_primary_execution_node():
        return {
            "ok": True,
            "skipped": "not_primary_execution_node",
            "host": _hostname(),
            "hint": "Cursor headless autopilot runs on AMD primary only; Intel stays delivery/Mongo secondary.",
        }

    cep.register_cursor_ide_session(
        host=_hostname(),
        source="cursor_private_worker",
        identity={"mailbox": "cursor", "role": "headless_autopilot", "host": _hostname()},
    )
    consumer = cep.register_cursor_consumer_heartbeat(
        identity={"mailbox": "cursor", "host": _hostname(), "role": "inbox_consumer"},
    )
    classified = cep.classify_cursor_execution()

    out: dict = {
        "ok": True,
        "host": _hostname(),
        "primary": True,
        "classification": classified,
        "consumer": consumer,
        "auto_claim": auto_claim,
        "execute": execute,
        "pinned_model": cor.CURSOR_PINNED_MODEL,
    }

    if not auto_claim:
        out["auto_claim"] = False
        out["hint"] = "Set INNEROS_CURSOR_AUTO_CLAIM=1 to claim owner-authorized cursor ops from this tick."
        return out

    listed = cor.list_claimable_ops_tasks(limit=limit)
    tasks = listed.get("tasks") or []
    eligible = [t for t in tasks if t.get("owner_authorized")]
    if not eligible:
        out["claim"] = {"ok": True, "claimed": False, "reason": "no_owner_authorized_claimable"}
        return out

    task_id = str(eligible[0].get("task_id") or "")
    claim = cor.claim_ops_task(task_id=task_id, owner_approved=True, owner_actor="INNEROS_HEADLESS_AUTOPILOT")
    out["claim"] = claim
    if not claim.get("ok"):
        return out

    body = (
        f"HEADLESS AUTOPILOT · claim activo\n"
        f"task_id={claim.get('task_id')}\n"
        f"model={claim.get('pinned_model')}\n"
        f"worktree={claim.get('worktree')}\n"
        f"repo={claim.get('repo')}\n\n"
        f"Objective:\n{(claim.get('objective') or '')[:4000]}"
    )
    am.create_agent_message(
        from_agent="inneros",
        target_agent="cursor",
        title=f"Autopilot claim · {claim.get('task_id')}",
        body=body,
        correlation_id=str(claim.get("correlation_id") or ""),
        message_type="task",
        payload={
            "task_id": claim.get("task_id"),
            "claim_token": claim.get("claim_token"),
            "headless_autopilot": True,
            "pinned_model": claim.get("pinned_model"),
        },
        idempotency_key=f"headless-autopilot-{claim.get('task_id')}-{claim.get('claim_token')}",
    )

    if execute:
        cwd = Path(str(claim.get("worktree") or ROOT))
        prompt = (
            f"Ejecuta la tarea InnerOS ops {claim.get('task_id')} con modelo {claim.get('pinned_model')}. "
            f"Objetivo:\n{claim.get('objective')}\n"
            "Entrega evidencia: commit_sha o tests exitosos antes de marcar completed."
        )
        sdk = _sdk_execute(prompt=prompt, cwd=cwd, model=str(claim.get("pinned_model") or cor.CURSOR_PINNED_MODEL))
        out["sdk"] = sdk
        if sdk.get("ok") and claim.get("claim_token"):
            sha = ""
            try:
                import subprocess

                proc = subprocess.run(
                    ["git", "-C", str(cwd), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if proc.returncode == 0:
                    sha = proc.stdout.strip()
            except Exception:
                sha = ""
            evidence = {"notes": sdk.get("result", "")[:2000], "commit_sha": sha or None}
            if sha:
                out["complete"] = cor.complete_ops_task(
                    str(claim.get("task_id")),
                    claim_token=str(claim.get("claim_token")),
                    status="completed",
                    evidence=evidence,
                    commit_sha=sha,
                )
            else:
                out["complete"] = {
                    "ok": False,
                    "skipped": "evidence_incomplete",
                    "hint": "SDK run finished but no commit_sha; complete manually or enable git commit in agent.",
                }
    else:
        out["execution"] = {
            "mode": "claim_and_inbox_only",
            "hint": (
                "Private Worker must run Composer (this chat) or set INNEROS_CURSOR_HEADLESS_EXECUTE=1 "
                "with CURSOR_API_KEY + cursor-sdk for unattended SDK runs."
            ),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor ops headless autopilot (AMD primary)")
    parser.add_argument("--no-claim", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run Cursor SDK when CURSOR_API_KEY is set (otherwise claim + inbox only)",
    )
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    execute = args.execute or os.getenv("INNEROS_CURSOR_HEADLESS_EXECUTE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    out = run(auto_claim=not args.no_claim, execute=execute, limit=max(1, min(args.limit, 10)))
    print(json.dumps(out, indent=2, default=str))
    if out.get("skipped") == "not_primary_execution_node":
        return 0
    if not out.get("ok"):
        return 2
    classified = out.get("classification") or {}
    if classified.get("execution_classification") == "remote_inbox_only" and not execute:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
