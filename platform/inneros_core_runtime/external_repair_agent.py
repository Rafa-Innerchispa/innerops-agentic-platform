"""Provider-neutral external repair agent admission and credit guard.

This module is intentionally conservative. It records capability and budget
state, but it does not spend external model credits unless a caller passes an
explicit approval flag to an execution primitive.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pymongo import ReturnDocument

from raphiia_openai import coordination_live, mongo_store
from raphiia_openai.settings import COL_AGENT_MESSAGES

RUNS_COL = "ralfia_external_repair_runs"
CREDIT_STATE_KEY = "external_repair_credit_governor"
PROVIDERS = ("codex", "cursor", "antigravity", "digitalocean-amd-cloud")
LOCAL_CLI_PROVIDERS = {"codex", "cursor", "antigravity"}
CLOUD_BURST_PROVIDERS = {"digitalocean-amd-cloud"}
PRIORITY_ORDER = {"urgent": 0, "critical": 1, "p0": 2, "high": 3, "p1": 4, "normal": 5, "p2": 6, "low": 7}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
NONTERMINAL_STATUSES = {"proposed", "accepted", "in_progress", "partial", "verification", "awaiting_approval", "blocked"}
ACTIVE_STATUSES = {"accepted", "in_progress", "verification", "awaiting_approval", "blocked"}
SUCCESS_RESULTS = {"PASS", "OK", "COMPLETED"}
COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
COMPLETION_MARKERS = ("ya integr", "ya fue cerrado", "closed by", "completed", "integrated", "reconcílialo", "ciérralo")
DEFAULT_DAILY_HARD_LIMIT = {"codex": 3, "cursor": 0, "antigravity": 0, "digitalocean-amd-cloud": 1}
DEFAULT_MONTHLY_HARD_LIMIT = {"codex": 30, "cursor": 0, "antigravity": 0, "digitalocean-amd-cloud": 6}
RUN_ACTIVE_STATUSES = {"queued", "running", "checkpointed"}
RUN_TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled"}
AUTO_CLAIM_ENV = "EXTERNAL_REPAIR_AUTO_CLAIM"
AUTO_CLAIM_OWNER_ENV = "EXTERNAL_REPAIR_OWNER_AUTHORIZED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _run_help(argv: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:1200],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


def _codex_home() -> Path:
    return Path(os.getenv("CODEX_HOME") or Path.home() / ".codex").expanduser()


def _auth_probe(provider: str) -> dict[str, Any]:
    if provider == "codex":
        home = _codex_home()
        auth_file = home / "auth.json"
        config_file = home / "config.toml"
        return {
            "auth_ready": auth_file.is_file() or bool(os.getenv("OPENAI_API_KEY")),
            "auth_markers": {
                "codex_auth_file_present": auth_file.is_file(),
                "codex_config_file_present": config_file.is_file(),
                "openai_api_key_env_present": bool(os.getenv("OPENAI_API_KEY")),
            },
            "secret_policy": "presence only; secret values are never read or returned",
        }
    return {"auth_ready": False, "auth_markers": {}, "secret_policy": "no supported headless auth probe"}


def detect_provider(provider: str) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        return {"ok": False, "provider": provider, "error": "provider_not_supported", "supported": list(PROVIDERS)}
    if provider in CLOUD_BURST_PROVIDERS:
        from raphiia_openai import digitalocean_amd_provider as do

        status = do.status()
        preflight = do.preflight()
        ready = bool(status.get("token_present") and status.get("account_reachable"))
        return {
            "ok": True,
            "provider": provider,
            "node": socket.gethostname(),
            "installed": True,
            "cli_path": "",
            "version": "api:v2",
            "headless_supported": True,
            "auth_ready": bool(status.get("token_present")),
            "status": "ready" if ready else "unavailable",
            "unavailable_reason": "" if ready else "digitalocean_pat_or_account_not_ready",
            "provider_type": "ephemeral_cloud_burst",
            "local_first": True,
            "mutations_require": status.get("mutations_require") or ["approval_id", "apply_window"],
            "preflight": preflight,
        }
    cli = shutil.which(provider)
    installed = bool(cli)
    version = ""
    help_probe: dict[str, Any] = {}
    headless_supported = False
    if installed:
        version_probe = _run_help([cli, "--version"])
        version = ((version_probe.get("stdout") or version_probe.get("stderr") or "").splitlines() or [""])[0][:120]
        if provider == "codex":
            help_probe = _run_help([cli, "exec", "--help"])
            help_text = f"{help_probe.get('stdout') or ''}\n{help_probe.get('stderr') or ''}".lower()
            headless_supported = bool(help_probe.get("ok") and "non-interactively" in help_text)
    auth = _auth_probe(provider)
    status = "ready" if installed and headless_supported and auth.get("auth_ready") else "unavailable"
    reason = ""
    if not installed:
        reason = "cli_not_installed"
    elif not headless_supported:
        reason = "headless_runner_not_confirmed"
    elif not auth.get("auth_ready"):
        reason = "auth_not_ready"
    return {
        "ok": True,
        "provider": provider,
        "node": socket.gethostname(),
        "installed": installed,
        "cli_path": cli or "",
        "version": version,
        "headless_supported": headless_supported,
        "auth_ready": bool(auth.get("auth_ready")),
        "status": status,
        "unavailable_reason": reason,
        "auth": auth,
    }


def provider_matrix() -> dict[str, Any]:
    providers = [detect_provider(p) for p in PROVIDERS]
    return {
        "ok": True,
        "node": socket.gethostname(),
        "generated_at": _now(),
        "providers": providers,
        "architecture": {
            "default_route": "Dev Swarm/local models first",
            "external_route": "repair/escalation only after capability and credit admission",
            "canonical_store": "Mongo ralfia_ops_tasks + ralfia_external_repair_runs",
        },
    }


def _credit_config() -> dict[str, Any]:
    state = mongo_store.get_coordination_state(CREDIT_STATE_KEY)
    cfg = dict((state.get("state") or {}) if state.get("ok") else {})
    cfg.setdefault("enabled", True)
    cfg.setdefault("daily_hard_limit", dict(DEFAULT_DAILY_HARD_LIMIT))
    cfg.setdefault("monthly_hard_limit", dict(DEFAULT_MONTHLY_HARD_LIMIT))
    cfg.setdefault("external_spend_default", False)
    cfg.setdefault("updated_at", _now())
    return cfg


def external_credit_status(provider: str = "") -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    providers = [provider] if provider else list(PROVIDERS)
    now = datetime.now(timezone.utc)
    day_start = (now - timedelta(days=1)).isoformat()
    month_start = (now - timedelta(days=30)).isoformat()
    cfg = _credit_config()
    rows = []
    for p in providers:
        daily = _db()[RUNS_COL].count_documents({"provider": p, "started_at": {"$gte": day_start}, "chargeable": True})
        monthly = _db()[RUNS_COL].count_documents({"provider": p, "started_at": {"$gte": month_start}, "chargeable": True})
        daily_limit = int((cfg.get("daily_hard_limit") or {}).get(p, 0))
        monthly_limit = int((cfg.get("monthly_hard_limit") or {}).get(p, 0))
        row = {
            "provider": p,
            "daily_chargeable_runs": daily,
            "monthly_chargeable_runs": monthly,
            "daily_hard_limit": daily_limit,
            "monthly_hard_limit": monthly_limit,
            "hard_blocked": daily >= daily_limit or monthly >= monthly_limit,
        }
        if p == "digitalocean-amd-cloud":
            try:
                from raphiia_openai import digitalocean_amd_provider as do

                row["provider_credit"] = do.balance()
                row["billing_policy"] = "DigitalOcean charges are governed by explicit approval, apply window, per-session spend_limit_usd, idle timeout, and destroy evidence."
            except Exception as exc:
                row["provider_credit"] = {"ok": False, "error": str(exc)[:300]}
        rows.append(row)
    return {"ok": True, "config": cfg, "providers": rows}


def _budget_allows(provider: str) -> dict[str, Any]:
    status = external_credit_status(provider)
    row = (status.get("providers") or [{}])[0]
    if row.get("hard_blocked"):
        return {"ok": False, "error": "blocked_by_budget", "credit": row}
    return {"ok": True, "credit": row}


def external_repair_agent_status(provider: str = "") -> dict[str, Any]:
    matrix = provider_matrix()
    credit = external_credit_status(provider)
    active_runs = list_active_runs(provider=provider, limit=10)
    nonterminal = provider_nonterminal_summary(provider=provider, limit=50)
    if provider:
        matrix["providers"] = [p for p in matrix["providers"] if p.get("provider") == provider]
    return {
        "ok": True,
        "matrix": matrix,
        "credit_governor": credit,
        "active_runs": active_runs,
        "pending_nonterminal_count": nonterminal.get("pending_nonterminal_count", 0),
        "nonterminal_buckets": nonterminal.get("buckets", {}),
        "nonterminal_statuses": nonterminal.get("statuses", {}),
        "nonterminal_tasks": nonterminal.get("tasks", []),
    }


def list_active_runs(provider: str = "", limit: int = 20) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"status": {"$in": sorted(RUN_ACTIVE_STATUSES)}}
    if provider:
        query["provider"] = provider.strip().lower()
    return list(
        _db()[RUNS_COL]
        .find(query, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(int(limit or 20), 100)))
    )


def list_provider_active_tasks(provider: str = "codex", limit: int = 20, stale_after_seconds: int = 7200) -> list[dict[str, Any]]:
    provider_n = (provider or "codex").strip().lower()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(60, int(stale_after_seconds or 7200)))).isoformat()
    query = {
        "assignee": provider_n,
        "owner": provider_n,
        "status": {"$in": ["accepted", "in_progress"]},
        "$or": [
            {"last_heartbeat_at": {"$gte": cutoff}},
            {"updated_at": {"$gte": cutoff}},
        ],
    }
    return list(
        _db()[coordination_live.OPS_TASKS_COL]
        .find(query, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(int(limit or 20), 100)))
    )



def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_task_activity(task: dict[str, Any]) -> datetime | None:
    candidates = [
        task.get("last_heartbeat_at"),
        task.get("last_evidence_at"),
        task.get("updated_at"),
        task.get("started_at"),
        task.get("accepted_at"),
        task.get("created_at"),
    ]
    parsed = [_parse_ts(value) for value in candidates]
    parsed = [value for value in parsed if value]
    return max(parsed) if parsed else None


def _latest_run(runs: list[dict[str, Any]], statuses: set[str] | None = None) -> dict[str, Any] | None:
    filtered = [run for run in runs if not statuses or str(run.get("status") or "").lower() in statuses]
    if not filtered:
        return None
    return sorted(filtered, key=lambda run: str(run.get("updated_at") or run.get("ended_at") or run.get("started_at") or ""), reverse=True)[0]


def _recoverable_blocked_task(task: dict[str, Any]) -> bool:
    if bool(task.get("dev_swarm_retry_requested")):
        return True
    text = " ".join(str(task.get(k) or "") for k in ("next_action", "blocker", "dev_swarm_last_skip_reason"))
    if not text.strip():
        return False
    retry_markers = ("retry", "resume", "recover", "next", "escalate", "reanudar", "corregir")
    exhausted_markers = ("no_retry", "do_not_retry", "human_required", "approval_required")
    text_l = text.lower()
    return any(marker in text_l for marker in retry_markers) and not any(marker in text_l for marker in exhausted_markers)


def _summarize_task(task: dict[str, Any], *, bucket: str, action: str, run: dict[str, Any] | None = None, stale_after_seconds: int = 7200) -> dict[str, Any]:
    latest_activity = _latest_task_activity(task)
    now = datetime.now(timezone.utc)
    age_seconds = int((now - latest_activity).total_seconds()) if latest_activity else None
    return {
        "task_id": str(task.get("task_id") or ""),
        "status": str(task.get("status") or ""),
        "owner": task.get("owner"),
        "priority": task.get("priority"),
        "correlation_id": task.get("correlation_id"),
        "repo": task.get("repo") or task.get("related_project"),
        "work_branch": task.get("work_branch"),
        "bucket": bucket,
        "action": action,
        "run_id": (run or {}).get("run_id"),
        "run_status": (run or {}).get("status"),
        "latest_activity_at": latest_activity.isoformat() if latest_activity else None,
        "age_seconds": age_seconds,
        "stale_after_seconds": int(stale_after_seconds),
    }


def classify_nonterminal_task(task: dict[str, Any], runs: list[dict[str, Any]] | None = None, *, stale_after_seconds: int = 7200) -> dict[str, Any]:
    """Classify one non-terminal ops_task without deleting or re-running work."""
    task_runs = list(runs or [])
    status = str(task.get("status") or "").strip().lower()
    active_run = _latest_run(task_runs, RUN_ACTIVE_STATUSES)
    if active_run:
        return _summarize_task(task, bucket="ACTIVE_RUN", action="MONITOR", run=active_run, stale_after_seconds=stale_after_seconds)
    terminal_run = _latest_run(task_runs, RUN_TERMINAL_STATUSES)
    if terminal_run and str(terminal_run.get("status") or "").lower() == "completed":
        return _summarize_task(task, bucket="TERMINAL_PENDING_EVIDENCE", action="CLOSE_FROM_COMPLETED_RUN", run=terminal_run, stale_after_seconds=stale_after_seconds)
    if status == "proposed":
        return _summarize_task(task, bucket="PROPOSED", action="ELIGIBLE_FOR_CLAIM", stale_after_seconds=stale_after_seconds)
    if status == "blocked" and not _recoverable_blocked_task(task):
        return _summarize_task(task, bucket="BLOCKED", action="WAIT_FOR_OWNER_OR_NEW_EVIDENCE", stale_after_seconds=stale_after_seconds)
    latest = _latest_task_activity(task)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(60, int(stale_after_seconds or 7200)))
    if not latest or latest < cutoff:
        return _summarize_task(task, bucket="STALE_RECOVERABLE", action="RESUME_OR_CLOSE_WITH_EVIDENCE", stale_after_seconds=stale_after_seconds)
    return _summarize_task(task, bucket="ACTIVE_TASK_NO_RUN", action="MONITOR_TASK_STATE", stale_after_seconds=stale_after_seconds)


def list_provider_nonterminal_tasks(provider: str = "codex", limit: int = 50) -> list[dict[str, Any]]:
    provider_n = (provider or "codex").strip().lower()
    query = {"assignee": provider_n, "status": {"$in": sorted(NONTERMINAL_STATUSES)}}
    return list(
        _db()[coordination_live.OPS_TASKS_COL]
        .find(query, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(int(limit or 50), 200)))
    )


def _runs_by_task(provider: str, task_ids: list[str], limit: int = 200) -> dict[str, list[dict[str, Any]]]:
    if not task_ids:
        return {}
    query: dict[str, Any] = {"task_id": {"$in": task_ids}}
    provider_n = (provider or "").strip().lower()
    if provider_n:
        query["provider"] = provider_n
    runs = list(_db()[RUNS_COL].find(query, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(int(limit or 200), 500))))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(str(run.get("task_id") or ""), []).append(run)
    return grouped


def provider_nonterminal_summary(provider: str = "codex", limit: int = 50, stale_after_seconds: int = 7200) -> dict[str, Any]:
    provider_n = (provider or "codex").strip().lower()
    tasks = list_provider_nonterminal_tasks(provider_n, limit=limit)
    grouped_runs = _runs_by_task(provider_n, [str(task.get("task_id") or "") for task in tasks], limit=max(limit * 4, 50))
    rows = [classify_nonterminal_task(task, grouped_runs.get(str(task.get("task_id") or ""), []), stale_after_seconds=stale_after_seconds) for task in tasks]
    statuses: dict[str, int] = {}
    buckets: dict[str, int] = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        buckets[row["bucket"]] = buckets.get(row["bucket"], 0) + 1
    return {
        "ok": True,
        "provider": provider_n,
        "pending_nonterminal_count": len(rows),
        "statuses": statuses,
        "buckets": buckets,
        "tasks": rows[: max(1, min(int(limit or 50), 100))],
    }




def _is_success_result(value: Any) -> bool:
    return str(value or "").strip().upper() in SUCCESS_RESULTS


def _normalize_success_evidence(evidence: dict[str, Any], raw_result: Any = "PASS") -> dict[str, Any]:
    normalized = dict(evidence or {})
    result = str(normalized.get("result") or raw_result or "PASS")
    if result.upper() not in SUCCESS_RESULTS:
        normalized["external_repair_result_text"] = result
        normalized["result"] = "PASS"
    else:
        normalized["result"] = result.upper()
    return normalized


def _close_task_from_terminal_evidence(task: dict[str, Any], evidence: dict[str, Any], *, provider: str, row: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    current_status = str(task.get("status") or "").lower()
    if current_status == "blocked":
        resumed = coordination_live.update_ops_task_state(
            task_id,
            "in_progress",
            actor=provider,
            evidence={"result": "OK", "reason": "resume only to close terminal evidence", "run_id": evidence.get("run_id"), "message_id": evidence.get("message_id")},
            force_handoff=True,
        )
        if not resumed.get("ok"):
            return {**row, "error": resumed.get("error"), "details": resumed}
        current_status = "in_progress"
    if current_status != "verification":
        verifying = coordination_live.update_ops_task_state(
            task_id,
            "verification",
            actor=provider,
            evidence={"result": "OK", "reason": "terminal evidence pending task closure", "run_id": evidence.get("run_id"), "message_id": evidence.get("message_id")},
            force_handoff=True,
        )
        if not verifying.get("ok"):
            return {**row, "error": verifying.get("error"), "details": verifying}
    result = coordination_live.complete_ops_task(task_id, status="completed", evidence=evidence)
    if result.get("ok"):
        return {**row, "status": "completed"}
    return {**row, "error": result.get("error"), "details": result}


def _message_completion_evidence(task: dict[str, Any], *, provider: str) -> dict[str, Any] | None:
    task_id = str(task.get("task_id") or "")
    correlation_id = str(task.get("correlation_id") or "")
    if not task_id and not correlation_id:
        return None
    clauses: list[dict[str, Any]] = []
    if task_id:
        clauses.extend([
            {"body": {"$regex": re.escape(task_id), "$options": "i"}},
            {"payload.hyperloom_task_id": task_id},
            {"payload.completed_task_id": task_id},
            {"payload.task_id": task_id},
        ])
    if correlation_id:
        clauses.append({"body": {"$regex": re.escape(correlation_id), "$options": "i"}})
    query: dict[str, Any] = {"$or": clauses}
    messages = list(_db()[COL_AGENT_MESSAGES].find(query, {"_id": 0}).sort("created_at", -1).limit(25))
    for msg in messages:
        payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
        text = " ".join(str(msg.get(k) or "") for k in ("title", "body"))
        text_l = text.lower()
        explicit_payload_match = task_id and task_id in {str(payload.get("hyperloom_task_id") or ""), str(payload.get("completed_task_id") or "")}
        if not explicit_payload_match:
            continue
        commit = str(payload.get("hyperloom_canonical_commit") or payload.get("commit_sha") or "")
        if not COMMIT_SHA_RE.fullmatch(commit):
            found = COMMIT_SHA_RE.search(text)
            commit = found.group(0) if found else ""
        has_marker = any(marker in text_l for marker in COMPLETION_MARKERS)
        no_rerun_guard = "no debe reejecutarse" in text_l or "do not rerun" in text_l or "no rerun" in text_l
        if commit and has_marker and (no_rerun_guard or "canonical" in text_l or "canónica" in text_l):
            return {
                "result": "PASS",
                "reconciled_from_agent_message": True,
                "message_id": msg.get("message_id"),
                "commit_sha": commit.lower(),
                "source_agent": msg.get("from_agent"),
                "reconcile_policy": "agent_message_terminal_evidence_v1",
                "no_rerun": bool(no_rerun_guard),
            }
    return None
def reconcile_completed_runs_to_tasks(provider: str = "codex", limit: int = 25, dry_run: bool = False) -> dict[str, Any]:
    """Close non-terminal ops_tasks whose external repair run is already completed."""
    provider_n = (provider or "codex").strip().lower()
    runs = list(
        _db()[RUNS_COL]
        .find({"provider": provider_n, "status": "completed"}, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(int(limit or 25), 100)))
    )
    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for run in runs:
        task_id = str(run.get("task_id") or "")
        if not task_id:
            continue
        task = _db()[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id, "status": {"$in": sorted(NONTERMINAL_STATUSES)}}, {"_id": 0})
        if not task:
            continue
        raw_evidence = dict(run.get("evidence") or {})
        if not (_is_success_result(raw_evidence.get("result")) or _is_success_result(run.get("result"))):
            skipped.append({
                "task_id": task_id,
                "run_id": run.get("run_id"),
                "previous_status": task.get("status"),
                "reason": "completed_run_without_explicit_success_result",
                "result": raw_evidence.get("result") or run.get("result"),
            })
            continue
        evidence = _normalize_success_evidence(raw_evidence, run.get("result") or "PASS")
        evidence.setdefault("run_id", run.get("run_id"))
        evidence.setdefault("reconciled_from_completed_run", True)
        evidence.setdefault("reconcile_policy", "external_repair_completed_run_to_task_v1")
        row = {"task_id": task_id, "run_id": run.get("run_id"), "previous_status": task.get("status"), "result": evidence.get("result")}
        if dry_run:
            skipped.append({**row, "dry_run": True})
            continue
        closed_row = _close_task_from_terminal_evidence(task, evidence, provider=provider_n, row=row)
        if closed_row.get("status") == "completed":
            closed.append(closed_row)
        else:
            skipped.append(closed_row)
    already_closed = {row["task_id"] for row in closed}
    tasks = list_provider_nonterminal_tasks(provider_n, limit=limit)
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        if not task_id or task_id in already_closed:
            continue
        evidence = _message_completion_evidence(task, provider=provider_n)
        if not evidence:
            continue
        evidence = _normalize_success_evidence(evidence, evidence.get("result") or "PASS")
        row = {"task_id": task_id, "run_id": None, "message_id": evidence.get("message_id"), "previous_status": task.get("status"), "result": evidence.get("result")}
        if dry_run:
            skipped.append({**row, "dry_run": True})
            continue
        closed_row = _close_task_from_terminal_evidence(task, evidence, provider=provider_n, row=row)
        if closed_row.get("status") == "completed":
            closed.append(closed_row)
            already_closed.add(task_id)
        else:
            skipped.append(closed_row)
    return {"ok": True, "dry_run": dry_run, "closed": closed, "skipped": skipped, "closed_count": len(closed), "skipped_count": len(skipped)}


def record_nonterminal_reconcile_buckets(provider: str = "codex", limit: int = 50, dry_run: bool = False) -> dict[str, Any]:
    summary = provider_nonterminal_summary(provider=provider, limit=limit)
    now = _now()
    updates: list[dict[str, Any]] = []
    for row in summary.get("tasks") or []:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            continue
        updates.append({"task_id": task_id, "bucket": row.get("bucket"), "action": row.get("action")})
        if not dry_run:
            _db()[coordination_live.OPS_TASKS_COL].update_one(
                {"task_id": task_id, "status": {"$in": sorted(NONTERMINAL_STATUSES)}},
                {"$set": {"nonterminal_reconcile_bucket": row.get("bucket"), "nonterminal_next_action": row.get("action"), "nonterminal_reconciled_at": now, "updated_by": "external_repair_agent"}},
            )
    return {"ok": True, "dry_run": dry_run, "summary": summary, "updates": updates}


def _task_priority_key(task: dict[str, Any]) -> tuple[int, str]:
    return (PRIORITY_ORDER.get(str(task.get("priority") or "normal").lower(), 99), str(task.get("created_at") or ""))


def _candidate_tasks(provider: str, limit: int) -> list[dict[str, Any]]:
    rows = list(
        _db()[coordination_live.OPS_TASKS_COL]
        .find({"assignee": provider, "status": "proposed"}, {"_id": 0})
        .sort("created_at", 1)
        .limit(max(1, min(int(limit or 1), 20)))
    )
    return sorted(rows, key=_task_priority_key)


def _auto_claim_enabled(provider: str) -> bool:
    raw = os.getenv(AUTO_CLAIM_ENV, "").strip().lower()
    provider_raw = os.getenv(f"{AUTO_CLAIM_ENV}_{provider.upper()}", "").strip().lower()
    owner_raw = os.getenv(AUTO_CLAIM_OWNER_ENV, "").strip().lower()
    enabled_values = {"1", "true", "yes", "on", "enabled", "owner_authorized"}
    return provider_raw in enabled_values or (raw in enabled_values and owner_raw in enabled_values)


def _mark_admission_blocked(provider: str, selected: dict[str, Any], admission: dict[str, Any], capability: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    reason = "blocked_by_budget" if not admission.get("budget_ok") else "provider_not_ready"
    claimed = _db()[coordination_live.OPS_TASKS_COL].find_one_and_update(
        {"task_id": selected["task_id"], "status": "proposed", "owner": None, "revision": selected.get("revision", 1)},
        {
            "$set": {
                "status": "accepted",
                "owner": provider,
                "updated_at": now,
                "updated_by": "external_repair_agent",
                "last_heartbeat_at": now,
            },
            "$inc": {"revision": 1},
            "$push": {"state_history": {"at": now, "actor": "external_repair_agent", "from": "proposed", "to": "accepted", "provider": provider}},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not claimed:
        return {"ok": False, "error": "claim_race_lost", "provider": provider, "candidate_task_id": selected["task_id"]}
    evidence = {
        "result": "BLOCKED",
        "reason": reason,
        "admission": admission,
        "capability": capability,
        "budget": budget,
    }
    blocked = coordination_live.update_ops_task_state(
        str(claimed["task_id"]),
        "blocked",
        actor=provider,
        expected_revision=int(claimed.get("revision") or 1),
        evidence=evidence,
        force_handoff=True,
    )
    return {"ok": bool(blocked.get("ok")), "claimed": True, "blocked": True, "reason": reason, "provider": provider, "task": claimed, "transition": blocked}


def external_repair_agent_claim_next(provider: str = "codex", dry_run: bool = True, limit: int = 10, task_id: str = "") -> dict[str, Any]:
    provider = (provider or "codex").strip().lower()
    capability = detect_provider(provider)
    budget = _budget_allows(provider)
    task_id = (task_id or "").strip()
    if task_id:
        doc = _db()[coordination_live.OPS_TASKS_COL].find_one({"task_id": task_id, "assignee": provider, "status": "proposed"}, {"_id": 0})
        candidates = [doc] if doc else []
    else:
        candidates = _candidate_tasks(provider, limit)
    if not candidates:
        return {"ok": True, "claimed": False, "provider": provider, "reason": "no_proposed_tasks", "capability": capability, "budget": budget}
    selected = candidates[0]
    admission = {
        "capability_ok": capability.get("status") == "ready",
        "budget_ok": budget.get("ok"),
        "local_first": "Dev Swarm/local models should be attempted before external spend unless this is repair/escalation",
    }
    if dry_run:
        return {"ok": True, "dry_run": dry_run, "claimed": False, "provider": provider, "candidate": selected, "admission": admission, "capability": capability, "budget": budget}
    if not (admission["capability_ok"] and admission["budget_ok"]):
        return _mark_admission_blocked(provider, selected, admission, capability, budget)

    now = _now()
    claimed = _db()[coordination_live.OPS_TASKS_COL].find_one_and_update(
        {"task_id": selected["task_id"], "status": "proposed", "owner": None, "revision": selected.get("revision", 1)},
        {
            "$set": {
                "status": "accepted",
                "owner": provider,
                "updated_at": now,
                "updated_by": "external_repair_agent",
                "last_heartbeat_at": now,
            },
            "$inc": {"revision": 1},
            "$push": {"state_history": {"at": now, "actor": "external_repair_agent", "from": "proposed", "to": "accepted", "provider": provider}},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not claimed:
        return {"ok": False, "error": "claim_race_lost", "provider": provider, "candidate_task_id": selected["task_id"]}
    coordination_live.bump_revision(reason=f"external_repair_agent claimed {selected['task_id']}", source="external_repair_agent")
    promoted = coordination_live.update_ops_task_state(claimed["task_id"], "in_progress", actor=provider, expected_revision=int(claimed.get("revision") or 1))
    if not promoted.get("ok"):
        return {"ok": False, "error": "claim_promote_failed", "provider": provider, "task": claimed, "promotion": promoted}
    task = _db()[coordination_live.OPS_TASKS_COL].find_one({"task_id": claimed["task_id"]}, {"_id": 0}) or claimed
    return {"ok": True, "claimed": True, "provider": provider, "task": task, "admission": admission, "promotion": promoted}


def reconcile_terminal_handoffs(provider: str = "codex", limit: int = 25) -> dict[str, Any]:
    """Mark machine-generated handoffs for terminal tasks as done without acknowledging human decisions."""
    provider_n = (provider or "codex").strip().lower()
    terminal_tasks = list(
        _db()[coordination_live.OPS_TASKS_COL]
        .find({"assignee": provider_n, "status": {"$in": sorted(TERMINAL_STATUSES)}}, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(int(limit or 25), 100)))
    )
    task_ids = {str(task.get("task_id") or "") for task in terminal_tasks if task.get("task_id")}
    correlations = {str(task.get("correlation_id") or "") for task in terminal_tasks if task.get("correlation_id")}
    if not task_ids and not correlations:
        return {"ok": True, "resolved": [], "checked_terminal_tasks": 0}
    query = {
        "target_agent": {"$in": ["chatgpt", provider_n]},
        "type": "handoff",
        "status": {"$in": ["open", "acknowledged"]},
        "$or": [
            {"payload.task_id": {"$in": sorted(task_ids)}},
            {"correlation_id": {"$in": sorted(correlations)}},
        ],
    }
    now = _now()
    resolved: list[str] = []
    for msg in _db()[COL_AGENT_MESSAGES].find(query, {"_id": 0}).limit(max(1, min(int(limit or 25), 100))):
        payload = msg.get("payload") or {}
        if payload.get("requires_human_approval") is True or msg.get("priority") in {"approval", "p0"}:
            continue
        result = _db()[COL_AGENT_MESSAGES].update_one(
            {"message_id": msg.get("message_id"), "status": msg.get("status")},
            {
                "$set": {
                    "status": "done",
                    "resolved_at": now,
                    "resolved_by": "external_repair_reconcile",
                    "updated_at": now,
                    "resolution": "terminal_task_handoff_consumed",
                }
            },
        )
        if getattr(result, "modified_count", 0) == 1:
            resolved.append(str(msg.get("message_id")))
    if resolved:
        coordination_live.bump_revision(reason=f"external_repair_reconcile resolved {len(resolved)} terminal handoff(s)", source="external_repair_agent")
    return {"ok": True, "resolved": resolved, "checked_terminal_tasks": len(terminal_tasks)}


def external_repair_agent_reconcile(provider: str = "codex", auto_claim: bool = True, limit: int = 10, dry_run: bool = False) -> dict[str, Any]:
    """Reconcile terminal handoffs, stale runs and optionally auto-claim the next eligible task."""
    provider_n = (provider or "codex").strip().lower()
    status_before = external_repair_agent_status(provider_n)
    completed_runs = reconcile_completed_runs_to_tasks(provider_n, limit=max(limit, 10), dry_run=dry_run)
    handoffs = reconcile_terminal_handoffs(provider_n, limit=max(limit, 10))
    recovered = recover_external_repair_runs(provider=provider_n, mark_stale_after_seconds=3600)
    bucket_record = record_nonterminal_reconcile_buckets(provider_n, limit=max(limit, 20), dry_run=dry_run)
    status_mid = external_repair_agent_status(provider_n)
    active_runs = status_mid.get("active_runs") or []
    active_tasks = [
        task for task in (status_mid.get("nonterminal_tasks") or [])
        if task.get("bucket") in {"ACTIVE_RUN", "ACTIVE_TASK_NO_RUN"}
    ]
    capability = ((status_mid.get("matrix") or {}).get("providers") or [{}])[0]
    enabled = _auto_claim_enabled(provider_n)
    claim: dict[str, Any] = {"ok": True, "claimed": False, "reason": "auto_claim_disabled", "enabled": enabled}
    if auto_claim and enabled and not active_runs and not active_tasks and capability.get("status") == "ready":
        claim = external_repair_agent_claim_next(provider=provider_n, dry_run=dry_run, limit=limit)
    elif auto_claim and enabled and active_runs:
        claim = {"ok": True, "claimed": False, "reason": "provider_has_active_runs", "active_runs": active_runs}
    elif auto_claim and enabled and active_tasks:
        claim = {"ok": True, "claimed": False, "reason": "provider_has_active_tasks", "active_tasks": active_tasks}
    elif auto_claim and enabled and capability.get("status") != "ready":
        claim = {"ok": True, "claimed": False, "reason": "provider_not_ready", "capability": capability}
    status_after = external_repair_agent_status(provider_n)
    return {
        "ok": bool(completed_runs.get("ok") and handoffs.get("ok") and recovered.get("ok") and bucket_record.get("ok") and claim.get("ok")),
        "provider": provider_n,
        "auto_claim_enabled": enabled,
        "status_before": status_before,
        "completed_runs": completed_runs,
        "handoffs": handoffs,
        "recovered": recovered,
        "nonterminal_reconcile": bucket_record,
        "active_tasks": active_tasks,
        "claim": claim,
        "status_after": status_after,
    }


def record_external_repair_run(
    *,
    provider: str,
    task_id: str,
    correlation_id: str = "",
    outcome: str,
    chargeable: bool = False,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = {
        "run_id": f"extrep_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{os.getpid()}",
        "provider": provider,
        "task_id": task_id,
        "correlation_id": correlation_id,
        "node": socket.gethostname(),
        "started_at": _now(),
        "ended_at": _now(),
        "outcome": outcome,
        "chargeable": bool(chargeable),
        "evidence": evidence or {},
    }
    _db()[RUNS_COL].insert_one(dict(doc))
    return {"ok": True, "run": doc}


def start_external_repair_run(
    *,
    provider: str,
    task_id: str,
    correlation_id: str = "",
    repo: str = "",
    branch: str = "",
    worktree: str = "",
    dry_run: bool = True,
    chargeable: bool = False,
    context_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    task_id = (task_id or "").strip()
    if provider not in PROVIDERS:
        return {"ok": False, "error": "provider_not_supported", "provider": provider}
    if not task_id:
        return {"ok": False, "error": "task_id_required"}
    budget = _budget_allows(provider)
    if chargeable and not budget.get("ok"):
        return {"ok": False, **budget}
    run_id = f"extrep_{task_id}_{provider}_{secrets.token_hex(4)}"
    now = _now()
    doc = {
        "run_id": run_id,
        "provider": provider,
        "task_id": task_id,
        "correlation_id": correlation_id,
        "node": socket.gethostname(),
        "repo": repo,
        "branch": branch,
        "worktree": worktree,
        "status": "queued" if dry_run else "running",
        "started_at": now,
        "updated_at": now,
        "attempts": 0,
        "chargeable": bool(chargeable),
        "dry_run": bool(dry_run),
        "context_bundle": context_bundle or {},
        "checkpoints": [],
        "evidence_refs": [],
    }
    _db()[RUNS_COL].insert_one(dict(doc))
    return {"ok": True, "run": doc}


def checkpoint_external_repair_run(
    run_id: str,
    *,
    phase: str,
    evidence: dict[str, Any] | None = None,
    files_touched: list[str] | None = None,
) -> dict[str, Any]:
    run_id = (run_id or "").strip()
    if not run_id:
        return {"ok": False, "error": "run_id_required"}
    now = _now()
    checkpoint = {
        "at": now,
        "phase": (phase or "checkpoint").strip(),
        "evidence": evidence or {},
        "files_touched": [str(x) for x in (files_touched or [])],
    }
    result = _db()[RUNS_COL].find_one_and_update(
        {"run_id": run_id, "status": {"$nin": sorted(RUN_TERMINAL_STATUSES)}},
        {
            "$set": {"status": "checkpointed", "updated_at": now, "last_checkpoint_at": now},
            "$inc": {"attempts": 1},
            "$push": {"checkpoints": {"$each": [checkpoint], "$slice": -50}},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not result:
        return {"ok": False, "error": "run_not_found_or_terminal", "run_id": run_id}
    try:
        coordination_live.heartbeat_ops_task(
            str(result.get("task_id") or ""),
            str(result.get("provider") or "external_repair_agent"),
            next_action=f"external repair checkpoint: {checkpoint['phase']}",
            files_touched=checkpoint["files_touched"],
        )
    except Exception:
        pass
    return {"ok": True, "run": result, "checkpoint": checkpoint}


def complete_external_repair_run(
    run_id: str,
    *,
    outcome: str = "completed",
    result: str = "PASS",
    evidence: dict[str, Any] | None = None,
    report_to: str = "chatgpt",
    update_task: bool = True,
) -> dict[str, Any]:
    run_id = (run_id or "").strip()
    if not run_id:
        return {"ok": False, "error": "run_id_required"}
    outcome = (outcome or "completed").strip().lower()
    if outcome not in RUN_TERMINAL_STATUSES:
        return {"ok": False, "error": "invalid_outcome", "accepted": sorted(RUN_TERMINAL_STATUSES)}
    now = _now()
    final_evidence = {"result": result, **(evidence or {})}
    run = _db()[RUNS_COL].find_one_and_update(
        {"run_id": run_id},
        {"$set": {"status": outcome, "outcome": outcome, "result": result, "evidence": final_evidence, "ended_at": now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not run:
        return {"ok": False, "error": "run_not_found", "run_id": run_id}
    task_result: dict[str, Any] | None = None
    if update_task and run.get("task_id"):
        target_status = "completed" if outcome == "completed" else "blocked" if outcome == "blocked" else "failed"
        try:
            if target_status == "completed":
                coordination_live.update_ops_task_state(str(run["task_id"]), "verification", actor=str(run.get("provider") or "external_repair_agent"), evidence=final_evidence, force_handoff=True)
                task_result = coordination_live.complete_ops_task(str(run["task_id"]), status="completed", evidence=final_evidence)
            else:
                task_result = coordination_live.update_ops_task_state(str(run["task_id"]), target_status, actor=str(run.get("provider") or "external_repair_agent"), evidence=final_evidence, force_handoff=True)
        except Exception as exc:
            task_result = {"ok": False, "error": str(exc)[:500]}
    report_result = _report_external_repair_result(run, report_to=report_to)
    return {"ok": True, "run": run, "task_result": task_result, "report": report_result}


def _report_external_repair_result(run: dict[str, Any], *, report_to: str = "chatgpt") -> dict[str, Any]:
    target = (report_to or "chatgpt").strip().lower()
    if target not in {"chatgpt", "ralfia", "codex", "cursor", "antigravity"}:
        target = "chatgpt"
    title = f"External repair run {run.get('status')}: {run.get('task_id')}"
    body = (
        f"run_id: `{run.get('run_id')}`\n"
        f"provider: `{run.get('provider')}`\n"
        f"task_id: `{run.get('task_id')}`\n"
        f"status: `{run.get('status')}`\n"
        f"result: `{run.get('result')}`\n"
        f"chargeable: `{run.get('chargeable')}`\n"
        f"node: `{run.get('node')}`"
    )
    try:
        from raphiia_openai import coordination_ingest

        return coordination_ingest.ingest_agent_message(
            from_agent="EXTERNAL_REPAIR_AGENT",
            target_agent=target,
            title=title,
            body=body,
            priority="normal",
            correlation_id=str(run.get("correlation_id") or run.get("run_id") or ""),
            message_type="handoff",
            payload={"run_id": run.get("run_id"), "task_id": run.get("task_id"), "provider": run.get("provider")},
            idempotency_key=f"external-repair-report-{run.get('run_id')}-{target}",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


def recover_external_repair_runs(provider: str = "", mark_stale_after_seconds: int = 3600) -> dict[str, Any]:
    """Return resumable runs and mark old active ones as blocked by stale timeout."""
    provider = (provider or "").strip().lower()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=max(60, int(mark_stale_after_seconds or 3600)))).isoformat()
    query: dict[str, Any] = {"status": {"$in": sorted(RUN_ACTIVE_STATUSES)}}
    if provider:
        query["provider"] = provider
    stale = list(_db()[RUNS_COL].find({**query, "updated_at": {"$lt": cutoff}}, {"_id": 0}))
    if stale:
        _db()[RUNS_COL].update_many(
            {"run_id": {"$in": [r["run_id"] for r in stale]}},
            {"$set": {"status": "blocked", "outcome": "blocked", "blocker": "stale_after_restart", "updated_at": _now()}},
        )
    active = list_active_runs(provider=provider, limit=50)
    return {"ok": True, "active_runs": active, "stale_marked": [r["run_id"] for r in stale]}


def external_repair_agent_run_task(
    provider: str,
    task_id: str,
    *,
    dry_run: bool = True,
    allow_external_spend: bool = False,
    approval_id: str = "",
) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    capability = detect_provider(provider)
    budget = _budget_allows(provider)
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": provider, "task_id": task_id, "capability": capability, "budget": budget}
    if provider == "digitalocean-amd-cloud":
        if not allow_external_spend or not approval_id.strip():
            return {"ok": False, "error": "external_spend_approval_required", "provider": provider, "task_id": task_id}
        if capability.get("status") != "ready":
            return {"ok": False, "error": "provider_not_ready", "capability": capability}
        if not budget.get("ok"):
            return {"ok": False, **budget}
        return record_external_repair_run(
            provider=provider,
            task_id=task_id,
            outcome="admitted_cloud_burst_not_created_by_repair_agent",
            chargeable=False,
            evidence={
                "approval_id": approval_id,
                "note": "Admission succeeded. Use digitalocean_create_gpu_droplet with the same approval_id plus active apply window to create the ephemeral node.",
            },
        )
    if not allow_external_spend or not approval_id.strip():
        return {"ok": False, "error": "external_spend_approval_required", "provider": provider, "task_id": task_id}
    if capability.get("status") != "ready":
        return {"ok": False, "error": "provider_not_ready", "capability": capability}
    if not budget.get("ok"):
        return {"ok": False, **budget}
    return record_external_repair_run(
        provider=provider,
        task_id=task_id,
        outcome="admitted_not_executed_by_mcp",
        chargeable=False,
        evidence={"approval_id": approval_id, "note": "MCP admission succeeded; execution adapter must run inside isolated worktree worker."},
    )
