"""Estado vivo de coordinación — proyección de observabilidad e inventario operativo.

Arquitectura Canónica Congelada:
- Temporal es la única autoridad del lifecycle de tareas.
- Mongo es proyección de lectura, búsqueda, evidencia, histórico e inventario.
- NATS JetStream es el bus durable de eventos y mensajes.
- Coordination Live proyecta el estado operativo real sin ocultar anomalías ni estados terminales relevantes.
"""

from __future__ import annotations

import re
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from pymongo import MongoClient

from raphiia_openai import mongo_store
from raphiia_openai.settings import COL_AGENT_MESSAGES, COORD_ROOT

STATE_KEY = "coordination_live"
OPS_TASKS_COL = "ralfia_ops_tasks"
RUNS_COL = "ralfia_external_repair_runs"
ESTADO_VIVO_PATH = COORD_ROOT / "HUB" / "ESTADO_VIVO.md"

MANDATORY_READS: tuple[str, ...] = (
    "00_LEER_PRIMERO.md",
    "HUB/ESTADO_VIVO.md",
    "HUB/RUNBOOK_COTIZACION_WHATSAPP.md",
    "PROTOCOLO_COMUNICACION_IAS_2026-07-11.md",
    "ESTADO_ACTUAL.md",
    "OPEN_QUESTIONS.md",
)

ASSIGNEES = frozenset({"cursor", "codex", "antigravity", "chatgpt", "gemini", "notion", "ralfia", "rafael"})
COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
SHA_EVIDENCE_KEYS = ("remote_commit_sha", "commit_sha", "commit", "sha", "merge_sha", "pr_merge_sha")


def _status_event_type(status: str) -> str:
    normalized = (status or "").strip().lower()
    return {
        "proposed": "task.created",
        "queued": "task.queued",
        "dispatched": "task.dispatched",
        "worker_starting": "task.worker_starting",
        "claimed": "task.claimed",
        "accepted": "task.claimed",
        "running": "task.running",
        "in_progress": "task.running",
        "verification": "task.verification",
        "blocked": "task.blocked",
        "completed": "task.completed",
        "failed": "task.failed",
        "cancelled": "task.cancelled",
        "superseded": "task.superseded",
    }.get(normalized, "task.heartbeat")


def _publish_task_event(
    event_type: str,
    task: dict[str, Any],
    *,
    actor: str,
    status: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        from inneros_core_runtime import durable_coordination_spine

        return durable_coordination_spine.publish_event(
            event_type,
            actor=(actor or "system").strip().lower(),
            task_id=str(task.get("task_id") or ""),
            correlation_id=str(task.get("correlation_id") or ""),
            repo=str(task.get("repo") or task.get("related_project") or ""),
            provider=str(task.get("preferred_provider") or task.get("provider_transport") or ""),
            model=str(task.get("preferred_model") or ""),
            status=status or str(task.get("status") or ""),
            payload=payload or {},
        )
    except Exception as exc:
        try:
            mongo_store.log_sync(
                "durable_coordination_event_failed",
                task_id=task.get("task_id"),
                correlation_id=task.get("correlation_id"),
                event_type=event_type,
                error=str(exc)[:500],
            )
        except Exception:
            pass
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_display() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _task_id() -> str:
    return f"ops_{secrets.token_hex(6)}"


def bump_revision(*, reason: str, source: str = "system", current_priority: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _now()
    now_d = _now_display()
    state = mongo_store.get_coordination_state(STATE_KEY)
    st = (state.get("state") or {}) if state.get("ok") else {}
    rev = int(st.get("revision") or 0) + 1
    new_state = {
        **st,
        "revision": rev,
        "updated_at": now,
        "updated_at_display": now_d,
        "reason": reason,
        "last_bump_source": source,
        "agent_acks": {},
    }
    if current_priority is not None:
        new_state["current_priority"] = current_priority
    mongo_store.save_coordination_state(STATE_KEY, new_state)
    return {"ok": True, "revision": rev, "updated_at": now, "reason": reason}


def _unread_messages() -> dict[str, int]:
    try:
        db = mongo_store.get_db()
        pipeline = [
            {"$match": {"status": {"$in": ["open", "unread", "pending", "delivered"]}}},
            {"$group": {"_id": {"$ifNull": ["$recipient", "$to"]}, "count": {"$sum": 1}}},
        ]
        results = list(db[COL_AGENT_MESSAGES].aggregate(pipeline))
        return {r["_id"]: r["count"] for r in results if r["_id"]}
    except Exception:
        return {}


def get_coordination_live() -> dict[str, Any]:
    """Proyección viva de observabilidad de InnerOS según la matriz canónica congelada."""
    state = mongo_store.get_coordination_state(STATE_KEY)
    st = (state.get("state") or {}) if state.get("ok") else {}
    rev = int(st.get("revision") or 0)
    unread = _unread_messages()
    acks = st.get("agent_acks") or {}

    db = mongo_store.get_db()
    all_tasks = list(db[OPS_TASKS_COL].find({}, {"_id": 0}))
    all_runs = list(db[RUNS_COL].find({}, {"_id": 0}))
    all_msgs = list(db[COL_AGENT_MESSAGES].find({}, {"_id": 0}))

    active_tasks = []
    waiting_or_blocked = []
    in_verification = []
    failed_tasks = []
    completed_recently = []
    completed_with_unread_handoff = []
    tasks_missing_required_evidence = []
    duplicate_execution_anomalies = []
    stale_workers = []

    now_dt = datetime.now(timezone.utc)
    recent_cutoff = (now_dt - timedelta(hours=24)).isoformat()

    # Map tasks
    task_map = {t.get("task_id"): t for t in all_tasks if t.get("task_id")}

    # Map unread messages by task_id
    unread_by_task = {}
    for m in all_msgs:
        if m.get("status") in ["open", "unread", "pending", "delivered"]:
            tid = m.get("task_id")
            if tid:
                unread_by_task.setdefault(tid, []).append(m)

    # Categorize tasks
    for t in all_tasks:
        tid = t.get("task_id", "")
        status = (t.get("status") or "").lower()
        updated_at = t.get("updated_at") or t.get("created_at") or ""

        if status in ["running", "in_progress", "claimed", "dispatched", "worker_starting"]:
            active_tasks.append(t)
            # Check stale heartbeat (> 300s)
            last_hb = t.get("last_heartbeat_at") or t.get("started_at")
            if last_hb:
                try:
                    hb_dt = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                    if (now_dt - hb_dt).total_seconds() > 300:
                        stale_workers.append({"task_id": tid, "last_heartbeat": last_hb, "stale_seconds": (now_dt - hb_dt).total_seconds()})
                except Exception:
                    pass
        elif status in ["blocked", "waiting", "queued", "pending_human_review"]:
            waiting_or_blocked.append(t)
        elif status in ["verification"]:
            in_verification.append(t)
        elif status in ["failed", "verification_failed"]:
            failed_tasks.append(t)
        elif status in ["completed"]:
            if updated_at >= recent_cutoff:
                completed_recently.append(t)
            if tid in unread_by_task:
                completed_with_unread_handoff.append({
                    "task_id": tid,
                    "title": t.get("title"),
                    "completed_at": updated_at,
                    "unread_messages_count": len(unread_by_task[tid]),
                    "unread_recipients": [m.get("recipient") or m.get("to") for m in unread_by_task[tid]]
                })
            # Check required evidence
            req_ev = t.get("evidence_required") or []
            if req_ev and not t.get("evidence"):
                tasks_missing_required_evidence.append(tid)

    # Detect duplicate runs / anomalies
    runs_by_task = {}
    for r in all_runs:
        tid = r.get("task_id")
        if tid:
            runs_by_task.setdefault(tid, []).append(r)

    orphaned_runs = []
    for tid, rlist in runs_by_task.items():
        running_runs = [r for r in rlist if r.get("status") == "running"]
        completed_runs = [r for r in rlist if r.get("status") == "completed"]
        
        # Anomaly: both running and completed runs, or > 1 running runs
        if len(running_runs) > 1 or (running_runs and completed_runs):
            duplicate_execution_anomalies.append({
                "task_id": tid,
                "running_runs_count": len(running_runs),
                "completed_runs_count": len(completed_runs),
                "run_ids": [r.get("run_id") for r in rlist]
            })
        
        # Orphaned: running run for a completed or non-existent parent task
        parent = task_map.get(tid)
        if parent and parent.get("status") in ["completed", "failed", "cancelled"]:
            for rr in running_runs:
                orphaned_runs.append({"run_id": rr.get("run_id"), "task_id": tid, "parent_status": parent.get("status")})

    # Unacknowledged handoffs
    unacknowledged_handoffs = [
        {
            "message_id": m.get("message_id") or m.get("_id"),
            "task_id": m.get("task_id"),
            "sender": m.get("sender") or m.get("from"),
            "recipient": m.get("recipient") or m.get("to"),
            "subject": m.get("subject"),
            "status": m.get("status"),
            "created_at": m.get("created_at")
        }
        for m in all_msgs if m.get("status") in ["open", "unread", "pending", "delivered"]
    ]

    return {
        "ok": True,
        "revision": rev,
        "updated_at": st.get("updated_at"),
        "updated_at_display": st.get("updated_at_display"),
        "reason": st.get("reason"),
        "mandatory_reads": list(MANDATORY_READS),
        "estado_vivo_path": "HUB/ESTADO_VIVO.md",
        "unread_messages": unread,
        "open_ops_count": len(active_tasks) + len(waiting_or_blocked) + len(in_verification),
        "agent_acks": acks,
        "current_priority": st.get("current_priority"),
        # Consolidated 11 Projection Sections
        "projections": {
            "active_tasks": active_tasks,
            "waiting_or_blocked": waiting_or_blocked,
            "in_verification": in_verification,
            "failed_tasks": failed_tasks,
            "completed_recently": completed_recently,
            "completed_with_unread_handoff": completed_with_unread_handoff,
            "orphaned_runs": orphaned_runs,
            "duplicate_execution_anomalies": duplicate_execution_anomalies,
            "tasks_missing_required_evidence": tasks_missing_required_evidence,
            "stale_workers": stale_workers,
            "unacknowledged_handoffs": unacknowledged_handoffs,
        }
    }


def ack_coordination_revision(agent: str, revision: int) -> dict[str, Any]:
    agent_n = (agent or "").strip().lower()
    if not agent_n:
        return {"ok": False, "error": "agent required"}
    state = mongo_store.get_coordination_state(STATE_KEY)
    st = (state.get("state") or {}) if state.get("ok") else {}
    current_rev = int(st.get("revision") or 0)
    if revision != current_rev:
        return {"ok": False, "error": f"revision mismatch: current is {current_rev}, got {revision}"}
    acks = st.get("agent_acks") or {}
    acks[agent_n] = {"revision": revision, "acked_at": _now(), "acked_at_display": _now_display()}
    new_state = {**st, "agent_acks": acks}
    mongo_store.save_coordination_state(STATE_KEY, new_state)
    return {"ok": True, "agent": agent_n, "revision": revision, "acked_at": acks[agent_n]["acked_at"]}


def list_ops_tasks(
    *,
    task_id: str | None = None,
    correlation_id: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    assignee: str | None = None,
    status: str | None = None,
    date: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Superficie canónica de búsqueda de tareas en la proyección de MongoDB."""
    db = mongo_store.get_db()
    query: dict[str, Any] = {}
    if task_id:
        query["task_id"] = task_id
    if correlation_id:
        query["correlation_id"] = correlation_id
    if project:
        query["$or"] = [{"project_id": project}, {"related_project": project}]
    if repo:
        query["repo"] = repo
    if assignee:
        query["$or"] = [{"assignee": assignee.lower()}, {"assigned_to": assignee.lower()}, {"owner": assignee.lower()}]
    if status:
        query["status"] = status.lower()
    if date:
        query["created_at"] = {"$regex": f"^{date}"}
    if workflow_id:
        query["$or"] = [{"workflow_id": workflow_id}, {"evidence.workflow_id": workflow_id}]
    if run_id:
        query["$or"] = [{"run_id": run_id}, {"evidence.run_id": run_id}]

    tasks = list(db[OPS_TASKS_COL].find(query, {"_id": 0}).sort("created_at", -1).limit(limit))
    return {
        "ok": True,
        "count": len(tasks),
        "tasks": tasks,
        "query": query,
    }


def create_ops_task(
    assignee: str,
    title: str,
    *,
    checklist: list[str] | str | None = None,
    evidence_required: list[str] | str | None = None,
    priority: str = "normal",
    from_agent: str = "RAFAEL",
    correlation_id: str | None = None,
    project_id: str | None = None,
    repo: str | None = None,
    base_ref: str | None = None,
    work_branch: str | None = None,
    task_class: str | None = None,
    execution_lane: str | None = None,
    provider_transport: str | None = None,
    runtime_profile: str | None = None,
    execution_policy: str | None = None,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Admit a task through Temporal, the only lifecycle authority."""
    tid = (
        f"ops_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]}"
        if idempotency_key
        else _task_id()
    )
    now = _now()
    workflow_id = f"ops_task:{tid}"
    doc = {
        "task_id": tid,
        "workflow_id": workflow_id,
        "title": title,
        "assignee": assignee.lower(),
        "assigned_to": assignee.lower(),
        "owner": assignee.lower(),
        "from_agent": from_agent,
        "priority": priority.lower(),
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "correlation_id": correlation_id or tid,
        "project_id": project_id,
        "repo": repo,
        "base_ref": base_ref or "main",
        "work_branch": work_branch,
        "task_class": task_class or "coding",
        "execution_lane": execution_lane or "internal",
        "provider_transport": provider_transport or "mcp",
        "runtime_profile": runtime_profile or "python-tests",
        "execution_policy": execution_policy or "local_first",
        "preferred_provider": preferred_provider or assignee.lower(),
        "preferred_model": preferred_model,
        "idempotency_key": idempotency_key or f"idem_{tid}",
        "checklist": [checklist] if isinstance(checklist, str) else (checklist or []),
        "evidence_required": [evidence_required] if isinstance(evidence_required, str) else (evidence_required or []),
        "evidence": {},
        "revision": 1,
    }

    from inneros_core_runtime import durable_coordination_spine

    started = durable_coordination_spine.start_task_workflow(doc)
    if not started.get("ok"):
        return {
            "ok": False,
            "error": "temporal_task_admission_failed",
            "task_id": tid,
            "workflow_id": workflow_id,
            "details": started,
        }
    doc["run_id"] = started.get("run_id")
    _publish_task_event(
        "task.created",
        doc,
        actor=from_agent,
        status="queued",
        payload={"workflow_id": workflow_id, "run_id": started.get("run_id")},
    )
    bump_revision(reason=f"create_ops_task: {tid}", source=from_agent)
    return {
        "ok": True,
        "task_id": tid,
        "workflow_id": workflow_id,
        "run_id": started.get("run_id"),
        "authority": "temporal",
        "task": doc,
    }


def heartbeat_ops_task(
    task_id: str,
    *,
    actor: str,
    phase: str = "",
    current_step: str = "",
    last_progress: str = "",
    attempt: int = 1,
    next_action: str | None = None,
    blocker: str | None = None,
    files_touched: list[str] | None = None,
) -> dict[str, Any]:
    """Send a worker heartbeat to the canonical Temporal workflow."""
    now = _now()
    hb_data = {
        "actor": actor,
        "at": now,
        "phase": phase,
        "current_step": current_step,
        "last_progress": last_progress,
        "attempt": attempt,
        "next_action": next_action,
        "blocker": blocker,
        "files_touched": files_touched or [],
    }
    from inneros_core_runtime import durable_coordination_spine

    signalled = durable_coordination_spine.signal_task_workflow(task_id, "heartbeat", hb_data)
    return {
        **signalled,
        "heartbeat": hb_data,
        "authority": "temporal",
    }


def update_ops_task_state(
    task_id: str,
    status: str,
    *,
    actor: str = "system",
    evidence: dict[str, Any] | None = None,
    expected_revision: int | None = None,
    force_handoff: bool = False,
) -> dict[str, Any]:
    """Route lifecycle commands to Temporal; never write task state directly."""
    normalized = (status or "").strip().lower()
    from inneros_core_runtime import durable_coordination_spine

    if normalized in {"cancelled", "canceled"}:
        reason = str((evidence or {}).get("reason") or f"cancelled by {actor}")
        return durable_coordination_spine.signal_task_workflow(task_id, "cancel", reason)
    if normalized in {"approved", "approve"}:
        return durable_coordination_spine.signal_task_workflow(
            task_id,
            "approve",
            {
                "actor": actor,
                "evidence": evidence or {},
                "expected_revision": expected_revision,
            },
        )
    if normalized in {"verification", "candidate_result"}:
        return durable_coordination_spine.signal_task_workflow(
            task_id,
            "record_candidate_result",
            {
                "result": normalized,
                "actor": actor,
                "evidence": evidence or {},
                "expected_revision": expected_revision,
            },
        )
    return {
        "ok": False,
        "error": "temporal_owns_task_lifecycle",
        "task_id": task_id,
        "requested_status": normalized,
        "allowed_commands": ["cancelled", "approved", "verification"],
        "authority": "temporal",
    }


def complete_ops_task(
    task_id: str,
    *,
    status: str = "completed",
    actor: str = "system",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject direct completion; only the Temporal verification gate may close."""
    return {
        "ok": False,
        "error": "direct_completion_forbidden",
        "task_id": task_id,
        "requested_status": status,
        "authority": "temporal",
        "next_action": "submit candidate evidence to the running workflow",
    }
