"""Two-step, isolated and auditable Codex jobs requested from WhatsApp."""
from __future__ import annotations

import os
import json
import re
import secrets
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.notifications.evolution_client import send_whatsapp

COLLECTION = "ralfia_whatsapp_codex_jobs"
WORKTREE_ROOT = Path("/home/rlopez/worktrees/whatsapp-codex-jobs")
PROJECTS: dict[str, dict[str, Any]] = {
    "openai": {
        "repo": "/home/rlopez/worktrees/raphiia-openai-core-demo",
        "ref": "codex/openai-multimodal-e2e",
        "tests": ["/home/rlopez/projects/raphiia-openai/venv/bin/python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
    },
    "mcp": {
        "repo": "/home/rlopez/worktrees/raphiia-openai-core-demo",
        "ref": "codex/openai-multimodal-e2e",
        "tests": ["/home/rlopez/projects/raphiia-openai/venv/bin/python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
    },
    "quoteops": {
        "repo": "/home/rlopez/projects/ralphiia-quoteops",
        "ref": "codex/openai-whatsapp-demo",
        "tests": ["/home/rlopez/projects/ralphiia-quoteops/.venv/bin/python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
    },
}
PROJECT_ALIASES = {"primary": "openai", "amd": "openai"}
CODEX_BIN = "/home/rlopez/.local/node_modules/.bin/codex" if Path("/home/rlopez/.local/node_modules/.bin/codex").is_file() else "/home/rlopez/.local/bin/codex" if Path("/home/rlopez/.local/bin/codex").is_file() else "codex"
ALLOWED_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
CODEX_MODEL = os.getenv("CODEX_WHATSAPP_MODEL", "gpt-5.6-sol")
if CODEX_MODEL not in ALLOWED_MODELS:
    CODEX_MODEL = "gpt-5.6-sol"
MAX_PROMPT = 3000
SECRET_RE = re.compile(r"(api[_ -]?key|token|password|secret|private[_ -]?key|contraseña)", re.I)
MUTATION_RE = re.compile(r"\b(implementa|corrige|agrega|añade|modifica|crea|actualiza|fix|add|change|update|implement|create)\b", re.I)
REDACT_RE = re.compile(r"(?i)(authorization:\s*bearer\s+|(?:api[_-]?key|token|password|secret)\s*[=:]\s*)\S+")
SAFE_ENV_KEYS = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "SHELL", "CODEX_HOME", "SSL_CERT_FILE", "SSL_CERT_DIR")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: str) -> str:
    return REDACT_RE.sub(r"\1[REDACTED]", value or "")


def _project(target: str) -> tuple[str, dict[str, Any]] | None:
    canonical = PROJECT_ALIASES.get(target, target)
    spec = PROJECTS.get(canonical)
    return (canonical, spec) if spec else None


def _safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    clean = {key: os.environ[key] for key in SAFE_ENV_KEYS if os.environ.get(key)}
    clean.update(extra or {})
    return clean


def _codex_metadata(events: str) -> tuple[str | None, dict[str, int]]:
    thread_id = None
    usage: dict[str, int] = {}
    for line in (events or "").splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if event.get("type") == "thread.started":
            thread_id = str(event.get("thread_id") or "") or None
        elif event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = {
                str(key): int(value)
                for key, value in event["usage"].items()
                if isinstance(value, (int, float))
            }
    return thread_id, usage


def request_job(sender: str, prompt: str, target: str = "openai", node: str = "primary", trace: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    target = (target or "openai").lower()
    selected = _project(target)
    if not selected:
        return {"ok": False, "error": "codex_target_not_allowed", "allowed": sorted(PROJECTS)}
    canonical, spec = selected
    if not prompt:
        return {"ok": False, "error": "codex_prompt_empty"}
    if len(prompt) > MAX_PROMPT:
        return {"ok": False, "error": "codex_prompt_too_long"}
    if SECRET_RE.search(prompt):
        return {"ok": False, "error": "codex_prompt_must_not_contain_secrets"}
    trace = trace or {}
    job_id = f"cj_{secrets.token_urlsafe(8)}"
    now = _now()
    doc = {
        "job_id": job_id,
        "requested_by": sender,
        "target": canonical,
        "node": node,
        "project": spec["repo"],
        "base_ref": spec["ref"],
        "prompt": prompt,
        "status": "pending_confirmation",
        "created_at": now,
        "updated_at": now,
        "execution": "isolated_worktree_workspace_write",
        "risk_class": "development_isolated",
        "requires_deploy_approval": True,
        "model_requested": CODEX_MODEL,
        "correlation_id": trace.get("correlation_id"),
        "source_message_id": trace.get("message_id"),
        "conversation_ref": trace.get("conversation_ref"),
    }
    mongo_store.get_db()[COLLECTION].insert_one(doc)
    return {
        "ok": True,
        "job_id": job_id,
        "status": doc["status"],
        "correlation_id": doc["correlation_id"],
        "text": f"Trabajo Codex {job_id} creado para {canonical}. Responde: confirmar codex {job_id}",
    }


def confirm_job(sender: str, job_id: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    job = db[COLLECTION].find_one({"job_id": job_id, "requested_by": sender})
    if not job:
        return {"ok": False, "error": "codex_job_not_found_or_sender_mismatch"}
    if job.get("status") != "pending_confirmation":
        return {"ok": False, "error": "codex_job_not_pending"}
    db[COLLECTION].update_one({"job_id": job_id}, {"$set": {"status": "approved", "approved_at": _now(), "updated_at": _now()}})
    return {"ok": True, "job_id": job_id, "status": "approved", "text": "Trabajo aprobado. Codex lo ejecutará en un worktree aislado; despliegue y producción siguen bloqueados."}


def _run(command: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env or _safe_env(),
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _safe_worktree(job_id: str) -> Path:
    if not re.fullmatch(r"cj_[A-Za-z0-9_-]{6,32}", job_id):
        raise ValueError("invalid_job_id")
    root = WORKTREE_ROOT.resolve()
    path = (root / job_id).resolve()
    if path.parent != root:
        raise ValueError("unsafe_worktree_path")
    return path


def run_job(job_id: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    job = db[COLLECTION].find_one({"job_id": job_id, "status": "approved"})
    if not job:
        return {"ok": False, "error": "codex_job_not_approved"}
    selected = _project(str(job.get("target") or ""))
    if not selected:
        return {"ok": False, "error": "codex_target_not_allowed"}
    target, spec = selected
    repo = Path(spec["repo"])
    if not repo.is_dir():
        return {"ok": False, "error": "codex_project_unavailable"}
    worktree = _safe_worktree(job_id)
    if worktree.exists():
        return {"ok": False, "error": "codex_worktree_already_exists"}
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    branch = f"codex/wa-{job_id[3:].lower()}"
    started = time.monotonic()
    db[COLLECTION].update_one({"job_id": job_id}, {"$set": {"status": "preparing", "branch": branch, "worktree": str(worktree), "updated_at": _now()}})
    add = _run(["git", "worktree", "add", "-b", branch, str(worktree), str(spec["ref"])], repo, 60)
    if add.returncode != 0:
        error = _redact((add.stderr or add.stdout)[-2000:])
        db[COLLECTION].update_one({"job_id": job_id}, {"$set": {"status": "failed", "error": error, "finished_at": _now(), "updated_at": _now()}})
        return {"ok": False, "job_id": job_id, "status": "failed", "error": "worktree_setup_failed"}
    db[COLLECTION].update_one({"job_id": job_id}, {"$set": {"status": "running", "started_at": _now(), "updated_at": _now()}})
    with tempfile.NamedTemporaryFile(prefix=f"{job_id}-", suffix=".txt", delete=False) as output:
        output_path = Path(output.name)
    guarded_prompt = (
        "Trabaja únicamente en el repositorio actual. No despliegues, no uses sudo, no cambies DNS/credenciales y no imprimas secretos. "
        "Realiza la solicitud, conserva cambios comprobables y termina con un resumen breve. Solicitud: " + str(job.get("prompt") or "")
    )
    model_requested = str(job.get("model_requested") or CODEX_MODEL)
    if model_requested not in ALLOWED_MODELS:
        model_requested = CODEX_MODEL
    cmd = [CODEX_BIN, "exec", "--ignore-user-config", "-m", model_requested, "-c", "shell_environment_policy.inherit=none", "--sandbox", "workspace-write", "--ephemeral", "--json", "--cd", str(worktree), "-o", str(output_path), guarded_prompt]
    try:
        proc = _run(cmd, worktree, 900)
        codex_thread_id, usage = _codex_metadata(proc.stdout)
        result_text = output_path.read_text(errors="replace")[:12000] if output_path.exists() else (proc.stdout or "")[-12000:]
        status_proc = _run(["git", "status", "--porcelain"], worktree, 30)
        changed = bool(status_proc.stdout.strip())
        mutation_expected = bool(MUTATION_RE.search(str(job.get("prompt") or "")))
        test_env = _safe_env({"PYTHONPATH": str(worktree)})
        tests = _run(list(spec["tests"]), worktree, 300, env=test_env)
        commit_sha = None
        diff_stat = ""
        verification_error = None
        if proc.returncode != 0:
            verification_error = "codex_execution_failed"
        elif tests.returncode != 0:
            verification_error = "tests_failed"
        elif mutation_expected and not changed:
            verification_error = "no_verifiable_change"
        if not verification_error and changed:
            stage = _run(["git", "add", "-A"], worktree, 30)
            stat = _run(["git", "diff", "--cached", "--stat"], worktree, 30)
            diff_stat = stat.stdout[-4000:]
            commit = _run(["git", "commit", "-m", f"Codex WhatsApp {job_id}"], worktree, 60)
            if stage.returncode != 0 or commit.returncode != 0:
                verification_error = "commit_failed"
            else:
                sha = _run(["git", "rev-parse", "HEAD"], worktree, 30)
                commit_sha = sha.stdout.strip()
        status = "failed" if verification_error else "completed"
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        evidence = {
            "status": status,
            "returncode": proc.returncode,
            "model_requested": model_requested,
            "codex_thread_id": codex_thread_id,
            "usage": usage,
            "result": _redact(result_text),
            "tests_returncode": tests.returncode,
            "tests_output": _redact(((tests.stdout or "") + "\n" + (tests.stderr or ""))[-8000:]),
            "changed": changed,
            "diff_stat": diff_stat,
            "commit_sha": commit_sha,
            "verification_error": verification_error,
            "latency_ms": latency_ms,
            "finished_at": _now(),
            "updated_at": _now(),
        }
        db[COLLECTION].update_one({"job_id": job_id}, {"$set": evidence})
        return {"ok": not verification_error, "job_id": job_id, "target": target, "status": status, "result": evidence["result"], "tests_returncode": tests.returncode, "commit_sha": commit_sha, "branch": branch, "worktree": str(worktree), "verification_error": verification_error, "latency_ms": latency_ms, "model_requested": model_requested, "codex_thread_id": codex_thread_id, "usage": usage}
    except Exception as exc:
        error = _redact(str(exc))
        db[COLLECTION].update_one({"job_id": job_id}, {"$set": {"status": "failed", "error": error, "finished_at": _now(), "updated_at": _now()}})
        return {"ok": False, "job_id": job_id, "status": "failed", "error": error}
    finally:
        output_path.unlink(missing_ok=True)


def run_next_approved_job() -> dict[str, Any]:
    db = mongo_store.get_db()
    job = db[COLLECTION].find_one({"status": "approved"}, {"_id": 0}, sort=[("approved_at", 1)])
    if not job:
        return {"ok": True, "status": "idle"}
    result = run_job(str(job["job_id"]))
    sender = "".join(c for c in str(job.get("requested_by") or "") if c.isdigit())
    if sender:
        if result.get("ok"):
            body = f"Codex terminó {job['job_id']}. Modelo: {result.get('model_requested')}. Thread: {result.get('codex_thread_id')}. Tests: PASS. Commit: {result.get('commit_sha') or 'sin cambios (consulta)'}.\n\n{str(result.get('result') or '')[:2400]}"
        else:
            body = f"Codex no pudo verificar {job['job_id']}: {str(result.get('verification_error') or result.get('error') or result.get('status'))[:500]}"
        send_whatsapp(body, number=sender, node=str(job.get("node") or "primary"))
    return result
