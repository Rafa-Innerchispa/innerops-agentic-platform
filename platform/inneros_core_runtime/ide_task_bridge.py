"""Durable IDE task bridge for Antigravity, Cursor, Codex and Gemini.

The bridge intentionally separates *delivery* from *execution*.  An IDE inbox
message proves only that the task was delivered to the canonical InnerOS bus.
Claim/running/completed are explicit transitions backed by Mongo/RACB.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Protocol

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
        priority=priority, from_agent=from_agent, correlation_id=cid, related_project=repo or None,
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
