"""Durable IDE task bridge for Antigravity, Cursor, Codex and Gemini.

The bridge intentionally separates *delivery* from *execution*.  An IDE inbox
message proves only that the task was delivered to the canonical InnerOS bus.
Claim/running/completed are explicit transitions backed by Mongo/RACB.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from inneros_core_runtime import agent_identity

IDE_DISPATCH_COL = "ralfia_ide_task_dispatches"
SUPPORTED_IDES = frozenset({"antigravity", "cursor", "codex", "gemini"})
ALIASES = {
    "anti-gravity": "antigravity", "anti_gravity": "antigravity", "antigravit": "antigravity",
    "google-antigravity": "antigravity", "google_antigravity": "antigravity",
    "vscode-gemini": "gemini", "gemini-cli": "gemini", "gemini_cli": "gemini",
    "cursor-ide": "cursor", "codex-cli": "codex", "codex_cli": "codex",
}
TERMINAL = frozenset({"completed", "failed", "cancelled", "rejected"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_ide(value: str) -> str:
    key = str(value or "").strip().lower().replace(" ", "-")
    return ALIASES.get(key, key)


def _trace_id(correlation_id: str, ide: str, title: str) -> str:
    raw = f"{correlation_id}|{ide}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


class Store(Protocol):
    def get_by_key(self, key: str) -> dict[str, Any] | None: ...
    def get(self, dispatch_id: str) -> dict[str, Any] | None: ...
    def put(self, record: dict[str, Any]) -> None: ...


class MongoStore:
    def _col(self):
        from raphiia_openai import mongo_store
        return mongo_store.get_db()[IDE_DISPATCH_COL]

    def get_by_key(self, key: str) -> dict[str, Any] | None:
        return self._col().find_one({"idempotency_key": key}, {"_id": 0})

    def get(self, dispatch_id: str) -> dict[str, Any] | None:
        return self._col().find_one({"dispatch_id": dispatch_id}, {"_id": 0})

    def put(self, record: dict[str, Any]) -> None:
        self._col().update_one({"dispatch_id": record["dispatch_id"]}, {"$set": dict(record)}, upsert=True)


def _provider_status(ide: str) -> dict[str, Any]:
    try:
        from raphiia_openai import external_repair_agent
        out = external_repair_agent.external_repair_agent_status(provider=ide)
        providers = ((out.get("matrix") or {}).get("providers") or []) if isinstance(out, dict) else []
        provider = providers[0] if providers else {}
        return {
            "provider": ide,
            "installed": bool(provider.get("installed")),
            "headless_supported": bool(provider.get("headless_supported")),
            "auth_ready": bool(provider.get("auth_ready")),
            "provider_status": provider.get("status") or "unknown",
        }
    except Exception as exc:
        return {"provider": ide, "installed": False, "headless_supported": False, "auth_ready": False, "provider_status": "unknown", "error": type(exc).__name__}


def dispatch_task(
    *, ide: str, title: str, body: str, repo: str = "", branch: str = "", worktree: str = "",
    correlation_id: str = "", priority: str = "p0", from_agent: str = "CHATGPT_A",
    require_evidence: bool = True, approval_required: bool = False,
    idempotency_key: str = "", store: Store | None = None,
) -> dict[str, Any]:
    target = normalize_ide(ide)
    if target not in SUPPORTED_IDES:
        return {"ok": False, "error": "unsupported_ide", "ide": target, "supported": sorted(SUPPORTED_IDES)}
    clean_title, clean_body = str(title or "").strip(), str(body or "").strip()
    if not clean_title or not clean_body:
        return {"ok": False, "error": "title_and_body_required"}
    cid = str(correlation_id or "").strip() or f"ide-{target}-{secrets.token_hex(6)}"
    sender_identity = agent_identity.identity_from_payload(from_agent)
    target_identity = agent_identity.normalize_actor(target, role="ide")
    idem = str(idempotency_key or "").strip() or hashlib.sha256(f"{target}|{cid}|{clean_title}|{repo}|{branch}".encode()).hexdigest()[:32]
    store = store or MongoStore()
    existing = store.get_by_key(idem)
    if existing:
        return {"ok": True, "created": False, "idempotent": True, **existing}

    from raphiia_openai import coordination_live
    created = coordination_live.create_ops_task(
        assignee=target, title=clean_title,
        checklist=[clean_body, f"IDE target={target}", "Claim task before editing", "Use isolated worktree/RACB when repo writes are required"],
        evidence_required=["status OK/PARTIAL/FAIL", "commit/tests/evidence refs"] if require_evidence else ["status OK/PARTIAL/FAIL"],
        priority=priority, from_agent=sender_identity["actor_id"], correlation_id=cid, related_project=repo or None,
    )
    if not created.get("ok"):
        return {"ok": False, "error": "ops_task_create_failed", "details": created}
    task_id = str(created.get("task_id") or (created.get("task") or {}).get("task_id") or "")
    provider = _provider_status(target)
    dispatch_id = f"ide_{secrets.token_hex(8)}"
    trace_id = _trace_id(cid, target, clean_title)
    transport = "external_repair" if provider.get("installed") and provider.get("headless_supported") and provider.get("auth_ready") else "ide_inbox"
    record = {
        "dispatch_id": dispatch_id, "idempotency_key": idem, "ide": target,
        "from_identity": sender_identity, "target_identity": target_identity,
        "ops_task_id": task_id, "correlation_id": cid, "trace_id": trace_id,
        "title": clean_title, "repo": repo, "branch": branch, "worktree": worktree,
        "transport": transport, "delivery_state": "delivered_to_inbox", "execution_state": "queued",
        "approval_required": bool(approval_required), "require_evidence": bool(require_evidence),
        "provider": provider, "created_at": _now(), "updated_at": _now(),
        "claimed_at": None, "claimed_by": None, "completed_at": None, "evidence": {},
    }
    store.put(record)
    return {"ok": True, "created": True, "idempotent": False, **record,
            "note": "delivery_state proves inbox delivery only; execution_state remains queued until IDE claim"}


def task_status(dispatch_id: str, store: Store | None = None) -> dict[str, Any]:
    store = store or MongoStore()
    rec = store.get(str(dispatch_id or "").strip())
    if not rec:
        return {"ok": False, "error": "ide_dispatch_not_found", "dispatch_id": dispatch_id}
    try:
        from raphiia_openai import coordination_live, mongo_store
        task = mongo_store.get_db()[coordination_live.OPS_TASKS_COL].find_one({"task_id": rec.get("ops_task_id")}, {"_id": 0}) or {}
        rec = {**rec, "ops_status": task.get("status"), "ops_owner": task.get("owner"), "ops_evidence": task.get("evidence") or {}}
    except Exception:
        pass
    return {"ok": True, **rec, "terminal": rec.get("execution_state") in TERMINAL}


def claim_task(dispatch_id: str, ide: str, store: Store | None = None) -> dict[str, Any]:
    target = normalize_ide(ide)
    store = store or MongoStore()
    rec = store.get(str(dispatch_id or "").strip())
    if not rec:
        return {"ok": False, "error": "ide_dispatch_not_found"}
    if target != rec.get("ide"):
        return {"ok": False, "error": "ide_identity_mismatch", "expected": rec.get("ide"), "got": target}
    state = rec.get("execution_state")
    if state in TERMINAL:
        return {"ok": False, "error": "terminal_dispatch", "execution_state": state}
    if state in {"claimed", "running"}:
        return {"ok": True, "idempotent": True, **rec}
    now = _now()
    updated = {**rec, "execution_state": "claimed", "claimed_at": now, "claimed_by": target, "updated_at": now}
    store.put(updated)
    try:
        from raphiia_openai import coordination_live
        coordination_live.update_ops_task_state(rec["ops_task_id"], "accepted", target)
    except Exception:
        pass
    return {"ok": True, "idempotent": False, **updated}


def mark_running(dispatch_id: str, ide: str, store: Store | None = None) -> dict[str, Any]:
    target = normalize_ide(ide); store = store or MongoStore(); rec = store.get(str(dispatch_id or "").strip())
    if not rec: return {"ok": False, "error": "ide_dispatch_not_found"}
    if target != rec.get("ide"): return {"ok": False, "error": "ide_identity_mismatch"}
    if rec.get("execution_state") in TERMINAL: return {"ok": False, "error": "terminal_dispatch"}
    if rec.get("execution_state") == "queued":
        claimed = claim_task(dispatch_id, target, store=store)
        if not claimed.get("ok"): return claimed
        rec = store.get(dispatch_id) or rec
    updated = {**rec, "execution_state": "running", "updated_at": _now()}; store.put(updated)
    try:
        from raphiia_openai import coordination_live
        coordination_live.update_ops_task_state(rec["ops_task_id"], "in_progress", target)
    except Exception: pass
    return {"ok": True, **updated}


def complete_task(dispatch_id: str, ide: str, result: str = "completed", evidence: dict[str, Any] | None = None, store: Store | None = None) -> dict[str, Any]:
    target = normalize_ide(ide); store = store or MongoStore(); rec = store.get(str(dispatch_id or "").strip())
    if not rec: return {"ok": False, "error": "ide_dispatch_not_found"}
    if target != rec.get("ide"): return {"ok": False, "error": "ide_identity_mismatch"}
    final = str(result or "completed").strip().lower()
    if final not in TERMINAL: return {"ok": False, "error": "invalid_terminal_state", "allowed": sorted(TERMINAL)}
    ev = evidence or {}
    if rec.get("require_evidence") and final == "completed" and not ev:
        return {"ok": False, "error": "evidence_required_for_completed"}
    now = _now(); updated = {**rec, "execution_state": final, "completed_at": now, "updated_at": now, "evidence": ev}; store.put(updated)
    try:
        from raphiia_openai import coordination_live
        ops_state = "completed" if final == "completed" else ("cancelled" if final == "cancelled" else "failed")
        coordination_live.update_ops_task_state(rec["ops_task_id"], ops_state, target, evidence=ev, force_handoff=True)
    except Exception: pass
    return {"ok": True, **updated, "terminal": True}


def bridge_status() -> dict[str, Any]:
    return {"ok": True, "service": "inneros-ide-task-bridge", "supported_ides": sorted(SUPPORTED_IDES),
            "source_of_truth": "ralfia_ops_tasks + ralfia_agent_messages + ralfia_ide_task_dispatches",
            "semantics": {"delivery_state": "message reached canonical IDE inbox", "execution_state": "queued|claimed|running|completed|failed|cancelled|rejected"},
            "providers": {ide: _provider_status(ide) for ide in sorted(SUPPORTED_IDES)}}

# Compatibility surface for the unified ACP/IDE fabric.  The durable bridge above
# remains canonical for real execution; these helpers project the same lifecycle
# into Cursor ACP/A2A terminology without treating inbox delivery as completion.
BRIDGE_VERSION = "ide_task_bridge_v1"
SUPPORTED_TARGETS = tuple(sorted(SUPPORTED_IDES))
IDE_CLAIMED_STATES = frozenset({"accepted", "dispatched"})
IDE_RUNNING_STATES = frozenset({"in_progress", "working", "verification"})
IDE_TERMINAL_STATES = TERMINAL | frozenset({"canceled", "superseded"})
INBOX_PATHS = {
    "cursor": "cursor/INBOX.md",
    "codex": "codex/INBOX.md",
    "antigravity": "antigravity/INBOX.md",
    "gemini": "gemini/INBOX.md",
    "chatgpt": "chatgpt/INBOX.md",
}
DispatchStore = dict[str, dict[str, Any]]


def normalize_target(target: str) -> str:
    aliases = {"chatgpt": "gemini", "chatgpt_a": "gemini", "google": "gemini", "cursor_ide": "cursor"}
    return aliases.get(str(target or "").strip().lower(), normalize_ide(target))


def _fabric_idempotency_key(*, target: str, correlation_id: str, title: str) -> str:
    blob = f"{target}|{correlation_id}|{title}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:24]


def project_execution_state(*, ops_status: str = "", a2a_status: dict[str, Any] | None = None, target: str = "cursor") -> dict[str, Any]:
    target_id = normalize_target(target)
    if target_id not in SUPPORTED_IDES:
        return {"ok": False, "error": "unsupported_ide", "target": target, "supported": sorted(SUPPORTED_IDES)}
    a2a_state = ""
    if a2a_status:
        status = a2a_status.get("status") or {}
        a2a_state = str(status.get("state") or a2a_status.get("state") or "")
    ops = (ops_status or str((a2a_status or {}).get("ops_status") or "")).strip().lower()
    combined = {a2a_state.lower(), ops}
    delivered = bool(a2a_status) or bool(ops)
    claimed = bool(combined & IDE_CLAIMED_STATES)
    running = bool(combined & IDE_RUNNING_STATES)
    terminal = bool(combined & IDE_TERMINAL_STATES)
    completed = "completed" in combined and not (a2a_status or {}).get("integrity_error")
    execution_state = "queued"
    if completed:
        execution_state = "completed"
    elif terminal:
        execution_state = "failed" if "failed" in combined else "canceled"
    elif running:
        execution_state = "running"
    elif claimed:
        execution_state = "claimed"
    elif delivered:
        execution_state = "delivered_to_inbox"
    return {
        "ok": True,
        "target": target_id,
        "transport": "a2a|ide_inbox",
        "delivered_to_inbox": delivered,
        "claimed": claimed or running or terminal,
        "running": running,
        "completed": completed,
        "execution_state": execution_state,
        "a2a_state": a2a_state,
        "ops_status": ops,
        "duplicates_ide_bridge": False,
    }


def dispatch_ide_task(
    *,
    title: str,
    body: str,
    target: str,
    correlation_id: str = "",
    ops_task_id: str = "",
    repo: str = "Rafa-Innerchispa/innerops-agentic-platform",
    branch: str = "",
    worktree: str = "",
    transport: str = "ide_inbox",
    dry_run: bool = False,
    store: DispatchStore | None = None,
    message_writer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target_id = normalize_target(target)
    if target_id not in SUPPORTED_IDES:
        return {"ok": False, "error": "unsupported_ide", "target": target, "supported": sorted(SUPPORTED_IDES)}
    try:
        from inneros_core_runtime.tracking_envelope import build_envelope
        envelope = build_envelope(
            agent=target_id,
            provider="inneros-ide-bridge",
            correlation_id=correlation_id,
            branch=branch,
            worktree=worktree,
            repo=repo,
            extra={"ops_task_id": ops_task_id, "transport": transport},
        )
        corr = str(envelope["correlation_id"])
    except Exception:
        corr = str(correlation_id or "").strip() or f"ide-{target_id}"
        envelope = {"correlation_id": corr, "traceparent": _trace_id(corr, target_id, title)}
    idem = _fabric_idempotency_key(target=target_id, correlation_id=corr, title=title)
    bucket = store if store is not None else {}
    if idem in bucket:
        return {"ok": True, "duplicate": True, "idempotency_key": idem, **bucket[idem]}
    inbox_path = INBOX_PATHS.get(target_id, f"{target_id}/INBOX.md")
    message = {
        "from_agent": "INNEROS",
        "target_agent": target_id,
        "title": title,
        "body": body,
        "correlation_id": corr,
        "ops_task_id": ops_task_id,
        "transport": transport,
        "inbox_path": inbox_path,
        "metadata": {"repo": repo, "branch": branch, "worktree": worktree, "traceparent": envelope.get("traceparent")},
    }
    write_result: dict[str, Any] = {"ok": True, "dry_run": dry_run}
    if not dry_run and message_writer is not None:
        write_result = message_writer(message)
    projection = project_execution_state(
        a2a_status={"status": {"state": "submitted"}, "correlation_id": corr, "envelope": envelope},
        ops_status="proposed",
        target=target_id,
    )
    record = {
        "bridge_version": BRIDGE_VERSION,
        "target": target_id,
        "correlation_id": corr,
        "ops_task_id": ops_task_id,
        "transport": transport,
        "inbox_path": inbox_path,
        "envelope": envelope,
        "message": message,
        "write_result": write_result,
        "execution_projection": projection,
        "delivered_to_inbox": projection.get("delivered_to_inbox"),
        "running": projection.get("running"),
        "completed": projection.get("completed"),
    }
    bucket[idem] = record
    return {"ok": True, "duplicate": False, "idempotency_key": idem, **record}


def mark_ops_progress(*, store: DispatchStore, idempotency_key: str, ops_status: str, a2a_state: str = "") -> dict[str, Any]:
    record = store.get(idempotency_key)
    if not record:
        return {"ok": False, "error": "unknown_dispatch", "idempotency_key": idempotency_key}
    projection = project_execution_state(
        a2a_status={"status": {"state": a2a_state or ops_status}, "correlation_id": record["correlation_id"]},
        ops_status=ops_status,
        target=record["target"],
    )
    record["execution_projection"] = projection
    record["ops_status"] = ops_status
    return {"ok": True, "idempotency_key": idempotency_key, "execution_projection": projection}


# TaskEnvelope v1 hardening.  IDE delivery is not executable until the durable
# ops_task carries an exact verified project binding and a matching IDE lane.
_dispatch_task_without_envelope = dispatch_task
_claim_task_without_envelope_gate = claim_task
_mark_running_without_envelope_gate = mark_running


def _dispatch_binding_gate(record: dict[str, Any], target: str) -> dict[str, Any]:
    envelope = record.get("task_envelope") if isinstance(record.get("task_envelope"), dict) else {}
    status = str(record.get("task_binding_status") or envelope.get("binding_status") or "")
    lane = str(record.get("execution_lane") or envelope.get("execution_lane") or "").strip().lower()
    if status != "verified":
        return {"ok": False, "error": "task_binding_not_verified", "task_binding_status": status or "missing"}
    if lane != target:
        return {"ok": False, "error": "execution_lane_mismatch", "execution_lane": lane or None, "expected_execution_lane": target}
    return {"ok": True, "task_binding_status": status, "execution_lane": lane}


def dispatch_task(
    *,
    ide: str,
    title: str,
    body: str,
    repo: str = "",
    branch: str = "",
    worktree: str = "",
    correlation_id: str = "",
    priority: str = "p0",
    from_agent: str = "CHATGPT_A",
    require_evidence: bool = True,
    approval_required: bool = False,
    idempotency_key: str = "",
    store: Store | None = None,
) -> dict[str, Any]:
    target = normalize_ide(ide)
    effective_store = store or MongoStore()
    result = _dispatch_task_without_envelope(
        ide=ide,
        title=title,
        body=body,
        repo=repo,
        branch=branch,
        worktree=worktree,
        correlation_id=correlation_id,
        priority=priority,
        from_agent=from_agent,
        require_evidence=require_evidence,
        approval_required=approval_required,
        idempotency_key=idempotency_key,
        store=effective_store,
    )
    if not result.get("ok"):
        return result
    dispatch_id = str(result.get("dispatch_id") or "")
    task_id = str(result.get("ops_task_id") or "")
    if not dispatch_id or not task_id:
        return {**result, "ok": False, "error": "dispatch_missing_durable_ids"}

    from inneros_core_runtime import coordination_live

    transport = str(result.get("transport") or "ide_inbox")
    bound = coordination_live.bind_task_envelope(
        task_id,
        repo=str(repo or "").strip(),
        base_ref=str(branch or "main").strip(),
        task_class="coding",
        execution_lane=target,
        provider_transport=transport,
        correlation_id=str(result.get("correlation_id") or correlation_id or ""),
        idempotency_key=str(result.get("idempotency_key") or idempotency_key or ""),
        related_project=str(repo or "").strip(),
        write_capable=True,
        actor=target,
    )
    record = effective_store.get(dispatch_id) or dict(result)
    patched = {
        **record,
        "task_binding_status": bound.get("binding_status"),
        "task_envelope": bound.get("envelope") or {},
        "execution_lane": target,
        "provider_transport": transport,
        "project_id": (bound.get("envelope") or {}).get("project_id"),
        "base_ref": (bound.get("envelope") or {}).get("base_ref") or str(branch or "main").strip(),
        "updated_at": _now(),
    }
    effective_store.put(patched)
    return {
        **result,
        **patched,
        "executable": bool(bound.get("ok")),
        "binding_error": bound.get("error"),
        "binding_missing": bound.get("missing") or [],
    }


def claim_task(dispatch_id: str, ide: str, store: Store | None = None) -> dict[str, Any]:
    target = normalize_ide(ide)
    effective_store = store or MongoStore()
    rec = effective_store.get(str(dispatch_id or "").strip())
    if not rec:
        return {"ok": False, "error": "ide_dispatch_not_found"}
    if target != rec.get("ide"):
        return {"ok": False, "error": "ide_identity_mismatch", "expected": rec.get("ide"), "got": target}
    gate = _dispatch_binding_gate(rec, target)
    if not gate.get("ok"):
        return {**gate, "dispatch_id": dispatch_id, "ide": target}
    return _claim_task_without_envelope_gate(dispatch_id, target, store=effective_store)


def mark_running(dispatch_id: str, ide: str, store: Store | None = None) -> dict[str, Any]:
    target = normalize_ide(ide)
    effective_store = store or MongoStore()
    rec = effective_store.get(str(dispatch_id or "").strip())
    if not rec:
        return {"ok": False, "error": "ide_dispatch_not_found"}
    gate = _dispatch_binding_gate(rec, target)
    if not gate.get("ok"):
        return {**gate, "dispatch_id": dispatch_id, "ide": target}
    return _mark_running_without_envelope_gate(dispatch_id, target, store=effective_store)
