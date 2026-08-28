"""Orquestación P0 — briefs, tareas, actividad agentes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

from raphiia_openai import coordination_docs, mongo_store
from raphiia_openai.settings import (
    COL_AGENT_ACTIVITY,
    COL_ORCHESTRATION_BRIEFS,
    COL_ORCHESTRATION_TASKS,
    COORD_ROOT,
)

AGENTS = frozenset({"CURSOR", "CODEX", "ANTIGRAVITY", "GEMINI", "CHATGPT", "RAFAEL"})
TASK_STATUSES = frozenset({"pending", "dispatched", "in_progress", "completed", "failed", "blocked"})
ACTIVITY_STATUSES = frozenset({"started", "in_progress", "blocked", "completed", "failed", "needs_review", "missing_handoff"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "brief").strip())[:60].strip("-").lower()
    return s or "brief"


def save_brief(
    title: str,
    body: str,
    targets: list[str] | None = None,
    priority: str = "normal",
    author: str = "CHATGPT",
) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now_iso()
    ts = now.replace(":", "").replace("-", "")[:15]
    slug = _slug(title)
    rel = f"orchestration/briefs/{ts}_{slug}.md"
    path = COORD_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    md = f"# {title}\n\n**Priority:** {priority}\n**Targets:** {', '.join(targets or [])}\n**Author:** {author}\n\n{body}\n"
    path.write_text(md, encoding="utf-8")
    doc = {
        "title": title,
        "body": body,
        "targets": [t.upper() for t in (targets or []) if t],
        "priority": priority,
        "author": author.upper(),
        "path": str(path),
        "rel_path": rel,
        "status": "saved",
        "created_at": now,
        "updated_at": now,
    }
    res = db[COL_ORCHESTRATION_BRIEFS].insert_one(doc)
    bid = str(res.inserted_id)
    mongo_store.log_coordination(
        agent=author.upper(),
        summary=f"Brief orquestación: {title}",
        event="orchestration_brief",
        project="ralfia-orchestration",
        metadata={"brief_id": bid, "targets": doc["targets"]},
    )
    return {"ok": True, "brief_id": bid, "path": str(path), "rel_path": rel}


def create_task(
    target_agent: str,
    title: str,
    summary: str,
    brief_id: str = "",
    priority: str = "normal",
) -> dict[str, Any]:
    agent = target_agent.strip().upper()
    if agent not in AGENTS:
        return {"ok": False, "error": f"invalid agent: {target_agent}"}
    db = mongo_store.get_db()
    now = _now_iso()
    doc = {
        "target_agent": agent,
        "title": title,
        "summary": summary[:500],
        "brief_id": brief_id,
        "priority": priority,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    res = db[COL_ORCHESTRATION_TASKS].insert_one(doc)
    tid = str(res.inserted_id)
    return {"ok": True, "task_id": tid, "task": _serialize(db[COL_ORCHESTRATION_TASKS].find_one({"_id": res.inserted_id}))}


def dispatch_brief(brief_id: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    try:
        oid = ObjectId(brief_id)
    except Exception:
        return {"ok": False, "error": "invalid brief_id"}
    brief = db[COL_ORCHESTRATION_BRIEFS].find_one({"_id": oid})
    if not brief:
        return {"ok": False, "error": "brief not found"}
    targets = brief.get("targets") or ["CURSOR"]
    dispatched = []
    for agent in targets:
        msg_title = brief.get("title", "Tarea orquestación")
        msg_body = (
            f"**Brief:** `{brief_id}`\n"
            f"**Prioridad:** {brief.get('priority', 'normal')}\n\n"
            f"{brief.get('summary') or brief.get('body', '')[:400]}\n\n"
            f"Lee brief completo: `{brief.get('rel_path', '')}` o Mongo brief_id={brief_id}.\n"
            f"Responde en `{agent.lower()}/OUTBOX.md` y marca tarea done vía MCP."
        )
        task = create_task(agent, msg_title, msg_body[:500], brief_id=brief_id, priority=brief.get("priority", "normal"))
        if task.get("ok"):
            coordination_docs.create_agent_message(
                from_agent="ORCHESTRATOR",
                target_agent=agent.lower(),
                title=msg_title[:120],
                body=msg_body[:2000],
                priority=brief.get("priority", "normal"),
            )
            db[COL_ORCHESTRATION_TASKS].update_one(
                {"_id": ObjectId(task["task_id"])},
                {"$set": {"status": "dispatched", "updated_at": _now_iso()}},
            )
            dispatched.append({"agent": agent, "task_id": task["task_id"]})
    db[COL_ORCHESTRATION_BRIEFS].update_one(
        {"_id": oid},
        {"$set": {"status": "dispatched", "updated_at": _now_iso(), "dispatched_to": dispatched}},
    )
    return {"ok": True, "brief_id": brief_id, "dispatched": dispatched}


PENDING_HANDOFFS_REL = "orchestration/PENDING_HANDOFFS.md"
COL_PENDING_HANDOFFS = "ralfia_pending_agent_handoffs"


def _pending_path() -> Path:
    return COORD_ROOT / PENDING_HANDOFFS_REL


def _append_pending_handoff(entry: dict[str, Any]) -> None:
    path = _pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(
            "# Pending agent handoffs\n\n"
            "Cola de respaldo cuando falla entrega directa a INBOX.\n"
            "AG-25 / `handoff_brief` procesan esta cola.\n\n",
            encoding="utf-8",
        )
    line = (
        f"- **{entry.get('ts', _now_iso())}** | `{entry.get('agent', '?')}` | "
        f"brief `{entry.get('brief_id', '?')}` | {entry.get('status', 'pending')} | "
        f"{entry.get('title', '')[:80]}\n"
    )
    path.write_text(path.read_text(encoding="utf-8") + line, encoding="utf-8")


def _record_pending_mongo(entry: dict[str, Any]) -> None:
    db = mongo_store.get_db()
    doc = {**entry, "created_at": _now_iso(), "status": entry.get("status", "pending")}
    db[COL_PENDING_HANDOFFS].insert_one(doc)


def _inbox_rel(agent: str) -> str:
    return f"{agent.strip().lower()}/INBOX.md"


def handoff_brief(
    brief_id: str,
    agent: str = "CURSOR",
    note: str = "",
    priority: str | None = None,
) -> dict[str, Any]:
    """Entrega atómica brief → INBOX + tarea Mongo + log. Fallback a cola pendiente."""
    db = mongo_store.get_db()
    try:
        oid = ObjectId(brief_id)
    except Exception:
        return {"ok": False, "delivered": False, "error": "invalid brief_id", "status": "failed"}

    brief = db[COL_ORCHESTRATION_BRIEFS].find_one({"_id": oid})
    if not brief:
        return {"ok": False, "delivered": False, "error": "brief not found", "status": "failed"}

    target = agent.strip().upper()
    if target not in AGENTS:
        return {"ok": False, "delivered": False, "error": f"invalid agent: {agent}", "status": "failed"}

    prio = (priority or brief.get("priority") or "normal").lower()
    title = brief.get("title", "Brief orquestación")
    rel = brief.get("rel_path") or ""
    summary = (note or brief.get("body", "")[:400]).strip()
    inbox_body = (
        f"**Brief ID:** `{brief_id}`\n"
        f"**Prioridad:** {prio}\n"
        f"**Ruta:** `{rel}`\n\n"
        f"{summary}\n\n"
        f"Lee el brief completo con `read_coordination_file(\"{rel}\")` o Mongo brief_id.\n"
        f"Responde en `{target.lower()}/OUTBOX.md`."
    )

    inbox_ok = False
    task_id = ""
    inbox_path = ""
    errors: list[str] = []

    try:
        task = create_task(target, title, summary[:500], brief_id=brief_id, priority=prio)
        if task.get("ok"):
            task_id = task["task_id"]
            msg = coordination_docs.write_agent_message(
                target_agent=target.lower(),
                title=title[:120],
                body=inbox_body[:2000],
                priority=prio,
                from_agent="ORCHESTRATOR",
            )
            inbox_ok = bool(msg.get("ok"))
            inbox_path = msg.get("path") or _inbox_rel(target)
            db[COL_ORCHESTRATION_TASKS].update_one(
                {"_id": ObjectId(task_id)},
                {"$set": {"status": "dispatched", "updated_at": _now_iso()}},
            )
        else:
            errors.append(task.get("error", "create_task failed"))
    except Exception as exc:
        errors.append(str(exc)[:200])

    if inbox_ok:
        db[COL_ORCHESTRATION_BRIEFS].update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "delivered",
                    "delivery_status": "delivered",
                    "updated_at": _now_iso(),
                    "delivered_to": [{"agent": target, "task_id": task_id, "inbox_path": inbox_path}],
                }
            },
        )
        mongo_store.log_coordination(
            agent="MCP",
            summary=f"Handoff brief → {target}: {title[:80]}",
            event="handoff_brief",
            project="ralfia-orchestration",
            metadata={"brief_id": brief_id, "task_id": task_id, "agent": target},
        )
        return {
            "ok": True,
            "delivered": True,
            "status": "delivered",
            "agent": target,
            "brief_id": brief_id,
            "task_id": task_id,
            "inbox_path": inbox_path,
            "rel_path": rel,
        }

    pending = {
        "ts": _now_iso(),
        "agent": target,
        "brief_id": brief_id,
        "title": title,
        "rel_path": rel,
        "status": "pending",
        "errors": errors,
    }
    _append_pending_handoff(pending)
    _record_pending_mongo(pending)
    db[COL_ORCHESTRATION_BRIEFS].update_one(
        {"_id": oid},
        {"$set": {"status": "pending_delivery", "delivery_status": "partial", "updated_at": _now_iso()}},
    )
    return {
        "ok": True,
        "delivered": False,
        "status": "partial",
        "agent": target,
        "brief_id": brief_id,
        "task_id": task_id or None,
        "pending_path": PENDING_HANDOFFS_REL,
        "errors": errors,
    }


def save_and_handoff_brief(
    title: str,
    body: str,
    targets: list[str] | None = None,
    priority: str = "normal",
    note: str = "",
    author: str = "CHATGPT",
) -> dict[str, Any]:
    """Guarda brief + entrega al primer target en una sola operación."""
    saved = save_brief(title, body, targets=targets, priority=priority, author=author)
    if not saved.get("ok"):
        return saved
    bid = saved["brief_id"]
    agent = (targets or ["CURSOR"])[0]
    handoff = handoff_brief(bid, agent=agent, note=note, priority=priority)
    return {
        **saved,
        **handoff,
        "combined": True,
    }


def process_pending_handoffs(limit: int = 10) -> dict[str, Any]:
    """Reintenta entregas pendientes (AG-25 / watcher)."""
    db = mongo_store.get_db()
    cursor = (
        db[COL_PENDING_HANDOFFS]
        .find({"status": "pending"})
        .sort("created_at", 1)
        .limit(max(1, min(limit, 50)))
    )
    results = []
    for doc in cursor:
        bid = doc.get("brief_id", "")
        agent = doc.get("agent", "CURSOR")
        res = handoff_brief(bid, agent=agent, note=f"Retry pending handoff {doc.get('_id')}")
        if res.get("delivered"):
            db[COL_PENDING_HANDOFFS].update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "delivered", "updated_at": _now_iso()}},
            )
        results.append(res)
    return {"ok": True, "processed": len(results), "results": results}


def deliver_undelivered_briefs(limit: int = 20) -> dict[str, Any]:
    """Briefs guardados sin entregar → handoff automático."""
    db = mongo_store.get_db()
    cursor = (
        db[COL_ORCHESTRATION_BRIEFS]
        .find({"status": {"$in": ["saved", "pending_delivery"]}})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 50)))
    )
    delivered = []
    for brief in cursor:
        bid = str(brief["_id"])
        targets = brief.get("targets") or ["CURSOR"]
        for agent in targets:
            res = handoff_brief(bid, agent=agent)
            delivered.append(res)
    return {"ok": True, "count": len(delivered), "delivered": delivered}


def list_tasks(
    status: str | None = None,
    agent: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if status:
        filt["status"] = status
    if agent:
        filt["target_agent"] = agent.upper()
    cursor = db[COL_ORCHESTRATION_TASKS].find(filt).sort("created_at", -1).limit(max(1, min(limit, 100)))
    items = [_serialize(d) for d in cursor]
    return {"ok": True, "count": len(items), "tasks": items}


def mark_task_done(task_id: str, agent: str, summary: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    try:
        oid = ObjectId(task_id)
    except Exception:
        return {"ok": False, "error": "invalid task_id"}
    now = _now_iso()
    db[COL_ORCHESTRATION_TASKS].update_one(
        {"_id": oid},
        {"$set": {"status": "completed", "completed_by": agent.upper(), "result_summary": summary, "updated_at": now}},
    )
    finish_agent_task(agent, task_id=task_id, summary=summary, status="completed")
    doc = db[COL_ORCHESTRATION_TASKS].find_one({"_id": oid})
    return {"ok": True, "task": _serialize(doc)}


def start_agent_task(
    agent: str,
    *,
    task_id: str = "",
    project: str = "",
    summary: str,
    files_changed: list[str] | None = None,
    services_touched: list[str] | None = None,
    ports_touched: list[int] | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now_iso()
    doc = {
        "agent": agent.upper(),
        "task_id": task_id,
        "project": project,
        "status": "started",
        "summary": summary,
        "files_changed": files_changed or [],
        "services_touched": services_touched or [],
        "ports_touched": ports_touched or [],
        "risks": [],
        "next_action": "",
        "started_at": now,
        "updated_at": now,
    }
    res = db[COL_AGENT_ACTIVITY].insert_one(doc)
    return {"ok": True, "activity_id": str(res.inserted_id), "activity": _serialize(doc)}


def finish_agent_task(
    agent: str,
    *,
    task_id: str = "",
    summary: str,
    status: str = "completed",
    files_changed: list[str] | None = None,
    services_touched: list[str] | None = None,
    ports_touched: list[int] | None = None,
    risks: list[str] | None = None,
    next_action: str = "",
) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now_iso()
    doc = {
        "agent": agent.upper(),
        "task_id": task_id,
        "status": status if status in ACTIVITY_STATUSES else "completed",
        "summary": summary,
        "files_changed": files_changed or [],
        "services_touched": services_touched or [],
        "ports_touched": ports_touched or [],
        "risks": risks or [],
        "next_action": next_action,
        "finished_at": now,
        "updated_at": now,
    }
    res = db[COL_AGENT_ACTIVITY].insert_one(doc)
    mongo_store.register_change(
        agent=agent,
        project=doc.get("project") or "ralfia-orchestration",
        path=",".join(files_changed or [])[:500] or "activity",
        summary=summary,
        change_type="agent_activity",
        metadata={"activity_id": str(res.inserted_id), "task_id": task_id},
    )
    return {"ok": True, "activity_id": str(res.inserted_id), "activity": _serialize(doc)}


def list_recent_activity(agent: str | None = None, limit: int = 30) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if agent:
        filt["agent"] = agent.upper()
    cursor = db[COL_AGENT_ACTIVITY].find(filt).sort("updated_at", -1).limit(max(1, min(limit, 100)))
    items = [_serialize(d) for d in cursor]
    return {"ok": True, "count": len(items), "items": items}
