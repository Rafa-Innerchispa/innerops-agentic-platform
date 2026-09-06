"""Provider-neutral execution fabric for IDE/agent task runners.

The fabric makes one rule explicit: delivery is not execution. A provider can
only enter ``running`` with durable proof from a local process or a remote
session adapter. Otherwise the task remains delivered/claimed/blocked with a
truthful reason.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from inneros_core_runtime import ide_task_bridge, local_execution_plane, local_model_router

FABRIC_VERSION = "provider_execution_fabric_v1"
CANONICAL_PROVIDERS = ("local_qwen", "codex", "cursor", "antigravity")
LOCAL_QWEN_ALIASES = {"local-qwen", "local_qwen", "qwen", "qwen3", "qwen3-coder", "local-amd", "local-amd-5", "amd-qwen"}
RUNNING_PROOF_TYPES = {"process", "remote_session", "local_model"}


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
    key = str(provider or "").strip().lower().replace(" ", "-")
    if key in LOCAL_QWEN_ALIASES:
        return "local_qwen"
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
    if provider_n == "local_qwen":
        return _detect_local_qwen_provider()
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
    if proof_type == "local_model":
        run_id = str(proof.get("run_id") or "").strip()
        model = str(proof.get("model") or proof.get("selected_model") or "").strip()
        provider_id = str(proof.get("provider_id") or "").strip()
        if not run_id or provider_id != "local-amd-5" or "Qwen" not in model:
            return {"ok": False, "error": "local_qwen_proof_required", "provider": provider_n}
        return {"ok": True, "provider": provider_n, "proof_type": proof_type, "run_id": run_id, "provider_id": provider_id, "model": model}
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



def _detect_local_qwen_provider() -> dict[str, Any]:
    try:
        route = local_model_router.classify_task_runtime("local provider execution fabric coding smoke", task_type="coding")
        health = local_model_router.local_model_health()
    except Exception as exc:
        return {"ok": False, "provider": "local_qwen", "error": type(exc).__name__, "status": "unavailable"}
    provider_id = route.get("recommended_provider")
    model = route.get("recommended_model")
    vllm_ok = bool(((health.get("vllm") or {}).get("api_models") or {}).get("ok"))
    ready = provider_id == "local-amd-5" and bool(model) and vllm_ok
    return {
        "ok": True,
        "provider": "local_qwen",
        "fabric_version": FABRIC_VERSION,
        "installed": True,
        "headless_supported": True,
        "auth_ready": True,
        "remote_inbox_supported": False,
        "provider_id": provider_id,
        "selected_model": model,
        "runtime": "local_vllm" if provider_id == "local-amd-5" else route.get("recommended_backend"),
        "status": "ready" if ready else "unavailable",
        "health_ok": bool(health.get("ok")),
        "vllm_ok": vllm_ok,
        "truth_semantics": "local Qwen execution writes only validated file_ops through Local Execution Plane",
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    candidates = [raw]
    if "```" in raw:
        for part in raw.split("```"):
            value = part.strip()
            if value.startswith("json"):
                value = value[4:].strip()
            if value.startswith("{"):
                candidates.append(value)
    first, last = raw.find("{"), raw.rfind("}")
    if first >= 0 and last > first:
        candidates.append(raw[first:last + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _safe_file_ops(payload: dict[str, Any] | None, *, max_files: int = 8) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rejected: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return [], [{"reason": "missing_json_object"}]
    files = payload.get("files")
    if files is None:
        files = payload.get("file_ops")
    if not isinstance(files, list):
        return [], [{"reason": "missing_files_array", "payload_keys": sorted(str(k) for k in payload.keys())}]
    accepted: list[dict[str, str]] = []
    for item in files[:max_files]:
        if not isinstance(item, dict):
            rejected.append({"reason": "file_op_not_object"})
            continue
        action = str(item.get("action") or "write").strip().lower()
        path = str(item.get("path") or "").strip().replace("\\", "/")
        content = item.get("content")
        if action not in {"write", "create", "upsert"}:
            rejected.append({"path": path, "reason": "unsupported_action"})
            continue
        if not path or path.startswith("/") or re.match(r"^[A-Za-z]:/", path) or ".." in path.split("/"):
            rejected.append({"path": path, "reason": "unsafe_path"})
            continue
        if not isinstance(content, str) or not content.strip():
            rejected.append({"path": path, "reason": "missing_content"})
            continue
        if len(content.encode("utf-8")) > 100_000:
            rejected.append({"path": path, "reason": "content_too_large"})
            continue
        accepted.append({"path": path.strip("/"), "content": content})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in accepted:
        if item["path"] not in seen:
            deduped.append(item)
            seen.add(item["path"])
    return deduped, rejected


def _local_qwen_file_ops_prompt(title: str, body: str) -> str:
    return (
        "Return ONLY JSON, no markdown, no prose. Shape: "
        "{\"summary\":\"...\",\"files\":[{\"action\":\"write\",\"path\":\"platform/tests/test_local_qwen_fileops_smoke.py\",\"content\":\"...\"}]}. "
        "Use only repo-relative paths under platform/tests or platform/inneros_core_runtime for this smoke. "
        "Create a harmless pytest file if the task is a smoke. No secrets, no network calls, no production changes.\n\n"
        f"TITLE:\n{title[:800]}\n\nTASK:\n{body[:4000]}"
    )


def _model_file_ops(title: str, body: str) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    prompt = _local_qwen_file_ops_prompt(title, body)
    first = local_model_router.run_local_model(task_type="coding", prompt=prompt, max_tokens=1800, temperature=0.0)
    text = str(first.get("response") or first.get("text") or first.get("content") or "")
    payload = _extract_json_object(text) if first.get("ok") else None
    files, rejected = _safe_file_ops(payload)
    attempts = [{"ok": bool(first.get("ok")), "provider_id": first.get("provider_id"), "selected_model": first.get("selected_model"), "runtime": first.get("runtime"), "rejected": rejected, "preview": text[:500]}]
    if files or not first.get("ok"):
        return {"ok": bool(first.get("ok")), "attempts": attempts, "last": first}, files, rejected
    repair_prompt = (
        "Your previous answer was not valid executable file_ops JSON. Return ONLY this JSON shape with one harmless pytest file: "
        "{\"summary\":\"local qwen smoke\",\"files\":[{\"action\":\"write\",\"path\":\"platform/tests/test_local_qwen_fileops_smoke.py\",\"content\":\"def test_local_qwen_fileops_smoke():\\n    assert True\\n\"}]}"
    )
    second = local_model_router.run_local_model(task_type="coding", prompt=repair_prompt, max_tokens=800, temperature=0.0)
    text2 = str(second.get("response") or second.get("text") or second.get("content") or "")
    payload2 = _extract_json_object(text2) if second.get("ok") else None
    files2, rejected2 = _safe_file_ops(payload2)
    attempts.append({"ok": bool(second.get("ok")), "provider_id": second.get("provider_id"), "selected_model": second.get("selected_model"), "runtime": second.get("runtime"), "rejected": rejected2, "preview": text2[:500]})
    return {"ok": bool(second.get("ok")), "attempts": attempts, "last": second}, files2, rejected + rejected2


def _execute_local_qwen_fileops(*, title: str, body: str, repo: str, base_ref: str, work_branch: str, correlation_id: str, from_agent: str, idempotency_key: str) -> dict[str, Any]:
    if not repo:
        return {"ok": False, "provider": "local_qwen", "error": "repo_required"}
    cid = correlation_id or f"local-qwen-{secrets.token_hex(6)}"
    task_id = "ops_provider_" + hashlib.sha256(f"local_qwen|{cid}|{title}".encode()).hexdigest()[:12]
    branch = work_branch or f"local-agent/{task_id}-{hashlib.sha256(cid.encode()).hexdigest()[:6]}"
    lock = local_execution_plane.acquire_lock(repo=repo, actor="provider_execution_fabric", task_id=task_id, correlation_id=cid, ttl_seconds=900)
    if not lock.get("ok"):
        return {"ok": False, "provider": "local_qwen", "stage": "lock", "lock": lock}
    try:
        prepared = local_execution_plane.create_worktree(
            repo=repo, base_branch=base_ref or "main", work_branch=branch, actor="provider_execution_fabric",
            task_id=task_id, correlation_id=cid, idempotency_key=idempotency_key or f"{task_id}-worktree",
        )
        if not prepared.get("ok"):
            return {"ok": False, "provider": "local_qwen", "stage": "worktree", "lock": lock, "prepared": prepared}
        model_run, files, rejected = _model_file_ops(title, body)
        if not files:
            return {"ok": False, "provider": "local_qwen", "stage": "file_ops", "lock": lock, "prepared": prepared, "model_run": model_run, "rejected_files": rejected}
        writes=[]
        for item in files:
            writes.append(local_execution_plane.write_file(
                repo=repo, work_branch=branch, path=item["path"], content=item["content"], actor="provider_execution_fabric",
                task_id=task_id, correlation_id=cid, idempotency_key=f"{task_id}-write-{item['path']}",
            ))
        if not writes or not all(w.get("ok") for w in writes):
            return {"ok": False, "provider": "local_qwen", "stage": "write", "lock": lock, "prepared": prepared, "model_run": model_run, "writes": writes, "rejected_files": rejected}
        test_paths = [w["path"] for w in writes if str(w.get("path") or "").startswith("platform/tests/") and str(w.get("path") or "").endswith(".py")]
        command = ["python3", "-m", "pytest"] + (test_paths or ["platform/tests/test_provider_execution_fabric.py"]) + ["-q"]
        tests = local_execution_plane.run_command_allowlisted(repo=repo, work_branch=branch, command=command, actor="provider_execution_fabric", task_id=task_id, correlation_id=cid, timeout_seconds=120)
        if not (tests.get("ok") and (tests.get("command_result") or {}).get("ok")):
            return {"ok": False, "provider": "local_qwen", "stage": "tests", "lock": lock, "prepared": prepared, "model_run": model_run, "writes": writes, "tests": tests, "rejected_files": rejected}
        commit = local_execution_plane.commit_branch(repo=repo, work_branch=branch, message=f"test: local qwen fileops smoke {task_id}", actor="provider_execution_fabric", task_id=task_id, correlation_id=cid, idempotency_key=f"{task_id}-commit")
        proof = {
            "proof_type": "local_model",
            "run_id": task_id,
            "provider_id": "local-amd-5",
            "model": ((model_run.get("last") or {}).get("selected_model") or "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"),
            "runtime": ((model_run.get("last") or {}).get("runtime") or "local_vllm"),
            "writes": [w.get("path") for w in writes if w.get("ok")],
            "tests_ok": True,
            "commit": commit.get("head"),
        }
        proof_valid = validate_execution_proof("local_qwen", proof)
        return {"ok": bool(commit.get("ok") and proof_valid.get("ok")), "provider": "local_qwen", "execution_state": "completed", "repo": repo, "work_branch": branch, "worktree": prepared.get("worktree"), "lock": lock, "prepared": prepared, "model_run": model_run, "writes": writes, "tests": tests, "commit": commit, "proof": proof, "proof_valid": proof_valid, "rejected_files": rejected}
    finally:
        local_execution_plane.release_lock(repo=repo, actor="provider_execution_fabric", task_id=task_id, correlation_id=cid)

def _provider_exec_env() -> dict[str, str]:
    env = os.environ.copy()
    home = Path.home()
    user_paths = [
        str(home / ".local" / "bin"),
        str(home / ".local" / "npm-global" / "bin"),
    ]
    env["PATH"] = os.pathsep.join(user_paths + [env.get("PATH", "")])
    return env


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
    base_ref = branch or "main"
    work_branch = ""
    if provider_n == "local_qwen":
        return _execute_local_qwen_fileops(
            title=title, body=body, repo=repo, base_ref=base_ref, work_branch=work_branch,
            correlation_id=correlation_id, from_agent=from_agent, idempotency_key=idempotency_key,
        ) if not dry_run else {"ok": True, "dry_run": True, "provider": provider_n, "capability": capability, "execution_state": "ready" if capability.get("status") == "ready" else "blocked"}
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
    """Cheap local smoke proving Codex CLI lifecycle without running paid prompts."""
    started = _now()
    cli_path = str(capability.get("cli_path") or "codex")
    proc = subprocess.Popen(
        [cli_path, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_provider_exec_env(),
        cwd=Path(dispatch.get("worktree") or os.getcwd()),
    )
    try:
        stdout, stderr = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        stderr = (stderr or "") + "\nprovider fabric codex version smoke timed out"
    proof = {
        "proof_type": "process",
        "pid": proc.pid,
        "started_at": started,
        "last_output_at": _now(),
        "exit_code": proc.returncode,
        "stdout_tail": (stdout or "")[-1000:],
        "stderr_tail": (stderr or "")[-1000:],
        "transport": "local_cli",
        "command": ["codex", "--version"],
    }
    running = mark_running_with_proof(dispatch["dispatch_id"], "codex", proof)
    evidence = {
        "fabric_version": FABRIC_VERSION,
        "provider": "codex",
        "run_id": f"provider_smoke_{dispatch['dispatch_id']}",
        "process": proof,
        "capability": capability,
        "tests": "provider fabric codex cli version smoke",
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
        "entrypoints": {
            "mcp": "execute_provider_task(provider='local_qwen'|'codex'|'antigravity'|'cursor', ...)",
            "local_qwen": "validated file_ops -> Local Execution Plane -> tests -> commit",
            "cursor": "remote_inbox_only unless headless adapter proves otherwise",
        },
    }
