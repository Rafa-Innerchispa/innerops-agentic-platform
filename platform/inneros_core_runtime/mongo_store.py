"""Acceso MongoDB compartida ? conversaciones bridge + editorial."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import MongoClient

from raphiia_openai.settings import (
    COL_CONVERSATIONS,
    COL_COORDINATION_LOG,
    COL_COORDINATION_STATE,
    COL_EDITORIAL_PIPELINE,
    COL_IDEAS,
    COL_MCP_ERROR_LOG,
    COL_MAILBOX_SNAPSHOTS,
    COL_MAILBOX_LATEST,
    COL_MESSAGES,
    COL_MEMORY_ITEMS,
    COL_KNOWLEDGE_SEEDS,
    COL_AGENT_MESSAGES,
    COL_SYNC_LOG,
    HA_STATE_FILE,
    MONGO_DB,
    MONGO_URI,
    MONGO_URI_LOCAL,
    MONGO_URI_PRIMARY,
)
from raphiia_openai import ralfia_time

_client: MongoClient | None = None
_active_mongo_uri: str | None = None

SEARCHABLE = (
    (COL_IDEAS, ("title", "body", "content", "description", "tags")),
    (COL_MESSAGES, ("content", "role", "conversation_id")),
    (COL_EDITORIAL_PIPELINE, ("title", "channel", "markdown", "body", "status")),
    ("clients", ("name", "email", "city", "notas")),
    ("ralfia_ops_tasks", ("task_id", "correlation_id", "title", "checklist", "evidence_required", "assignee", "from_agent", "related_project", "conversation_ref", "source_message_id")),
    (COL_AGENT_MESSAGES, ("message_id", "correlation_id", "task_id", "title", "body", "target_agent", "from_agent", "related_project", "conversation_ref", "tags")),
    (COL_COORDINATION_LOG, ("summary", "event", "project", "tool_used", "metadata")),
    (COL_MEMORY_ITEMS, ("memory_id", "title", "body", "tags", "entities", "source_message_ids", "metadata")),
)


def _candidate_mongo_uris() -> list[str]:
    uris: list[str] = []
    try:
        if HA_STATE_FILE.is_file():
            data = json.loads(HA_STATE_FILE.read_text(encoding="utf-8"))
            preferred = str(data.get("mongo_uri") or "").strip()
            if preferred:
                uris.append(preferred)
    except Exception:
        pass
    for uri in (MONGO_URI_PRIMARY, MONGO_URI, MONGO_URI_LOCAL):
        u = (uri or "").strip()
        if u and u not in uris:
            uris.append(u)
    return uris or [MONGO_URI]


def _pick_mongo_uri() -> str:
    global _active_mongo_uri
    if _active_mongo_uri:
        return _active_mongo_uri
    for uri in _candidate_mongo_uris():
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=2500)
            client.admin.command("ping")
            _active_mongo_uri = uri
            return uri
        except Exception:
            continue
    _active_mongo_uri = MONGO_URI
    return MONGO_URI


def get_db():
    global _client
    uri = _pick_mongo_uri()
    if _client is None:
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _client[MONGO_DB]


def mongo_connection_info() -> dict[str, Any]:
    return {"uri": _pick_mongo_uri(), "db": MONGO_DB}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_fields() -> dict[str, str]:
    return {
        "ts": _now_iso(),
        "ts_local": ralfia_time.now_local_iso(),
        "ts_display": ralfia_time.format_log(),
    }


def _oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except Exception:
        return None


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def ping_mongo() -> dict[str, Any]:
    try:
        db = get_db()
        return {
            "ok": True,
            "db": MONGO_DB,
            "clients": db.clients.count_documents({}),
            "ideas": db[COL_IDEAS].count_documents({}),
            "editorial_pipeline": db[COL_EDITORIAL_PIPELINE].count_documents({}),
            "bridge_conversations": db[COL_CONVERSATIONS].count_documents({}),
            "bridge_messages": db[COL_MESSAGES].count_documents({}),
            "mcp_errors": db[COL_MCP_ERROR_LOG].count_documents({}),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def append_message(
    *,
    conversation_id: str,
    role: str,
    content: str,
    source: str = "chatgpt_mcp",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    now = _now_iso()
    doc = {
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "source": source,
        "metadata": metadata or {},
        "created_at": now,
    }
    db[COL_MESSAGES].insert_one(doc)
    db[COL_CONVERSATIONS].update_one(
        {"conversation_id": conversation_id},
        {
            "$set": {"updated_at": now, "source": source},
            "$setOnInsert": {"conversation_id": conversation_id, "created_at": now},
        },
        upsert=True,
    )
    return _serialize(doc)


def save_idea(
    *,
    title: str,
    body: str,
    tags: list[str] | None = None,
    source: str = "chatgpt_mcp",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    now = _now_iso()
    doc = {
        "title": title.strip(),
        "body": body.strip(),
        "content": body.strip(),
        "tags": tags or [],
        "source": source,
        "status": "new",
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_IDEAS].insert_one(doc)
    doc["_id"] = result.inserted_id
    log_sync("save_idea", idea_id=str(result.inserted_id), title=title[:120])
    return _serialize(doc)


def save_pipeline_draft(
    *,
    channel: str,
    markdown: str,
    title: str | None = None,
    status: str = "draft",
    source: str = "chatgpt_mcp",
    metadata: dict[str, Any] | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    db = get_db()
    now = _now_iso()
    meta = metadata or {}
    ent = (entity_id or meta.get("entity_id") or "").strip()
    doc = {
        "channel": channel.strip(),
        "markdown": markdown.strip(),
        "body": markdown.strip(),
        "title": (title or channel).strip(),
        "status": status,
        "source": source,
        "metadata": meta,
        "created_at": now,
        "updated_at": now,
    }
    if ent:
        doc["entity_id"] = ent
    result = db[COL_EDITORIAL_PIPELINE].insert_one(doc)
    doc["_id"] = result.inserted_id
    log_sync("save_pipeline_draft", pipeline_id=str(result.inserted_id), channel=channel)
    return _serialize(doc)


def list_pipeline(limit: int = 20) -> list[dict[str, Any]]:
    db = get_db()
    limit = max(1, min(int(limit), 100))
    cursor = db[COL_EDITORIAL_PIPELINE].find({}).sort("created_at", -1).limit(limit)
    return [_serialize(doc) for doc in cursor]


def get_context_summary() -> dict[str, Any]:
    db = get_db()
    summary = ping_mongo()
    latest_ideas = list(
        db[COL_IDEAS].find({}, {"title": 1, "created_at": 1, "status": 1}).sort("created_at", -1).limit(5)
    )
    latest_pipeline = list(
        db[COL_EDITORIAL_PIPELINE].find({}, {"title": 1, "channel": 1, "status": 1, "created_at": 1})
        .sort("created_at", -1)
        .limit(5)
    )
    return {
        **summary,
        "latest_ideas": [_serialize(i) for i in latest_ideas],
        "latest_pipeline": [_serialize(p) for p in latest_pipeline],
        "note": "Datos reales de MongoDB pcdoctor_swarm ? sin OpenAI API en servidor.",
    }


def _make_snippet(doc: dict[str, Any], fields: tuple[str, ...], query: str) -> str:
    parts: list[str] = []
    for field in fields:
        value = doc.get(field)
        if isinstance(value, list):
            parts.append(", ".join(str(v) for v in value))
        elif value:
            parts.append(str(value))
    text = " | ".join(parts)
    if not text:
        return ""
    q = query.lower()
    idx = text.lower().find(q[:20]) if q else -1
    if idx >= 0:
        start = max(0, idx - 60)
        return text[start : start + 180]
    return text[:180]


def search(query: str, limit: int = 10, collection: str | None = None) -> list[dict[str, Any]]:
    db = get_db()
    limit = max(1, min(int(limit), 50))
    q = (query or "").strip()
    if not q:
        return []

    regex = re.compile(re.escape(q), re.IGNORECASE)
    results: list[dict[str, Any]] = []

    for coll_name, fields in SEARCHABLE:
        if collection and coll_name != collection:
            continue
        or_filters = [{field: regex} for field in fields]
        docs = list(db[coll_name].find({"$or": or_filters}).limit(limit))
        if not docs:
            tokens = sorted(set(re.findall(r"[a-z0-9áéíóúñ_-]{3,}", q.lower())))[:12]
            token_filters = [{field: re.compile(re.escape(token), re.IGNORECASE)} for token in tokens for field in fields]
            if token_filters:
                candidates = list(db[coll_name].find({"$or": token_filters}).limit(limit * 5))
                candidates.sort(
                    key=lambda doc: sum(token in _make_snippet(doc, fields, q).lower() for token in tokens),
                    reverse=True,
                )
                docs = candidates[:limit]
        for doc in docs:
            oid = str(doc["_id"])
            results.append(
                {
                    "id": f"{coll_name}/{oid}",
                    "collection": coll_name,
                    "title": doc.get("title") or doc.get("name") or doc.get("conversation_id") or oid,
                    "snippet": _make_snippet(doc, fields, q),
                    "created_at": doc.get("created_at"),
                }
            )
            if len(results) >= limit:
                return results
    return results


def fetch(document_id: str) -> dict[str, Any]:
    db = get_db()
    raw = (document_id or "").strip()
    if not raw:
        return {"ok": False, "error": "document_id vac?o"}

    if "/" in raw:
        coll_name, oid_str = raw.split("/", 1)
    else:
        coll_name, oid_str = COL_IDEAS, raw

    oid = _oid(oid_str)
    if oid is None:
        return {"ok": False, "error": f"id inv?lido: {document_id}"}

    doc = db[coll_name].find_one({"_id": oid})
    if not doc:
        return {"ok": False, "error": f"no encontrado: {document_id}"}

    return {"ok": True, "id": f"{coll_name}/{oid_str}", "document": _serialize(doc)}


def log_sync(event: str, **extra: Any) -> None:
    db = get_db()
    db[COL_SYNC_LOG].insert_one({"event": event, **_timestamp_fields(), **extra})


def log_mcp_error(
    *,
    error_type: str,
    tool: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    client: str | None = None,
    message: str,
    stack_excerpt: str | None = None,
    catalog_version: str | None = None,
    scopes: list[str] | None = None,
    resolved: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    doc = {
        **_timestamp_fields(),
        "error_type": error_type,
        "tool": tool,
        "request_id": request_id,
        "session_id": session_id,
        "client": client,
        "message": message,
        "stack_excerpt": stack_excerpt,
        "catalog_version": catalog_version,
        "scopes": scopes or [],
        "resolved": resolved,
        "metadata": metadata or {},
    }
    result = db[COL_MCP_ERROR_LOG].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


def get_mcp_error_log(
    limit: int = 20,
    error_type: str | None = None,
    resolved: bool | None = None,
) -> dict[str, Any]:
    db = get_db()
    limit = max(1, min(int(limit), 100))
    filt: dict[str, Any] = {}
    if error_type:
        filt["error_type"] = error_type
    if resolved is not None:
        filt["resolved"] = bool(resolved)
    cursor = db[COL_MCP_ERROR_LOG].find(filt).sort("ts", -1).limit(limit)
    items = [_serialize(doc) for doc in cursor]
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "filter": filt,
    }


def log_coordination(
    *,
    agent: str,
    summary: str,
    event: str = "development",
    project: str | None = None,
    tool_used: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registro compartido Cursor/Codex/Rafael — colección ralfia_coordination_log."""
    db = get_db()
    doc = {
        **_timestamp_fields(),
        "agent": agent.strip().upper(),
        "event": event,
        "summary": summary.strip(),
        "project": project,
        "tool_used": tool_used,
        "metadata": metadata or {},
    }
    result = db[COL_COORDINATION_LOG].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


def register_change(
    *,
    agent: str,
    project: str,
    path: str,
    summary: str,
    before_hash: str | None = None,
    after_hash: str | None = None,
    service: str | None = None,
    change_type: str = "document_change",
    user: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registro canónico de cambios para el Agente Documental."""
    db = get_db()
    doc = {
        **_timestamp_fields(),
        "agent": agent.strip().upper(),
        "project": project,
        "path": path,
        "service": service,
        "summary": summary,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "change_type": change_type,
        "user": user,
        "metadata": metadata or {},
    }
    result = db[COL_COORDINATION_LOG].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


def list_recent_changes(limit: int = 20, project: str | None = None) -> dict[str, Any]:
    db = get_db()
    limit = max(1, min(int(limit), 100))
    filt: dict[str, Any] = {}
    if project:
        filt["project"] = project
    cursor = db[COL_COORDINATION_LOG].find(filt).sort("ts", -1).limit(limit)
    allowed = {"document_change", "documentation_sync", "mcp_catalog_change", "service_change", "agent_activity", "coordination_auto_sync"}
    items = [
        _serialize(doc)
        for doc in cursor
        if doc.get("change_type") in allowed or str(doc.get("change_type", "")).startswith("documentation_")
    ]
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "filter": filt,
    }


def get_coordination_summary(limit: int = 20) -> dict[str, Any]:
    """Últimos eventos de coordinación + puntero a carpeta compartida."""
    db = get_db()
    limit = max(1, min(int(limit), 100))
    cursor = db[COL_COORDINATION_LOG].find({}).sort("ts", -1).limit(limit)
    events = [_serialize(doc) for doc in cursor]
    total = db[COL_COORDINATION_LOG].count_documents({})
    return {
        "ok": True,
        "coordination_folder": "/home/rlopez/data/ai_coordination",
        "read_first": "/home/rlopez/data/ai_coordination/00_LEER_PRIMERO.md",
        "projects_registry": "/home/rlopez/data/ai_coordination/PROJECTS_REGISTRY.md",
        "mongo_schema_doc": "/home/rlopez/data/ai_coordination/MONGO_SCHEMA.md",
        "total_events": total,
        "recent_events": events,
    }


def sync_mailbox_snapshot(
    *,
    agent: str,
    mailbox: str,
    file_path: str,
    content_hash: str,
    excerpt: str,
    line_count: int,
    source: str = "ag25_daemon",
) -> dict[str, Any]:
    """Snapshot de INBOX/OUTBOX en Mongo — AG-25 y scripts de sync."""
    db = get_db()
    doc = {
        **_timestamp_fields(),
        "agent": agent.strip().upper(),
        "mailbox": mailbox.upper(),
        "file_path": file_path,
        "content_hash": content_hash,
        "excerpt": excerpt[:8000],
        "line_count": line_count,
        "source": source,
    }
    db[COL_MAILBOX_SNAPSHOTS].insert_one(dict(doc))
    latest = {
        "agent": doc["agent"],
        "mailbox": doc["mailbox"],
        "latest_ts": doc["ts"],
        "latest_ts_local": doc["ts_local"],
        "latest_ts_display": doc["ts_display"],
        "content_hash": content_hash,
        "excerpt": excerpt[:4000],
        "file_path": file_path,
        "line_count": line_count,
        "source": source,
    }
    db[COL_MAILBOX_LATEST].update_one(
        {"agent": doc["agent"], "mailbox": doc["mailbox"]},
        {"$set": latest},
        upsert=True,
    )
    return doc


def upsert_coordination_state(*, key: str, data: dict[str, Any]) -> dict[str, Any]:
    """Estado vivo del hub (mapa, health, tasks) — un doc por key."""
    db = get_db()
    now = _now_iso()
    payload = {**data, "updated_at": now, "key": key}
    db[COL_COORDINATION_STATE].update_one({"key": key}, {"$set": payload}, upsert=True)
    return payload


def get_coordination_state(key: str = "hub_live") -> dict[str, Any]:
    db = get_db()
    doc = db[COL_COORDINATION_STATE].find_one({"key": key})
    if not doc:
        return {"ok": False, "key": key}
    return {"ok": True, "state": _serialize(doc)}


def get_mailbox_latest(agent: str | None = None) -> dict[str, Any]:
    """Último snapshot por agente/mailbox (`ralfia_mailbox_latest`)."""
    db = get_db()
    filt: dict[str, Any] = {}
    if agent:
        filt["agent"] = agent.strip().upper()
    cursor = db[COL_MAILBOX_LATEST].find(filt).sort("latest_ts", -1)
    items = [_serialize(d) for d in cursor]
    return {"ok": True, "count": len(items), "mailboxes": items}


VALID_MEMORY_TYPES = {"personal", "professional", "technical", "research", "project", "architecture", "editorial", "timeline"}
VALID_VISIBILITY = {"PRIVATE", "INTERNAL", "TEAM", "PUBLIC"}


def save_memory(
    *,
    type: str,
    title: str,
    body: str,
    visibility: str,
    tags: list[str] | None = None,
    source: str = "chatgpt_mcp",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    now = _now_iso()
    mem_type = (type or "").strip().lower()
    vis = (visibility or "").strip().upper()
    if mem_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"invalid memory type: {type}")
    if vis not in VALID_VISIBILITY:
        raise ValueError(f"invalid visibility: {visibility}")
    doc = {
        "type": mem_type,
        "title": title.strip(),
        "body": body.strip(),
        "visibility": vis,
        "tags": tags or [],
        "source": source,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_MEMORY_ITEMS].insert_one(doc)
    doc["_id"] = result.inserted_id
    log_coordination(
        agent="CHATGPT",
        summary=f"Memory guardada: {title[:120]}",
        event="memory_save",
        project=(metadata or {}).get("project"),
        tool_used="save_memory",
        metadata={"type": mem_type, "visibility": vis, "tags": tags or []},
    )
    return _serialize(doc)


def _memory_blob(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "body", "content", "description"):
        value = doc.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    tags = doc.get("tags") or []
    if tags:
        parts.append(" ".join(str(tag) for tag in tags if tag))
    metadata = doc.get("metadata") or {}
    if isinstance(metadata, dict) and metadata:
        parts.append(" ".join(str(v) for v in metadata.values() if v not in (None, "")))
    return "\n".join(parts)


def _memory_score(query: str, doc: dict[str, Any]) -> tuple[float, list[str]]:
    text = _memory_blob(doc).lower()
    if not text:
        return 0.0, []
    q = (query or "").strip().lower()
    if not q:
        return 0.0, []
    tokens = [tok for tok in re.findall(r"[a-z0-9áéíóúñ_\-]+", q) if len(tok) > 1]
    score = 0.0
    matched: list[str] = []
    title = str(doc.get("title") or "").lower()
    body = str(doc.get("body") or doc.get("content") or "").lower()
    tags = " ".join(str(tag).lower() for tag in (doc.get("tags") or []))
    metadata = " ".join(str(v).lower() for v in (doc.get("metadata") or {}).values())
    haystacks = ((title, 5.0), (body, 3.0), (tags, 4.0), (metadata, 2.0))
    if q in text:
        score += 3.0
        matched.append("phrase")
    for tok in tokens:
        token_score = 0.0
        if tok in title:
            token_score += 5.0
        if tok in body:
            token_score += 3.0
        if tok in tags:
            token_score += 4.0
        if tok in metadata:
            token_score += 2.0
        if token_score:
            score += token_score
            matched.append(tok)
    for blob, weight in haystacks:
        if q and q in blob:
            score += weight
    if len(tokens) > 1:
        overlap = sum(1 for tok in tokens if tok in text)
        score += min(overlap, len(tokens)) * 0.5
    return score, sorted(set(matched))


def search_memory(
    *,
    query: str,
    type: str | None = None,
    visibility: str | None = None,
    limit: int = 10,
    min_score: float = 0.0,
    trace: bool = False,
    conversation_id: str | None = None,
    entity_id: str | None = None,
    project: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    db = get_db()
    q = (query or "").strip()
    if not q:
        empty: list[dict[str, Any]] = []
        return {"ok": True, "count": 0, "items": empty, "trace": {"query": q, "min_score": float(min_score), "considered": 0, "discarded": 0}} if trace else empty
    limit = max(1, min(int(limit), 50))
    filt: dict[str, Any] = {}
    if type:
        filt["type"] = type.strip().lower()
    if visibility:
        filt["visibility"] = visibility.strip().upper()
    if conversation_id:
        filt["metadata.conversation_id"] = conversation_id.strip()
    elif entity_id:
        filt["metadata.entity_id"] = entity_id.strip()
    if project:
        filt["metadata.project"] = project.strip()
    cursor = db[COL_MEMORY_ITEMS].find(filt)
    scored: list[dict[str, Any]] = []
    considered = 0
    discarded = 0
    for doc in cursor:
        considered += 1
        score, matched_terms = _memory_score(q, doc)
        if score < float(min_score or 0):
            discarded += 1
            continue
        enriched = _serialize(doc)
        enriched["score"] = round(score, 3)
        if matched_terms:
            enriched["matched_terms"] = matched_terms
        scored.append(enriched)
    scored.sort(key=lambda item: (float(item.get("score", 0.0)), item.get("created_at") or ""), reverse=True)
    items = scored[:limit]
    if trace:
        return {
            "ok": True,
            "count": len(items),
            "items": items,
            "filter": filt,
            "trace": {
                "query": q,
                "min_score": float(min_score or 0),
                "considered": considered,
                "discarded": discarded,
                "returned": len(items),
            },
        }
    return items


def save_knowledge_seed(
    *,
    title: str,
    body: str,
    category: str,
    intent: str,
    visibility: str,
    project: str | None = None,
    tags: list[str] | None = None,
    source: str = "chatgpt_mcp",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    now = _now_iso()
    cat = (category or "").strip().lower()
    inten = (intent or "").strip().lower()
    vis = (visibility or "").strip().upper()
    if vis not in VALID_VISIBILITY:
        raise ValueError(f"invalid visibility: {visibility}")
    doc = {
        "title": title.strip(),
        "body": body.strip(),
        "category": cat,
        "intent": inten,
        "visibility": vis,
        "project": project,
        "tags": tags or [],
        "source": source,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }
    result = db[COL_KNOWLEDGE_SEEDS].insert_one(doc)
    doc["_id"] = result.inserted_id
    should_publish = vis != "PRIVATE" and (cat == "publication" or inten == "publish")
    if should_publish:
        draft_res = db[COL_EDITORIAL_PIPELINE].insert_one(
            {
                "channel": "linkedin",
                "title": title.strip(),
                "markdown": body.strip(),
                "body": body.strip(),
                "status": "ready_for_review",
                "source": source,
                "metadata": {
                    **(metadata or {}),
                    "knowledge_seed_id": str(result.inserted_id),
                    "category": cat,
                    "intent": inten,
                    "visibility": vis,
                },
                "created_at": now,
                "updated_at": now,
            }
        )
        doc["draft_created"] = True
        doc["draft_id"] = str(draft_res.inserted_id)
    else:
        doc["draft_created"] = False
    log_coordination(
        agent="CHATGPT",
        summary=f"Knowledge seed: {title[:120]}",
        event="knowledge_seed",
        project=project,
        tool_used="save_knowledge_seed",
        metadata={"category": cat, "intent": inten, "visibility": vis, "tags": tags or []},
    )
    return _serialize(doc)


def get_publish_logs(limit: int = 20) -> dict[str, Any]:
    db = get_db()
    limit = max(1, min(int(limit), 50))
    destinations = list(db["social_destinations"].find({}).sort("updated_at", -1).limit(limit))
    posts = list(db["editorial_posts"].find({}).sort("updated_at", -1).limit(limit))
    sync = list(
        db[COL_SYNC_LOG]
        .find({"event": {"$in": ["linkedin_publish", "editorial_image", "editorial_approve", "mcp_health_check"]}})
        .sort("ts", -1)
        .limit(limit)
    )
    errors = [d for d in destinations if d.get("status") in {"failed", "pending_linkedin_config"}]
    return {
        "ok": True,
        "destinations": [_serialize(d) for d in destinations],
        "posts": [_serialize(p) for p in posts],
        "sync_events": [_serialize(s) for s in sync],
        "errors": [_serialize(e) for e in errors],
    }


def classify_knowledge_seed(title: str, body: str) -> dict[str, Any]:
    text = f"{title}\n{body}".lower()
    category = "technical"
    intent = "remember"
    visibility = "INTERNAL"
    project = None
    reason = "defaulted to technical/internal"

    rules = [
        (("linkedin", "publish", "post", "publicar", "publicación", "publicacion"), ("publication", "publish", "PUBLIC"), "looks like editorial/publication"),
        (("roadmap", "plan", "fase", "next", "próximo", "proximo"), ("roadmap", "plan", "TEAM"), "planning / roadmap"),
        (("architecture", "arquitect", "mcp", "oauth", "gateway"), ("architecture", "develop", "INTERNAL"), "architecture / integration"),
        (("hackathon", "funding", "grant", "opportunity"), ("hackathon", "plan", "TEAM"), "hackathon / funding"),
        (("client", "cliente", "business", "negocio"), ("client", "remember", "INTERNAL"), "client / business"),
        (("travel", "viaje", "trip"), ("travel", "remember", "PRIVATE"), "travel / private"),
    ]
    for needles, values, why in rules:
        if any(n in text for n in needles):
            category, intent, visibility = values
            reason = why
            break
    if category == "publication":
        intent = "publish"
        visibility = "PUBLIC"
    return {
        "ok": True,
        "category": category,
        "intent": intent,
        "visibility": visibility,
        "project": project,
        "confidence": 0.72,
        "reason": reason,
    }
