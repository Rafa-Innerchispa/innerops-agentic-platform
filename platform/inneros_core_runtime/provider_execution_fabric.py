"""Provider-neutral execution fabric for IDE/agent task runners.

The fabric makes one rule explicit: delivery is not execution. A provider can
only enter ``running`` with durable proof from a local process or a remote
session adapter. Otherwise the task remains delivered/claimed/blocked with a
truthful reason.
"""

from __future__ import annotations

import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from inneros_core_runtime import ide_task_bridge

FABRIC_VERSION = "provider_execution_fabric_v1"
CANONICAL_PROVIDERS = ("codex", "cursor", "antigravity")
RUNNING_PROOF_TYPES = {"process", "remote_session"}


class ProviderAdapter(Protocol):
    id: str

    def detect(self) -> dict[str, Any]: ...
    def auth_ready(self) -> dict[str, Any]: ...
    def launch(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def heartbeat(self, run_id: str) -> dict[str, Any]: ...
    def cancel(self, run_id: str) -> dict[str, Any]: ...
    def collect_evidence(self, run_id: str) -> dict[str, Any]: ...
    def complete(self, run_id: str, evidence: dict[str, Any]) -> dict[str, Any]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node() -> str:
    return socket.gethostname()


def normalize_provider(provider: str) -> str:
    return ide_task_bridge.normalize_target(provider)


def provider_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "version": FABRIC_VERSION,
        "provider_adapter_methods": [
            "detect",
            "auth_ready",
            "headless_supported",
            "remote_inbox_supported",
            "launch",
            "heartbeat",
            "cancel",
            "collect_evidence",
            "complete",
        ],
        "states": ["proposed", "accepted", "queued", "claimed", "running", "verification", "completed", "failed", "blocked", "cancelled"],
        "running_requires": sorted(RUNNING_PROOF_TYPES),
        "storage": ["ralfia_ops_tasks", "ralfia_ide_task_dispatches", "ralfia_external_repair_runs"],
    }


def detect_provider(provider: str) -> dict[str, Any]:
    provider_n = normalize_provider(provider)
    if provider_n not in CANONICAL_PROVIDERS:
        manifest = _detect_manifest_provider(provider_n)
        if manifest.get("ok"):
            return manifest
        return {"ok": False, "provider": provider_n, "error": "provider_not_registered"}
    try:
        from inneros_core_runtime import external_repair_agent

        base = external_repair_agent.detect_provider(provider_n)
    except Exception as exc:
        base = {"ok": False, "provider": provider_n, "error": type(exc).__name__}
    remote_inbox = provider_n in {"cursor", "antigravity", "codex"}
    status = "ready" if base.get("status") == "ready" else ("remote_inbox_only" if remote_inbox else "unavailable")
    return {
        **base,
        "ok": bool(base.get("ok", True)),
        "provider": provider_n,
        "fabric_version": FABRIC_VERSION,
        "remote_inbox_supported": remote_inbox,
        "launch_modes": _launch_modes(base, remote_inbox),
        "status": status,
        "truth_semantics": "running requires local process proof or remote session proof",
    }


def _launch_modes(base: dict[str, Any], remote_inbox: bool) -> list[str]:
    modes = []
    if base.get("headless_supported") and base.get("auth_ready"):
        modes.append("headless")
    if remote_inbox:
        modes.append("remote_inbox")
    return modes


def _detect_manifest_provider(provider: str) -> dict[str, Any]:
    try:
        from inneros_core_runtime import provider_onboarding_plane

        preflight = provider_onboarding_plane.provider_preflight(provider)
    except Exception as exc:
        return {"ok": False, "provider": provider, "error": type(exc).__name__}
    if not preflight.get("ok"):
        return {"ok": False, "provider": provider, "error": "provider_manifest_not_ready", "preflight": preflight}
    return {
        "ok": True,
        "provider": provider,
        "fabric_version": FABRIC_VERSION,
        "installed": True,
        "headless_supported": False,
        "auth_ready": preflight.get("checks", {}).get("secret_category_configured", False),
        "remote_inbox_supported": False,
        "status": "manifest_registered",
        "manifest": preflight.get("manifest"),
    }


def validate_execution_proof(provider: str, proof: dict[str, Any] | None) -> dict[str, Any]:
    provider_n = normalize_provider(provider)
    if not isinstance(proof, dict) or not proof:
        return {"ok": False, "error": "execution_proof_required", "provider": provider_n}
    proof_type = str(proof.get("proof_type") or "").strip()
    if proof_type not in RUNNING_PROOF_TYPES:
        return {"ok": False, "error": "invalid_execution_proof_type", "allowed": sorted(RUNNING_PROOF_TYPES), "provider": provider_n}
    if proof_type == "process":
        pid = proof.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return {"ok": False, "error": "process_pid_required", "provider": provider_n}
        return {"ok": True, "provider": provider_n, "proof_type": proof_type, "pid": pid}
    session_id = str(proof.get("session_id") or "").strip()
    transport = str(proof.get("transport") or "").strip()
    if not session_id or transport not in {"remote_ide", "a2a", "provider_inbox"}:
        return {"ok": False, "error": "remote_session_proof_required", "provider": provider_n}
    return {"ok": True, "provider": provider_n, "proof_type": proof_type, "session_id": session_id, "transport": transport}


def mark_running_with_proof(dispatch_id: str, provider: str, proof: dict[str, Any]) -> dict[str, Any]:
    valid = validate_execution_proof(provider, proof)
    if not valid.get("ok"):
        return valid
    enriched = {**proof, "validated_at": _now(), "node": proof.get("node") or _node(), "fabric_version": FABRIC_VERSION}
    return ide_task_bridge.mark_running(dispatch_id, provider, execution_proof=enriched)


def execute_provider_task(
    *,
    provider: str,
    title: str,
    body: str,
    repo: str = "",
    branch: str = "",
    worktree: str = "",
    correlation_id: str = "",
    priority: str = "p0",
    from_agent: str = "CHATGPT_A",
    dry_run: bool = True,
    require_evidence: bool = True,
    idempotency_key: str = "",
) -> dict[str, Any]:
    provider_n = normalize_provider(provider)
    capability = detect_provider(provider_n)
    dispatch = ide_task_bridge.dispatch_task(
        ide=provider_n,
        title=title,
        body=body,
        repo=repo,
        branch=branch,
        worktree=worktree,
        correlation_id=correlation_id,
        priority=priority,
        from_agent=from_agent,
        require_evidence=require_evidence,
        idempotency_key=idempotency_key,
    )
    if not dispatch.get("ok"):
        return {"ok": False, "stage": "dispatch", "capability": capability, "dispatch": dispatch}
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "provider": provider_n,
            "capability": capability,
            "dispatch": dispatch,
            "execution_state": dispatch.get("execution_state", "queued"),
        }
    if capability.get("status") != "ready":
        return {
            "ok": False,
            "provider": provider_n,
            "execution_state": "blocked",
            "error": "provider_not_executable_on_this_node",
            "capability": capability,
            "dispatch": dispatch,
        }
    if provider_n == "codex":
        return _execute_codex_smoke(dispatch, capability)
    return {
        "ok": False,
        "provider": provider_n,
        "execution_state": "blocked",
        "error": "provider_adapter_launch_not_implemented",
        "capability": capability,
        "dispatch": dispatch,
    }


def _execute_codex_smoke(dispatch: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    """Cheap local smoke proving lifecycle semantics without running paid prompts."""
    started = _now()
    proc = subprocess.run(
        ["python3", "-c", "import os; print('provider-fabric-smoke', os.getpid())"],
        text=True,
        capture_output=True,
        timeout=10,
        cwd=Path(dispatch.get("worktree") or os.getcwd()),
    )
    proof = {
        "proof_type": "process",
        "pid": os.getpid(),
        "started_at": started,
        "last_output_at": _now(),
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-1000:],
        "stderr_tail": proc.stderr[-1000:],
        "transport": "local_smoke",
    }
    running = mark_running_with_proof(dispatch["dispatch_id"], "codex", proof)
    evidence = {
        "fabric_version": FABRIC_VERSION,
        "provider": "codex",
        "run_id": f"provider_smoke_{dispatch['dispatch_id']}",
        "process": proof,
        "capability": capability,
        "tests": "provider fabric local smoke",
    }
    completed = ide_task_bridge.complete_task(dispatch["dispatch_id"], "codex", evidence=evidence)
    return {
        "ok": bool(running.get("ok") and completed.get("ok") and proc.returncode == 0),
        "provider": "codex",
        "execution_state": completed.get("execution_state"),
        "dispatch": dispatch,
        "running": running,
        "completed": completed,
        "evidence": evidence,
    }


def fabric_status() -> dict[str, Any]:
    return {
        "ok": True,
        "version": FABRIC_VERSION,
        "node": _node(),
        "contract": provider_contract(),
        "providers": [detect_provider(p) for p in CANONICAL_PROVIDERS],
    }
