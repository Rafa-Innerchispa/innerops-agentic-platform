"""Universal application/submission workspace for grants, forms and hackathons."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from raphiia_openai import mongo_store

COL_APPLICATIONS = "application_workspace_applications"
COL_QUESTIONS = "application_workspace_questions"
COL_SOURCES = "application_workspace_sources"
COL_EVIDENCE = "application_workspace_evidence"
COL_AUDIT = "application_workspace_audit"
LEGACY_FUNDING_COL = "funding_applications"

VALID_VERSION_STATUS = {"draft", "current", "submitted"}
VALID_APPLICATION_STATUS = {"draft", "active", "submitted", "archived", "rejected", "approved"}


def application_get(application_id: str = "", program: str = "", title: str = "") -> dict[str, Any]:
    _ensure_indexes()
    app = _find_application(application_id, program, title)
    if not app:
        return {"ok": False, "error": "application_not_found"}
    return {"ok": True, "application": _serialize(app), "questions": _questions_for(str(app["_id"]))}


def application_upsert(
    title: str,
    program: str = "",
    company: str = "",
    project: str = "",
    status: str = "active",
    application_id: str = "",
    metadata: dict[str, Any] | None = None,
    body: str = "",
    idempotency_key: str = "",
    source: str = "chatgpt_mcp",
) -> dict[str, Any]:
    _ensure_indexes()
    now = _now()
    status_value = _status(status, VALID_APPLICATION_STATUS, "active")
    filt: dict[str, Any]
    oid = _oid(application_id)
    if oid:
        filt = {"_id": oid}
    else:
        filt = {"canonical_key": _canonical_key(program or title, company, project)}
    existing = _db()[COL_APPLICATIONS].find_one(filt)
    doc = {
        "title": title.strip(),
        "program": program.strip(),
        "company": company.strip(),
        "project": project.strip(),
        "status": status_value,
        "metadata": metadata or {},
        "body": body,
        "canonical_key": _canonical_key(program or title, company, project),
        "source": source,
        "updated_at": now,
    }
    if existing:
        _db()[COL_APPLICATIONS].update_one({"_id": existing["_id"]}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
        app_id = existing["_id"]
        action = "application_update"
    else:
        doc["created_at"] = now
        res = _db()[COL_APPLICATIONS].insert_one(doc)
        app_id = res.inserted_id
        action = "application_create"
    _audit(action, str(app_id), {"idempotency_key": idempotency_key, "title": title, "program": program})
    return application_get(str(app_id))


def application_add_or_update_module(application_id: str, module: str, order: int = 0, status: str = "draft", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    app = _require_app(application_id)
    module_doc = {
        "name": module.strip(),
        "order": int(order or 0),
        "status": _status(status, VALID_VERSION_STATUS, "draft"),
        "metadata": metadata or {},
        "updated_at": _now(),
    }
    _db()[COL_APPLICATIONS].update_one(
        {"_id": app["_id"], "modules.name": {"$ne": module_doc["name"]}},
        {"$push": {"modules": module_doc}, "$set": {"updated_at": _now()}},
    )
    _db()[COL_APPLICATIONS].update_one(
        {"_id": app["_id"], "modules.name": module_doc["name"]},
        {"$set": {"modules.$.order": module_doc["order"], "modules.$.status": module_doc["status"], "modules.$.metadata": module_doc["metadata"], "modules.$.updated_at": module_doc["updated_at"], "updated_at": _now()}},
    )
    _audit("module_upsert", str(app["_id"]), {"module": module_doc["name"]})
    return application_get(str(app["_id"]))


def application_upsert_question_answer(
    application_id: str,
    question_key: str,
    question_text: str,
    answer: str,
    module: str = "",
    max_chars: int = 0,
    version_status: str = "draft",
    source_refs: list[str] | None = None,
    rationale: str = "",
    idempotency_key: str = "",
    author_agent: str = "CHATGPT",
) -> dict[str, Any]:
    app = _require_app(application_id)
    key = _question_key(question_key or question_text)
    now = _now()
    status = _status(version_status, VALID_VERSION_STATUS, "draft")
    filt = {"application_id": str(app["_id"]), "question_key": key}
    existing = _db()[COL_QUESTIONS].find_one(filt)
    if existing and idempotency_key:
        for old in existing.get("answer_versions") or []:
            if old.get("idempotency_key") == idempotency_key:
                return {"ok": True, "idempotent": True, "question": _serialize(existing)}
    version = {
        "version_id": hashlib.sha256(f"{key}|{answer}|{now}".encode()).hexdigest()[:16],
        "answer": answer,
        "status": status,
        "source_refs": source_refs or [],
        "rationale": rationale,
        "author_agent": author_agent,
        "created_at": now,
        "idempotency_key": idempotency_key,
    }
    if existing:
        update: dict[str, Any] = {
            "$set": {
                "question_text": question_text,
                "module": module,
                "max_chars": int(max_chars or 0),
                "updated_at": now,
            },
            "$push": {"answer_versions": version},
        }
        if status in {"current", "submitted"}:
            update["$set"].update({"current_answer": answer, "current_status": status, "current_version_id": version["version_id"]})
        elif not existing.get("current_answer"):
            update["$set"].update({"current_answer": answer, "current_status": status, "current_version_id": version["version_id"]})
        _db()[COL_QUESTIONS].update_one({"_id": existing["_id"]}, update)
        qid = existing["_id"]
    else:
        doc = {
            "application_id": str(app["_id"]),
            "question_key": key,
            "question_text": question_text,
            "module": module,
            "max_chars": int(max_chars or 0),
            "current_answer": answer,
            "current_status": status,
            "current_version_id": version["version_id"],
            "answer_versions": [version],
            "created_at": now,
            "updated_at": now,
        }
        qid = _db()[COL_QUESTIONS].insert_one(doc).inserted_id
    _db()[COL_APPLICATIONS].update_one({"_id": app["_id"]}, {"$set": {"updated_at": now}})
    _audit("question_answer_upsert", str(app["_id"]), {"question_key": key, "version_status": status, "idempotency_key": idempotency_key})
    return {"ok": True, "question": _serialize(_db()[COL_QUESTIONS].find_one({"_id": qid}))}


def application_list_questions(application_id: str, module: str = "", status: str = "") -> dict[str, Any]:
    app = _require_app(application_id)
    filt: dict[str, Any] = {"application_id": str(app["_id"])}
    if module:
        filt["module"] = module
    if status:
        filt["current_status"] = status
    rows = [_serialize(d) for d in _db()[COL_QUESTIONS].find(filt).sort([("module", 1), ("question_key", 1)])]
    return {"ok": True, "count": len(rows), "items": rows}


def application_search(query: str, program: str = "", company: str = "", project: str = "", limit: int = 10) -> dict[str, Any]:
    _ensure_indexes()
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query_required"}
    app_filter: dict[str, Any] = {}
    for field, value in {"program": program, "company": company, "project": project}.items():
        if value:
            app_filter[field] = {"$regex": re.escape(value), "$options": "i"}
    app_ids = [str(a["_id"]) for a in _db()[COL_APPLICATIONS].find(app_filter, {"_id": 1})] if app_filter else []
    tokens = [t for t in re.split(r"\W+", q, flags=re.UNICODE) if len(t) >= 3][:8]
    clauses = [{"question_text": {"$regex": re.escape(q), "$options": "i"}}, {"current_answer": {"$regex": re.escape(q), "$options": "i"}}, {"module": {"$regex": re.escape(q), "$options": "i"}}]
    for token in tokens:
        clauses.extend(
            [
                {"question_text": {"$regex": re.escape(token), "$options": "i"}},
                {"current_answer": {"$regex": re.escape(token), "$options": "i"}},
                {"module": {"$regex": re.escape(token), "$options": "i"}},
            ]
        )
    filt: dict[str, Any] = {"$or": clauses}
    if app_ids:
        filt["application_id"] = {"$in": app_ids}
    rows = []
    scored = []
    for doc in _db()[COL_QUESTIONS].find(filt).limit(100):
        item = _serialize(doc)
        app = _db()[COL_APPLICATIONS].find_one({"_id": _oid(item["application_id"])})
        item["application"] = _summarize_app(app) if app else None
        haystack = " ".join([item.get("question_text") or "", item.get("current_answer") or "", item.get("module") or ""]).lower()
        score = sum(1 for token in tokens if token.lower() in haystack)
        scored.append((score, item))
    for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[: max(1, min(int(limit or 10), 50))]:
        rows.append(item)
    return {"ok": True, "query": q, "count": len(rows), "items": rows}


def application_attach_source(application_id: str, source: dict[str, Any], idempotency_key: str = "") -> dict[str, Any]:
    return _attach(COL_SOURCES, "source_attach", application_id, source, idempotency_key)


def application_attach_evidence(application_id: str, evidence: dict[str, Any], idempotency_key: str = "") -> dict[str, Any]:
    return _attach(COL_EVIDENCE, "evidence_attach", application_id, evidence, idempotency_key)


def application_history(application_id: str = "", question_key: str = "") -> dict[str, Any]:
    app = _require_app(application_id) if application_id else None
    filt: dict[str, Any] = {}
    if app:
        filt["application_id"] = str(app["_id"])
    if question_key:
        filt["question_key"] = _question_key(question_key)
    rows = [_serialize(d) for d in _db()[COL_QUESTIONS].find(filt).sort("updated_at", -1).limit(100)]
    return {"ok": True, "count": len(rows), "items": rows}


def application_mark_submitted(application_id: str, submitted_at: str = "", evidence_refs: list[str] | None = None, idempotency_key: str = "") -> dict[str, Any]:
    app = _require_app(application_id)
    now = submitted_at or _now()
    _db()[COL_APPLICATIONS].update_one({"_id": app["_id"]}, {"$set": {"status": "submitted", "submitted_at": now, "submitted_evidence_refs": evidence_refs or [], "updated_at": _now()}})
    _db()[COL_QUESTIONS].update_many({"application_id": str(app["_id"]), "current_status": "current"}, {"$set": {"current_status": "submitted", "updated_at": _now()}})
    _audit("application_submitted", str(app["_id"]), {"submitted_at": now, "idempotency_key": idempotency_key})
    return application_get(str(app["_id"]))


def application_export_snapshot(application_id: str, format: str = "markdown") -> dict[str, Any]:
    app = _require_app(application_id)
    questions = _questions_for(str(app["_id"]))
    sources = [_serialize(d) for d in _db()[COL_SOURCES].find({"application_id": str(app["_id"])})]
    evidence = [_serialize(d) for d in _db()[COL_EVIDENCE].find({"application_id": str(app["_id"])})]
    payload = {"application": _serialize(app), "questions": questions, "sources": sources, "evidence": evidence}
    if (format or "markdown").lower() == "json":
        return {"ok": True, "format": "json", "snapshot": payload}
    lines = [f"# {app.get('title','Application')}", "", f"- Program: {app.get('program','')}", f"- Company: {app.get('company','')}", f"- Project: {app.get('project','')}", f"- Status: {app.get('status','')}", ""]
    current_module = None
    for q in questions:
        if q.get("module") != current_module:
            current_module = q.get("module")
            lines += ["", f"## {current_module or 'Questions'}"]
        lines += ["", f"### {q.get('question_text') or q.get('question_key')}", "", q.get("current_answer") or ""]
    return {"ok": True, "format": "markdown", "snapshot": "\n".join(lines), "json": payload}


def application_migrate_legacy_funding_application(application_id: str, idempotency_key: str = "legacy_funding_migration") -> dict[str, Any]:
    _ensure_indexes()
    oid = _oid(application_id)
    if not oid:
        return {"ok": False, "error": "invalid_application_id"}
    legacy = _db()[LEGACY_FUNDING_COL].find_one({"_id": oid})
    if not legacy:
        return {"ok": False, "error": "legacy_application_not_found"}
    meta = legacy.get("metadata") or {}
    app_doc = {
        "_id": oid,
        "title": legacy.get("title", ""),
        "program": meta.get("program") or legacy.get("program_id") or "",
        "company": meta.get("company") or "",
        "project": meta.get("initiative") or "",
        "status": legacy.get("status", "draft"),
        "metadata": {**meta, "legacy_collection": LEGACY_FUNDING_COL, "legacy_id": str(oid)},
        "body": legacy.get("body", ""),
        "canonical_key": _canonical_key(meta.get("program") or legacy.get("title", ""), meta.get("company") or "", meta.get("initiative") or ""),
        "source": "legacy_funding_migration",
        "created_at": legacy.get("created_at") or _now(),
        "updated_at": _now(),
        "modules": [],
    }
    _db()[COL_APPLICATIONS].replace_one({"_id": oid}, app_doc, upsert=True)
    body = legacy.get("body", "")
    seeded = _seed_mision_emprende_from_body(str(oid), body)
    for title in [
        "Guia 2026 - problema-solucion",
        "Guia 2026 - propuesta de valor",
        "Guia 2026 - segmentacion de clientes",
    ]:
        application_attach_source(str(oid), {"title": title, "type": "guide_reference", "program": "Mision Emprende 593", "year": 2026}, idempotency_key=f"{idempotency_key}:{title}")
    _audit("legacy_funding_application_migrated", str(oid), {"seeded_questions": seeded, "idempotency_key": idempotency_key})
    return {"ok": True, "application_id": str(oid), "seeded_questions": seeded, "application": application_get(str(oid))}


def _seed_mision_emprende_from_body(application_id: str, body: str) -> int:
    module = "Identificación del Segmento de Clientes"
    application_add_or_update_module(application_id, module, order=40, status="current", metadata={"source": "legacy_body"})
    labels = [
        ("claridad_cliente", "Claridad del cliente"),
        ("validacion_cliente", "Validación"),
        ("cliente_ideal", "Cliente ideal"),
        ("problema_principal", "Problema principal"),
    ]
    count = 0
    for key, label in labels:
        match = re.search(rf"(?m)^\d+\.\s*{re.escape(label)}:\s*(.+?)(?=^\d+\.\s*|\n\nGU[IÍ]A|\Z)", body, flags=re.S | re.I)
        if not match:
            continue
        answer = re.sub(r"\s+", " ", match.group(1)).strip()
        application_upsert_question_answer(
            application_id=application_id,
            question_key=key,
            question_text=label,
            answer=answer,
            module=module,
            version_status="current",
            source_refs=["legacy_body", "guia-2026-segmentacion-clientes", "guia-2026-propuesta-valor"],
            rationale="Migrated from existing funding_applications body without inventing new fields.",
            idempotency_key=f"mision593_seed:{key}",
            author_agent="CODEX",
        )
        count += 1
    return count


def _attach(collection: str, action: str, application_id: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    app = _require_app(application_id)
    clean = _clean_attachment(payload)
    clean.update({"application_id": str(app["_id"]), "updated_at": _now(), "idempotency_key": idempotency_key})
    if idempotency_key:
        _db()[collection].update_one({"application_id": str(app["_id"]), "idempotency_key": idempotency_key}, {"$set": clean, "$setOnInsert": {"created_at": _now()}}, upsert=True)
        doc = _db()[collection].find_one({"application_id": str(app["_id"]), "idempotency_key": idempotency_key})
    else:
        clean["created_at"] = _now()
        inserted = _db()[collection].insert_one(clean).inserted_id
        doc = _db()[collection].find_one({"_id": inserted})
    _audit(action, str(app["_id"]), {"collection": collection, "idempotency_key": idempotency_key})
    return {"ok": True, "item": _serialize(doc)}


def _ensure_indexes() -> None:
    db = _db()
    db[COL_APPLICATIONS].create_index("canonical_key", unique=False)
    db[COL_APPLICATIONS].create_index([("program", 1), ("company", 1), ("project", 1)])
    db[COL_QUESTIONS].create_index([("application_id", 1), ("question_key", 1)], unique=True)
    db[COL_QUESTIONS].create_index([("application_id", 1), ("module", 1)])
    db[COL_QUESTIONS].create_index([("question_text", "text"), ("current_answer", "text"), ("module", "text")], default_language="spanish")
    db[COL_SOURCES].create_index([("application_id", 1), ("idempotency_key", 1)])
    db[COL_EVIDENCE].create_index([("application_id", 1), ("idempotency_key", 1)])


def _db():
    return mongo_store.get_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oid(value: str | ObjectId | None) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value)) if value else None
    except Exception:
        return None


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _find_application(application_id: str, program: str, title: str) -> dict[str, Any] | None:
    oid = _oid(application_id)
    if oid:
        return _db()[COL_APPLICATIONS].find_one({"_id": oid})
    filt = {}
    if program:
        filt["program"] = {"$regex": re.escape(program), "$options": "i"}
    if title:
        filt["title"] = {"$regex": re.escape(title), "$options": "i"}
    return _db()[COL_APPLICATIONS].find_one(filt) if filt else None


def _require_app(application_id: str) -> dict[str, Any]:
    app = _find_application(application_id, "", "")
    if not app:
        raise ValueError("application_not_found")
    return app


def _questions_for(application_id: str) -> list[dict[str, Any]]:
    return [_serialize(d) for d in _db()[COL_QUESTIONS].find({"application_id": application_id}).sort([("module", 1), ("question_key", 1)])]


def _canonical_key(program: str, company: str, project: str) -> str:
    raw = "|".join([program or "", company or "", project or ""]).lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:180]


def _question_key(value: str) -> str:
    raw = (value or "").lower()
    key = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return key[:100] or hashlib.sha256(raw.encode()).hexdigest()[:16]


def _status(value: str, allowed: set[str], default: str) -> str:
    clean = (value or default).strip().lower()
    return clean if clean in allowed else default


def _clean_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    text = json.dumps(data, ensure_ascii=False)
    if re.search(r"(?i)(password\s*[:=]|token\s*[:=]|secret\s*[:=]|api[_-]?key\s*[:=]|-----BEGIN)", text):
        raise ValueError("attachment_contains_secret_like_value")
    if "path" in data and data["path"]:
        data["path_hash"] = hashlib.sha256(str(data["path"]).encode()).hexdigest()
    return data


def _summarize_app(app: dict[str, Any]) -> dict[str, Any]:
    return {"_id": str(app["_id"]), "title": app.get("title"), "program": app.get("program"), "company": app.get("company"), "project": app.get("project"), "status": app.get("status")}


def _audit(action: str, application_id: str, evidence: dict[str, Any]) -> None:
    try:
        _db()[COL_AUDIT].insert_one({"ts": _now(), "action": action, "application_id": application_id, "evidence": evidence})
    except Exception:
        pass
