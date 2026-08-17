"""Agent messages — canal único: Mongo canónico + INBOX markdown espejo.

Schema canónico (única verdad):
  message_id, from_agent, target_agent, title, body, priority, status,
  created_at, updated_at, resolved_at, source_file, ts_display

Reglas:
- Una sola tool de escritura: create_agent_message (write_agent_message es alias).
- Markdown INBOX se regenera desde Mongo (compact); append inmediato al escribir.
- Espejo ChatGPT/ se sincroniza desde chatgpt/ canónico.
- Si Markdown y Mongo divergen, Mongo manda.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.settings import COL_AGENT_MESSAGES

OPEN_STATUSES = {"open", "acknowledged", "in_progress", "blocked"}
VISIBLE_INBOX_STATUSES = {"open", "acknowledged", "in_progress", "blocked"}
TERMINAL_STATUSES = {"done", "cancelled", "obsolete", "superseded"}
LEGACY_OPEN_STATUSES = {"delivered"}  # schema viejo de write_agent_message

MAILBOX_AGENTS = ("cursor", "codex", "antigravity", "gemini", "chatgpt", "notion", "rafael")
MESSAGE_TYPES = frozenset({"message", "task", "status", "handoff", "reply", "event", "approval"})


def _new_id() -> str:
    return f"msg_{secrets.token_hex(8)}"


def _coord_root() -> Path:
    from raphiia_openai.coordination_docs import COORD_ROOT

    return COORD_ROOT


def _normalize_agent(name: str) -> str:
    return (name or "").strip().lower()


def _normalize_from(name: str) -> str:
    return (name or "SYSTEM").strip().upper()


def _ensure_inbox_file(agent: str) -> Path:
    root = _coord_root()
    path = root / agent
    path.mkdir(parents=True, exist_ok=True)
    inbox = path / "INBOX.md"
    if not inbox.exists():
        inbox.write_text(
            f"# {agent.title()} — INBOX\n\n"
            f"Mensajes **para** {agent} (Mongo `ralfia_agent_messages`).\n\n---\n\n",
            encoding="utf-8",
        )
    return inbox


def _mirror_chatgpt_inbox(content: str) -> None:
    """Espejo de compatibilidad: ChatGPT/INBOX.md ← chatgpt/INBOX.md."""
    root = _coord_root()
    alias = root / "ChatGPT"
    alias.mkdir(parents=True, exist_ok=True)
    (alias / "INBOX.md").write_text(content, encoding="utf-8")


def sync_chatgpt_mirror() -> dict[str, Any]:
    """Copia canónica chatgpt/ → ChatGPT/ (INBOX + OUTBOX + INSTRUCTIONS)."""
    root = _coord_root()
    src = root / "chatgpt"
    dst = root / "ChatGPT"
    dst.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in ("INBOX.md", "OUTBOX.md", "INSTRUCTIONS.md", "README.md"):
        sp = src / name
        if sp.is_file():
            (dst / name).write_text(sp.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            copied.append(name)
    return {"ok": True, "copied": copied, "canonical": "chatgpt/", "mirror": "ChatGPT/"}


def append_inbox_markdown(
    *,
    from_agent: str,
    target_agent: str,
    title: str,
    body: str,
    priority: str,
    message_id: str,
) -> str:
    """Append inmediato al INBOX del destino (espejo MD). No toca Mongo."""
    target = _normalize_agent(target_agent)
    inbox_path = _ensure_inbox_file(target)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = (
        f"\n## {ts} — {_normalize_from(from_agent)}\n\n"
        f"**Priority:** {priority}\n"
        f"**ID:** `{message_id}`\n\n"
        f"**{title.strip()}**\n\n"
        f"{body.strip()}\n"
    )
    content = inbox_path.read_text(encoding="utf-8", errors="replace").rstrip() + block + "\n"
    inbox_path.write_text(content, encoding="utf-8")
    if target == "chatgpt":
        _mirror_chatgpt_inbox(content)
    return str(inbox_path.relative_to(_coord_root()))


def create_agent_message(
    *,
    from_agent: str,
    target_agent: str,
    title: str,
    body: str,
    priority: str = "normal",
    related_project: str | None = None,
    tags: list[str] | None = None,
    sync_inbox: bool = True,
    correlation_id: str | None = None,
    message_type: str = "message",
    payload: dict[str, Any] | None = None,
    reply_to: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Canal único de mensajería entre agentes."""
    db = mongo_store.get_db()
    now = ralfia_time.now_utc_iso()
    message_id = _new_id()
    target = _normalize_agent(target_agent)
    sender = _normalize_from(from_agent)
    type_n = (message_type or "message").strip().lower()
    if target not in MAILBOX_AGENTS:
        return {"ok": False, "error": f"invalid_target_agent: {target}", "allowed": list(MAILBOX_AGENTS)}
    if type_n not in MESSAGE_TYPES:
        return {"ok": False, "error": f"invalid_message_type: {type_n}", "allowed": sorted(MESSAGE_TYPES)}

    idempotency_n = (idempotency_key or "").strip() or None
    if idempotency_n:
        existing = db[COL_AGENT_MESSAGES].find_one(
            {"target_agent": target, "idempotency_key": idempotency_n},
        )
        if existing:
            return {
                "ok": True,
                "created": False,
                "idempotent": True,
                "message_id": existing.get("message_id"),
                "path": existing.get("source_file"),
                "message": mongo_store._serialize(existing),
            }

    doc = {
        "message_id": message_id,
        "from_agent": sender,
        "target_agent": target,
        "type": type_n,
        "title": title.strip(),
        "body": body.strip(),
        "payload": payload or {},
        "correlation_id": (correlation_id or "").strip() or message_id,
        "reply_to": (reply_to or "").strip() or None,
        "idempotency_key": idempotency_n,
        "priority": (priority or "normal").lower(),
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "superseded_by": None,
        "related_project": related_project,
        "tags": tags or [],
        "source_file": f"{target}/INBOX.md",
        "ts_display": ralfia_time.format_log(),
        "acknowledged_at": None,
        "acknowledged_by": None,
        "schema_version": 3,
    }
    db[COL_AGENT_MESSAGES].insert_one(doc)
    path = None
    if sync_inbox:
        path = append_inbox_markdown(
            from_agent=sender,
            target_agent=target,
            title=title,
            body=f"{body.strip()}\n\n_Mongo ID: `{message_id}`_",
            priority=doc["priority"],
            message_id=message_id,
        )
    mongo_store.log_coordination(
        agent=sender,
        summary=f"agent_message → {target}: {title[:80]}",
        event="agent_message",
        project=related_project or "ralfia-coordination",
        tool_used="create_agent_message",
        metadata={"message_id": message_id, "priority": doc["priority"], "target_agent": target},
    )
    return {
        "ok": True,
        "created": True,
        "idempotent": False,
        "message_id": message_id,
        "correlation_id": doc["correlation_id"],
        "path": path,
        "message": mongo_store._serialize(doc),
    }


def ack_agent_message(message_id: str, agent: str) -> dict[str, Any]:
    """Acknowledge receipt without claiming that the work is complete."""
    db = mongo_store.get_db()
    agent_n = _normalize_agent(agent)
    message = db[COL_AGENT_MESSAGES].find_one({"message_id": message_id})
    if not message:
        return {"ok": False, "error": "message_not_found"}
    if message.get("target_agent") != agent_n:
        return {
            "ok": False,
            "error": "ack_agent_mismatch",
            "target_agent": message.get("target_agent"),
            "agent": agent_n,
        }
    if message.get("status") == "acknowledged":
        return {"ok": True, "idempotent": True, "message_id": message_id, "status": "acknowledged", "acknowledged_at": message.get("acknowledged_at")}
    if message.get("status") != "open":
        return {"ok": False, "error": "message_not_open", "status": message.get("status")}

    now = ralfia_time.now_utc_iso()
    result = db[COL_AGENT_MESSAGES].update_one(
        {"message_id": message_id, "status": "open"},
        {
            "$set": {
                "status": "acknowledged",
                "acknowledged_at": now,
                "acknowledged_by": agent_n,
                "updated_at": now,
                "schema_version": 3,
            }
        },
    )
    if result.modified_count != 1:
        return {"ok": False, "error": "concurrent_ack", "message_id": message_id}
    return {"ok": True, "idempotent": False, "message_id": message_id, "status": "acknowledged", "acknowledged_at": now}


def write_agent_message(
    target_agent: str,
    title: str,
    body: str,
    priority: str | None = None,
    from_agent: str = "CHATGPT",
) -> dict[str, Any]:
    """Alias MCP legacy → canal único. ChatGPT suele llamar esto sin from_agent."""
    return create_agent_message(
        from_agent=from_agent,
        target_agent=target_agent,
        title=title,
        body=body,
        priority=priority or "normal",
    )


def list_agent_messages(
    *,
    agent: str | None = None,
    status: str | None = None,
    limit: int = 20,
    role: str = "inbox",
) -> dict[str, Any]:
    """Lista mensajes. role=inbox (recibidos) | sent | all."""
    db = mongo_store.get_db()
    limit = max(1, min(int(limit), 100))
    filt: dict[str, Any] = {}
    if agent:
        a = _normalize_agent(agent)
        au = agent.strip().upper()
        role_n = (role or "inbox").strip().lower()
        if role_n == "inbox":
            filt["target_agent"] = {"$in": [a, a.upper()]}
        elif role_n == "sent":
            filt["$or"] = [{"from_agent": au}, {"agent": au}]
        else:
            filt["$or"] = [{"target_agent": a}, {"from_agent": au}, {"agent": au}]
    if status:
        filt["status"] = status.strip().lower()
    # Prefer created_at; legacy docs use ts
    cursor = db[COL_AGENT_MESSAGES].find(filt).sort([("created_at", -1), ("ts", -1)]).limit(limit)
    items = [mongo_store._serialize(d) for d in cursor]
    # Normalize display fields for legacy docs
    for item in items:
        if not item.get("from_agent") and item.get("agent"):
            item["from_agent"] = item["agent"]
        if not item.get("message_id"):
            item["message_id"] = item.get("_id") or "legacy"
        if not item.get("created_at") and item.get("ts"):
            item["created_at"] = item["ts"]
    return {"ok": True, "count": len(items), "messages": items, "role": role}


def poll_agent_inbox(*, agent: str, limit: int = 20, auto_ack: bool = True) -> dict[str, Any]:
    """Poll open inbox messages and atomically acknowledge those delivered to the caller."""
    result = list_agent_messages(agent=agent, status="open", limit=limit, role="inbox")
    if not result.get("ok") or not auto_ack:
        return {**result, "auto_ack": False, "acknowledged": []}
    acknowledged: list[str] = []
    errors: list[dict[str, Any]] = []
    for message in result.get("messages", []):
        message_id = str(message.get("message_id") or "")
        ack = ack_agent_message(message_id, agent)
        if ack.get("ok"):
            acknowledged.append(message_id)
            message["status"] = "acknowledged"
            message["acknowledged_by"] = _normalize_agent(agent)
            message["acknowledged_at"] = ack.get("acknowledged_at")
        else:
            errors.append({"message_id": message_id, "error": ack.get("error")})
    return {
        **result,
        "auto_ack": True,
        "acknowledged": acknowledged,
        "ack_count": len(acknowledged),
        "ack_errors": errors,
    }


def update_agent_message_status(message_id: str, status: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    st = status.strip().lower()
    if st not in OPEN_STATUSES | TERMINAL_STATUSES | LEGACY_OPEN_STATUSES:
        return {"ok": False, "error": f"invalid_status: {st}"}
    patch: dict[str, Any] = {"status": st, "updated_at": ralfia_time.now_utc_iso()}
    if st == "acknowledged":
        patch["acknowledged_at"] = ralfia_time.now_utc_iso()
    if st in TERMINAL_STATUSES:
        patch["resolved_at"] = ralfia_time.now_utc_iso()
    res = db[COL_AGENT_MESSAGES].update_one({"message_id": message_id}, {"$set": patch})
    if res.matched_count == 0:
        # legacy docs without message_id
        res = db[COL_AGENT_MESSAGES].update_one({"_id": message_id}, {"$set": patch})
        if res.matched_count == 0:
            return {"ok": False, "error": "message_not_found"}
    return {"ok": True, "message_id": message_id, "status": st}


def migrate_legacy_agent_messages() -> dict[str, Any]:
    """Convierte schema viejo (agent/ts/delivered) → canónico (from_agent/created_at/open)."""
    db = mongo_store.get_db()
    migrated = 0
    skipped = 0
    # Docs without from_agent but with agent=
    legacy = list(db[COL_AGENT_MESSAGES].find({"from_agent": {"$exists": False}}))
    for doc in legacy:
        sender = (doc.get("agent") or doc.get("from") or "SYSTEM")
        if isinstance(sender, str):
            sender = sender.strip().upper()
        else:
            sender = "SYSTEM"
        created = doc.get("ts") or doc.get("created_at") or ralfia_time.now_utc_iso()
        status = doc.get("status") or "open"
        if status in LEGACY_OPEN_STATUSES:
            status = "open"
        message_id = doc.get("message_id") or _new_id()
        patch = {
            "message_id": message_id,
            "from_agent": sender,
            "created_at": created,
            "updated_at": ralfia_time.now_utc_iso(),
            "status": status,
            "schema_version": 2,
            "source_file": doc.get("path") or doc.get("source_file") or f"{doc.get('target_agent', 'unknown')}/INBOX.md",
            "ts_display": doc.get("ts_display") or ralfia_time.format_log(),
        }
        if "target_agent" not in doc and doc.get("to_agent"):
            patch["target_agent"] = _normalize_agent(doc["to_agent"])
        db[COL_AGENT_MESSAGES].update_one({"_id": doc["_id"]}, {"$set": patch})
        migrated += 1

    # Also promote any remaining delivered → open
    res = db[COL_AGENT_MESSAGES].update_many(
        {"status": "delivered"},
        {"$set": {"status": "open", "updated_at": ralfia_time.now_utc_iso()}},
    )
    promoted = res.modified_count

    normalized_targets = 0
    for target in MAILBOX_AGENTS:
        res = db[COL_AGENT_MESSAGES].update_many(
            {"target_agent": target.upper()},
            {
                "$set": {
                    "target_agent": target,
                    "updated_at": ralfia_time.now_utc_iso(),
                    "schema_version": 3,
                }
            },
        )
        normalized_targets += res.modified_count

    # Docs with from_agent but missing message_id
    for doc in db[COL_AGENT_MESSAGES].find({"message_id": {"$exists": False}}):
        db[COL_AGENT_MESSAGES].update_one(
            {"_id": doc["_id"]},
            {"$set": {"message_id": _new_id(), "schema_version": 2}},
        )
        skipped += 1  # counted as backfill

    return {
        "ok": True,
        "migrated_legacy": migrated,
        "promoted_delivered_to_open": promoted,
        "normalized_target_agents": normalized_targets,
        "backfilled_message_id": skipped,
    }


def compact_agent_mailbox(agent: str, *, max_open: int = 20, archive_days: int = 30) -> dict[str, Any]:
    """Regenera INBOX.md desde Mongo (solo recibidos abiertos). No pierde mensajes open."""
    name = _normalize_agent(agent)
    inbox_path = _ensure_inbox_file(name)

    open_msgs = list_agent_messages(agent=name, status="open", limit=max_open, role="inbox")
    in_prog = list_agent_messages(agent=name, status="in_progress", limit=max_open, role="inbox")
    blocked = list_agent_messages(agent=name, status="blocked", limit=max_open, role="inbox")

    # Merge unique by message_id, newest first
    by_id: dict[str, dict[str, Any]] = {}
    for bucket in (open_msgs, in_prog, blocked):
        for msg in bucket.get("messages", []):
            mid = msg.get("message_id") or msg.get("_id")
            if mid and mid not in by_id:
                by_id[mid] = msg
    ordered = sorted(
        by_id.values(),
        key=lambda m: m.get("created_at") or m.get("ts") or "",
        reverse=True,
    )[:max_open]

    intro = (
        f"# {name.title()} — INBOX\n\n"
        f"Mensajes **para** {name}. Fuente de verdad: Mongo `ralfia_agent_messages`.\n"
        f"Leer: `list_agent_messages(agent='{name}', role='inbox')`.\n"
        f"Responder: `create_agent_message(from_agent='{name.upper()}', target_agent=..., ...)` "
        f"o OUTBOX.md + evidencia.\n\n---\n\n"
    )
    lines = [intro.rstrip(), f"## Compactado {ralfia_time.format_log()}\n"]
    for msg in ordered:
        mid = msg.get("message_id") or "legacy"
        lines.append(
            f"### [{msg.get('status')}] {msg.get('title')} — `{mid}`\n"
            f"**From:** {msg.get('from_agent') or msg.get('agent')} · **Priority:** {msg.get('priority')}\n"
            f"**Created:** {msg.get('created_at') or msg.get('ts')}\n\n"
            f"{(msg.get('body') or '')[:1200]}\n"
        )
    lines.append(
        f"\n_Histórico completo en Mongo. IDs visibles: {len(ordered)}. "
        f"Canal único: `create_agent_message` / alias `write_agent_message`._\n"
    )
    content = "\n".join(lines)
    inbox_path.write_text(content, encoding="utf-8")
    if name == "chatgpt":
        _mirror_chatgpt_inbox(content)

    archived = update_old_messages(agent=name, older_than_days=archive_days)
    return {
        "ok": True,
        "agent": name,
        "open_shown": len(ordered),
        "archived": archived,
        "message_ids": [m.get("message_id") for m in ordered],
    }


def compact_all_mailboxes(*, max_open: int = 20) -> dict[str, Any]:
    results = []
    for agent in MAILBOX_AGENTS:
        if agent == "rafael":
            continue
        results.append(compact_agent_mailbox(agent, max_open=max_open))
    mirror = sync_chatgpt_mirror()
    return {"ok": True, "mailboxes": results, "chatgpt_mirror": mirror}


def update_old_messages(agent: str, older_than_days: int = 30) -> int:
    db = mongo_store.get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    res = db[COL_AGENT_MESSAGES].update_many(
        {
            "target_agent": _normalize_agent(agent),
            "status": "open",
            "created_at": {"$lt": cutoff},
        },
        {"$set": {"status": "obsolete", "updated_at": ralfia_time.now_utc_iso()}},
    )
    return res.modified_count
