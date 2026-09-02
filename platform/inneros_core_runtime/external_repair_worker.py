"""Headless execution adapter for approved External Repair runs.

Runs provider CLIs in an explicit working directory and writes durable evidence.
No shell=True, no secret reads, and only providers already admitted by
external_repair_agent may reach this worker.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

from inneros_core_runtime import external_repair_agent
from inneros_core_runtime import provider_cli_preflight


def _codex_argv(prompt: str) -> tuple[list[str], dict[str, Any]]:
    preflight = provider_cli_preflight.codex_preflight()
    cli = str(preflight.get("cli_path") or "")
    if not preflight.get("ok") or not cli:
        raise RuntimeError(f"codex_not_ready:{preflight.get('blocker') or 'preflight_failed'}")
    return [cli, "exec", "--full-auto", prompt], preflight


def _mark_nonchargeable(run_id: str, reason: str) -> None:
    try:
        external_repair_agent._db()[external_repair_agent.RUNS_COL].update_one(
            {"run_id": run_id},
            {"$set": {"chargeable": False, "provider_preflight_blocker": reason}},
        )
    except Exception:
        pass


def _runner(run_id: str, provider: str, worktree: str, prompt: str, timeout_seconds: int) -> None:
    evidence: dict[str, Any] = {"provider_execution_started": False, "worktree": worktree}
    try:
        if provider != "codex":
            raise RuntimeError(f"provider_adapter_not_implemented:{provider}")

        try:
            argv, preflight = _codex_argv(prompt)
        except RuntimeError as exc:
            blocker = str(exc)[:500]
            _mark_nonchargeable(run_id, blocker)
            evidence.update({
                "provider_preflight": "BLOCKED",
                "provider_execution_started": False,
                "failure_class": "auth_not_ready" if "auth_not_ready" in blocker else "provider_not_ready",
                "error": blocker,
            })
            external_repair_agent.complete_external_repair_run(
                run_id,
                outcome="blocked",
                result="BLOCKED",
                evidence=evidence,
                report_to="chatgpt",
                update_task=True,
            )
            return

        evidence.update({
            "provider_preflight": "PASS",
            "provider_execution_started": True,
            "cli_path": preflight.get("cli_path"),
            "auth_ready": bool(preflight.get("auth_ready")),
        })
        external_repair_agent.checkpoint_external_repair_run(
            run_id, phase="provider_start", evidence=evidence
        )
        proc = subprocess.run(
            argv,
            cwd=worktree,
            text=True,
            capture_output=True,
            timeout=max(30, min(int(timeout_seconds or 1800), 7200)),
            env=provider_cli_preflight.provider_exec_env(),
        )
        failure_class = "" if proc.returncode == 0 else provider_cli_preflight.classify_provider_failure(proc.stdout or "", proc.stderr or "")
        if failure_class == "auth_expired":
            _mark_nonchargeable(run_id, failure_class)
        evidence.update({
            "provider_execution_finished": True,
            "returncode": proc.returncode,
            "failure_class": failure_class,
            "stdout_tail": (proc.stdout or "")[-12000:],
            "stderr_tail": (proc.stderr or "")[-6000:],
            "argv_safe": [argv[0], "exec", "--full-auto", "<prompt>"],
        })
        outcome = "completed" if proc.returncode == 0 else "blocked" if failure_class == "auth_expired" else "failed"
        result = "PASS" if proc.returncode == 0 else "BLOCKED" if failure_class == "auth_expired" else "FAIL"
        external_repair_agent.complete_external_repair_run(
            run_id,
            outcome=outcome,
            result=result,
            evidence=evidence,
            report_to="chatgpt",
            update_task=True,
        )
    except subprocess.TimeoutExpired:
        evidence.update({"provider_execution_finished": False, "error": "timeout", "timeout_seconds": timeout_seconds})
        external_repair_agent.complete_external_repair_run(run_id, outcome="failed", result="FAIL", evidence=evidence, report_to="chatgpt", update_task=True)
    except Exception as exc:
        evidence.update({"provider_execution_finished": False, "error": str(exc)[:1000]})
        external_repair_agent.complete_external_repair_run(run_id, outcome="failed", result="FAIL", evidence=evidence, report_to="chatgpt", update_task=True)


def launch(*, run_id: str, provider: str, worktree: str, prompt: str, timeout_seconds: int = 1800) -> dict[str, Any]:
    path = Path(worktree).expanduser().resolve()
    if not path.is_dir():
        return {"ok": False, "error": "worktree_not_found", "worktree": str(path)}
    thread = threading.Thread(
        target=_runner,
        kwargs={"run_id": run_id, "provider": provider, "worktree": str(path), "prompt": prompt, "timeout_seconds": timeout_seconds},
        daemon=True,
        name=f"external-repair-{provider}-{run_id[-8:]}",
    )
    thread.start()
    return {"ok": True, "run_id": run_id, "provider": provider, "worktree": str(path), "worker": thread.name, "alive": thread.is_alive()}
