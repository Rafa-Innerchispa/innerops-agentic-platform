"""Registro canónico de ideas, decisiones y trabajo pendiente (Cursor/ChatGPT/servidores).

Colección Mongo: ralfia_dev_backlog

Estados:
  discussed   — se habló, sin compromiso claro
  planned     — decidido hacer
  in_progress — en ejecución
  done        — completado (con evidencia opcional)
  deferred    — pospuesto explícitamente
  forgotten   — hablado pero sin seguimiento (manual o auto stale)
  cancelled   — descartado
  superseded  — reemplazado por otro item
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.settings import COL_DEV_BACKLOG

VALID_STATUSES = frozenset(
    {
        "discussed",
        "planned",
        "in_progress",
        "done",
        "deferred",
        "forgotten",
        "cancelled",
        "superseded",
    }
)
VALID_SOURCES = frozenset({"CURSOR", "CHATGPT", "CODEX", "ANTIGRAVITY", "GEMINI", "RAFAEL", "SYSTEM", "MCP"})
KINDS = frozenset({"idea", "decision", "task", "bug", "architecture", "question"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _item_id() -> str:
    return f"backlog_{secrets.token_hex(6)}"


def _fingerprint(title: str, source: str, project: str | None) -> str:
    norm = re.sub(r"\s+", " ", (title or "").strip().lower())
    key = f"{norm}|{(source or '').upper()}|{(project or '').lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _db():
    return mongo_store.get_db()


def _ensure_indexes() -> None:
    db = _db()
    col = db[COL_DEV_BACKLOG]
    col.create_index("item_id", unique=True)
    col.create_index("fingerprint")
    col.create_index([("status", 1), ("updated_at", -1)])
    col.create_index([("source_agent", 1), ("updated_at", -1)])
    col.create_index([("project", 1), ("status", 1)])
    col.create_index([("conversation_ref", 1)])


def capture_backlog_item(
    *,
    title: str,
    body: str = "",
    status: str = "discussed",
    kind: str = "idea",
    source_agent: str = "SYSTEM",
    project: str | None = None,
    tags: list[str] | None = None,
    conversation_ref: str | None = None,
    ops_task_id: str | None = None,
    evidence: str | None = None,
    related_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    dedupe: bool = True,
) -> dict[str, Any]:
    """Captura un item en el backlog. Con dedupe=True actualiza si ya existe fingerprint."""
    _ensure_indexes()
    status_u = (status or "discussed").strip().lower()
    if status_u not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    kind_u = (kind or "idea").strip().lower()
    if kind_u not in KINDS:
        raise ValueError(f"invalid kind: {kind}")
    source_u = (source_agent or "SYSTEM").strip().upper()
    if source_u not in VALID_SOURCES:
        source_u = "SYSTEM"

    now = _now()
    fp = _fingerprint(title, source_u, project)
    db = _db()
    col = db[COL_DEV_BACKLOG]

    if dedupe:
        existing = col.find_one({"fingerprint": fp, "status": {"$nin": ["cancelled", "superseded"]}})
        if existing:
            updates: dict[str, Any] = {
                "body": (body or existing.get("body") or "").strip(),
                "updated_at": now,
                "last_touched_at": now,
                "ts_display": ralfia_time.format_log(),
            }
            if status_u != "discussed":
                updates["status"] = status_u
            if evidence:
                updates["evidence"] = evidence
            if ops_task_id:
                updates["ops_task_id"] = ops_task_id
            if conversation_ref:
                updates["conversation_ref"] = conversation_ref
            if tags:
                updates["tags"] = sorted(set((existing.get("tags") or []) + tags))
            if metadata:
                updates["metadata"] = {**(existing.get("metadata") or {}), **metadata}
            col.update_one({"_id": existing["_id"]}, {"$set": updates})
            existing.update(updates)
            return {"ok": True, "action": "updated", "item": mongo_store._serialize(existing)}

    doc = {
        "item_id": _item_id(),
        "title": title.strip(),
        "body": body.strip(),
        "status": status_u,
        "kind": kind_u,
        "source_agent": source_u,
        "project": project,
        "tags": tags or [],
        "conversation_ref": conversation_ref,
        "ops_task_id": ops_task_id,
        "evidence": evidence,
        "related_ids": related_ids or [],
        "fingerprint": fp,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
        "last_touched_at": now,
        "ts_display": ralfia_time.format_log(),
    }
    res = col.insert_one(doc)
    doc["_id"] = res.inserted_id
    return {"ok": True, "action": "created", "item": mongo_store._serialize(doc)}


def capture_backlog_batch(items: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for raw in items:
        results.append(capture_backlog_item(**raw))
    created = sum(1 for r in results if r.get("action") == "created")
    updated = sum(1 for r in results if r.get("action") == "updated")
    return {"ok": True, "count": len(results), "created": created, "updated": updated, "results": results}


def finalize_session_handoff(
    *,
    agent: str,
    session_summary: str,
    items: list[dict[str, Any]] | None = None,
    conversation_ref: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Cierre de sesión: log coordinación + backlog batch + activity."""
    agent_u = (agent or "SYSTEM").strip().upper()
    batch = capture_backlog_batch(items or [])
    record_agent_run(
        agent_u,
        action="session_handoff",
        summary=session_summary[:500],
        project=project or "ralfia",
        tool_used="finalize_session_handoff",
        metadata={
            "conversation_ref": conversation_ref,
            "backlog_created": batch.get("created", 0),
            "backlog_updated": batch.get("updated", 0),
            "items_count": batch.get("count", 0),
        },
    )
    mongo_store.log_coordination(
        agent=agent_u,
        summary=session_summary[:500],
        event="session_handoff",
        project=project,
        tool_used="finalize_session_handoff",
        metadata={
            "conversation_ref": conversation_ref,
            "backlog": {"created": batch.get("created"), "updated": batch.get("updated")},
        },
    )
    return {"ok": True, "agent": agent_u, "backlog": batch, "summary_chars": len(session_summary)}


def list_dev_backlog(
    *,
    status: str | None = None,
    source_agent: str | None = None,
    project: str | None = None,
    kind: str | None = None,
    tag: str | None = None,
    stale_days: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    _ensure_indexes()
    db = _db()
    query: dict[str, Any] = {}
    if status:
        query["status"] = status.strip().lower()
    if source_agent:
        query["source_agent"] = source_agent.strip().upper()
    if project:
        query["project"] = project
    if kind:
        query["kind"] = kind.strip().lower()
    if tag:
        query["tags"] = tag
    if stale_days is not None and stale_days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        query.setdefault("status", {"$in": ["discussed", "planned"]})
        query["last_touched_at"] = {"$lt": cutoff}

    limit = max(1, min(int(limit), 200))
    cursor = db[COL_DEV_BACKLOG].find(query).sort("updated_at", -1).limit(limit)
    items = [mongo_store._serialize(d) for d in cursor]
    return {"ok": True, "count": len(items), "items": items, "filter": query}


def update_dev_backlog_item(
    item_id: str,
    *,
    status: str | None = None,
    note: str | None = None,
    evidence: str | None = None,
    ops_task_id: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_indexes()
    if status and status.strip().lower() not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    db = _db()
    col = db[COL_DEV_BACKLOG]
    doc = col.find_one({"item_id": item_id})
    if not doc:
        return {"ok": False, "error": "not_found", "item_id": item_id}

    now = _now()
    updates: dict[str, Any] = {"updated_at": now, "last_touched_at": now, "ts_display": ralfia_time.format_log()}
    if status:
        updates["status"] = status.strip().lower()
    if evidence is not None:
        updates["evidence"] = evidence
    if ops_task_id:
        updates["ops_task_id"] = ops_task_id
    if tags:
        updates["tags"] = sorted(set((doc.get("tags") or []) + tags))
    if note:
        history = list(doc.get("status_history") or [])
        history.append({"at": now, "note": note.strip(), "status": updates.get("status", doc.get("status"))})
        updates["status_history"] = history[-20:]

    col.update_one({"_id": doc["_id"]}, {"$set": updates})
    doc.update(updates)
    return {"ok": True, "item": mongo_store._serialize(doc)}


def get_dev_backlog_summary(*, stale_days: int = 14) -> dict[str, Any]:
    _ensure_indexes()
    db = _db()
    col = db[COL_DEV_BACKLOG]
    total = col.estimated_document_count()
    by_status: dict[str, int] = {}
    for st in VALID_STATUSES:
        by_status[st] = col.count_documents({"status": st})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, stale_days))).isoformat()
    stale = col.count_documents(
        {"status": {"$in": ["discussed", "planned"]}, "last_touched_at": {"$lt": cutoff}}
    )
    recent_done = list(
        col.find({"status": "done"}, {"title": 1, "updated_at": 1, "source_agent": 1})
        .sort("updated_at", -1)
        .limit(8)
    )
    recent_open = list(
        col.find({"status": {"$in": ["discussed", "planned", "in_progress"]}}, {"title": 1, "status": 1, "source_agent": 1})
        .sort("updated_at", -1)
        .limit(12)
    )
    return {
        "ok": True,
        "total": total,
        "by_status": by_status,
        "stale_open_count": stale,
        "stale_days_threshold": stale_days,
        "recent_done": [mongo_store._serialize(d) for d in recent_done],
        "recent_open": [mongo_store._serialize(d) for d in recent_open],
    }


def mark_stale_as_forgotten(*, stale_days: int = 14, dry_run: bool = True) -> dict[str, Any]:
    """Marca items discussed/planned sin tocar en N días como forgotten."""
    _ensure_indexes()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, stale_days))).isoformat()
    db = _db()
    col = db[COL_DEV_BACKLOG]
    query = {"status": {"$in": ["discussed", "planned"]}, "last_touched_at": {"$lt": cutoff}}
    candidates = list(col.find(query, {"item_id": 1, "title": 1, "last_touched_at": 1}).limit(500))
    if dry_run:
        return {"ok": True, "dry_run": True, "would_mark": len(candidates), "items": [mongo_store._serialize(c) for c in candidates[:20]]}
    now = _now()
    res = col.update_many(
        query,
        {"$set": {"status": "forgotten", "updated_at": now, "last_touched_at": now, "ts_display": ralfia_time.format_log()}},
    )
    return {"ok": True, "dry_run": False, "marked": res.modified_count}
