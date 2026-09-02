"""Estado vivo de coordinación — revisión única que todas las IAs deben leer."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.settings import COL_AGENT_MESSAGES, COORD_ROOT

STATE_KEY = "coordination_live"
OPS_TASKS_COL = "ralfia_ops_tasks"
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_display() -> str:
    from raphiia_openai import ralfia_time

    return ralfia_time.format_log()


def _task_id() -> str:
    return f"ops_{secrets.token_hex(6)}"


def bump_revision(*, reason: str, source: str = "system", current_priority: dict[str, Any] | None = None) -> dict[str, Any]:
    db = mongo_store.get_db()
    doc = db[mongo_store.COL_COORDINATION_STATE].find_one({"key": STATE_KEY}) or {}
    rev = int(doc.get("revision") or 0) + 1
    payload = {
        "key": STATE_KEY,
        "revision": rev,
        "updated_at": _now(),
        "updated_at_display": _now_display(),
        "reason": reason[:500],
        "source": source,
        "mandatory_reads": list(MANDATORY_READS),
    }
    if current_priority:
        payload["current_priority"] = current_priority
    mongo_store.upsert_coordination_state(key=STATE_KEY, data={k: v for k, v in payload.items() if k != "key"})
    refresh_estado_vivo()
    mongo_store.log_coordination(
        agent=source.upper()[:20],
        summary=f"coordination revision {rev}: {reason[:120]}",
        event="coordination_revision",
        project="ralfia-coordination",
        metadata={"revision": rev},
    )
    return {"ok": True, "revision": rev, "reason": reason}


def _unread_messages() -> dict[str, int]:
    db = mongo_store.get_db()
    out: dict[str, int] = {}
    for agent in ("cursor", "codex", "antigravity", "chatgpt", "gemini", "notion"):
        n = db[COL_AGENT_MESSAGES].count_documents({"target_agent": agent, "status": "open"})
        if n:
            out[agent] = n
    return out


def _open_ops_tasks(limit: int = 10) -> list[dict[str, Any]]:
    from raphiia_openai.racb_protocol import ACTIVE_STATUSES

    open_statuses = sorted(set(ACTIVE_STATUSES) | {"pending", "dispatched"})
    db = mongo_store.get_db()
    items = list(
        db[OPS_TASKS_COL]
        .find({"status": {"$in": open_statuses}}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return items


def _recent_feed_lines(limit: int = 8) -> list[str]:
    feed = COORD_ROOT / "HUB" / "feed.md"
    if not feed.is_file():
        return []
    lines = [ln.strip() for ln in feed.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip().startswith("-")]
    return lines[-limit:]


def refresh_estado_vivo() -> dict[str, Any]:
    live = get_coordination_live()
    rev = live.get("revision", 0)
    unread = live.get("unread_messages", {})
    tasks = live.get("open_ops_tasks", [])
    feed = live.get("recent_feed", [])
    priority = live.get("current_priority") or {}

    lines = [
        "# ESTADO VIVO — coordinación RalfIA",
        "",
        f"**Revisión:** `{rev}` · **Actualizado:** {live.get('updated_at_display', '—')} (auto cada ~2 min, daemon AG-25)",
        "",
        "> **Rafael / cualquier IA:** si tu revisión leída es menor que esta, **estás desactualizado**.",
        "> MCP: `get_coordination_live()` · al terminar: `ack_coordination_revision(agent, revision)`.",
        "",
        "---",
        "",
        "## 1. Lectura obligatoria (mismo orden para todos)",
        "",
    ]
    for i, path in enumerate(MANDATORY_READS, 1):
        lines.append(f"{i}. `{path}`")
    lines.extend(["", "## 2. Órdenes pendientes (ops_tasks)", ""])
    if tasks:
        for t in tasks[:8]:
            lines.append(
                f"- **{t.get('task_id')}** → `{t.get('assignee')}` · {t.get('priority', 'normal')} · {t.get('title', '')[:80]}"
            )
    else:
        lines.append("_Sin órdenes ops pendientes._")
    lines.extend(["", "## 3. Mensajes abiertos por agente", ""])
    if unread:
        for agent, count in sorted(unread.items()):
            lines.append(f"- **{agent}**: {count} mensaje(s) `open` en Mongo")
    else:
        lines.append("_Sin mensajes open pendientes._")
    lines.extend(["", "## 4. Últimos cambios (feed)", ""])
    lines.extend(feed or ["_Sin líneas recientes._"])
    if priority:
        lines.extend(["", "## 5. Prioridad Rafael", ""])
        lines.append(f"**{priority.get('title', '—')}**")
        if priority.get("summary"):
            lines.append(priority["summary"])
        if priority.get("tools"):
            lines.append(f"- Tools MCP: `{', '.join(priority['tools'])}`")
        if priority.get("doc"):
            lines.append(f"- Spec: `{priority['doc']}`")
    lines.extend([
        "",
        "---",
        "",
        "## Cómo funciona (no es webhook entre IAs)",
        "",
        "- **Broadcast** = archivo + INBOX + Mongo (tablón; no ejecuta solo).",
        "- **Webhook Notion** = Notion plataforma → servidor (no Notion AI ↔ Cursor).",
        "- **Órdenes** = `create_ops_task` → Mongo `ralfia_ops_tasks` + INBOX del assignee.",
        "- **Daemon AG-25** = regenera este archivo + HUB/feed cada ~2 min.",
        "",
        f"_Generado automáticamente · revisión {rev}_",
    ])
    ESTADO_VIVO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_VIVO_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(ESTADO_VIVO_PATH), "revision": rev}


def get_coordination_live() -> dict[str, Any]:
    state = mongo_store.get_coordination_state(STATE_KEY)
    st = (state.get("state") or {}) if state.get("ok") else {}
    rev = int(st.get("revision") or 0)
    unread = _unread_messages()
    tasks = _open_ops_tasks()
    acks = st.get("agent_acks") or {}
    return {
        "ok": True,
        "revision": rev,
        "updated_at": st.get("updated_at"),
        "updated_at_display": st.get("updated_at_display"),
        "reason": st.get("reason"),
        "mandatory_reads": list(MANDATORY_READS),
        "estado_vivo_path": "HUB/ESTADO_VIVO.md",
        "unread_messages": unread,
        "open_ops_tasks": tasks,
        "open_ops_count": len(tasks),
        "recent_feed": _recent_feed_lines(),
        "agent_acks": acks,
        "current_priority": st.get("current_priority"),
        "daemon": {"name": "AG-25", "interval_sec": 120, "expected": "active"},
        "chatgpt_note": (
            "Sugerencia ChatGPT jul-2026: correlation_id en órdenes; "
            "Notion webhook→Mongo; respuestas→Notion comentario (pendiente AG-07)."
        ),
    }


def ack_coordination_revision(agent: str, revision: int) -> dict[str, Any]:
    name = (agent or "").strip().lower()
    if not name:
        return {"ok": False, "error": "agent_required"}
    state = mongo_store.get_coordination_state(STATE_KEY)
    st = (state.get("state") or {}) if state.get("ok") else {}
    current = int(st.get("revision") or 0)
    acks = dict(st.get("agent_acks") or {})
    acks[name] = {"revision": int(revision), "acked_at": _now()}
    mongo_store.upsert_coordination_state(key=STATE_KEY, data={"agent_acks": acks})
    behind = int(revision) < current
    return {
        "ok": True,
        "agent": name,
        "acked_revision": int(revision),
        "current_revision": current,
        "behind": behind,
        "message": "Desactualizado — relee HUB/ESTADO_VIVO.md" if behind else "Al día",
    }


def create_ops_task(
    *,
    assignee: str,
    title: str,
    checklist: list[str] | str | None = None,
    evidence_required: list[str] | str | None = None,
    priority: str = "normal",
    from_agent: str = "RAFAEL",
    correlation_id: str | None = None,
    source_message_id: str | None = None,
    conversation_ref: str | None = None,
    related_project: str | None = None,
) -> dict[str, Any]:
    assignee_l = (assignee or "").strip().lower()
    if assignee_l not in ASSIGNEES:
        return {"ok": False, "error": f"invalid_assignee: {assignee}"}

    def _norm_list(val: list[str] | str | None) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [ln.strip() for ln in val.splitlines() if ln.strip()]
        return [str(x).strip() for x in val if str(x).strip()]

    items = _norm_list(checklist)
    evidence = _norm_list(evidence_required) or ["status OK/PARTIAL/FAIL", "outputs o conteos Mongo"]
    cid = (correlation_id or "").strip() or _task_id()
    db = mongo_store.get_db()
    existing = db[OPS_TASKS_COL].find_one(
        {
            "correlation_id": cid,
            "assignee": assignee_l,
            "status": {"$nin": ["cancelled", "failed", "superseded"]},
        },
        {"_id": 0},
    )
    if existing:
        return {
            "ok": True,
            "created": False,
            "idempotent": True,
            "task": existing,
            "task_id": existing["task_id"],
            "correlation_id": cid,
        }

    tid = _task_id()
    now = _now()
    doc = {
        "task_id": tid,
        "correlation_id": cid,
        "assignee": assignee_l,
        "from_agent": (from_agent or "RAFAEL").upper(),
        "title": title.strip(),
        "checklist": items,
        "evidence_required": evidence,
        "priority": (priority or "normal").lower(),
        "status": "proposed",
        "owner": None,
        "revision": 1,
        "protocol_version": "1.0.0",
        "state_history": [],
        "created_at": now,
        "updated_at": now,
        "evidence": {},
        "source_message_id": (source_message_id or "").strip() or None,
        "conversation_ref": (conversation_ref or "").strip() or None,
        "related_project": (related_project or "").strip() or None,
    }
    # PyMongo mutates the inserted mapping by adding ``_id``. Keep the public
    # tool response JSON-safe so MCP can return structuredContent reliably.
    db[OPS_TASKS_COL].insert_one(dict(doc))

    body = (
        f"**Orden ops:** `{tid}` · correlation `{cid}`\n\n"
        f"**Prioridad:** {doc['priority']}\n\n"
        f"**Checklist:**\n" + "\n".join(f"- [ ] {x}" for x in items) + "\n\n"
        f"**Evidencia requerida:**\n" + "\n".join(f"- {x}" for x in evidence) + "\n\n"
        f"Al terminar: `complete_ops_task('{tid}', status='completed', evidence={{...}})` "
        f"y `ack_coordination_revision('{assignee_l}', revision)`."
    )
    from raphiia_openai.memory.agent_messages import create_agent_message

    create_agent_message(
        from_agent=from_agent,
        target_agent=assignee_l,
        title=f"[OPS] {title[:100]}",
        body=body,
        priority=priority,
        correlation_id=cid,
        message_type="task",
        payload={
            "task_id": tid,
            "source_message_id": doc["source_message_id"],
            "conversation_ref": doc["conversation_ref"],
            "related_project": doc["related_project"],
        },
        related_project=doc["related_project"],
        tags=["ops_task", tid, cid],
    )
    bump_revision(reason=f"ops_task {tid} → {assignee_l}", source=from_agent)
    return {
        "ok": True,
        "created": True,
        "idempotent": False,
        "task": {k: v for k, v in doc.items()},
        "task_id": tid,
        "correlation_id": cid,
    }


def heartbeat_ops_task(
    task_id: str,
    actor: str,
    *,
    next_action: str | None = None,
    blocker: str | None = None,
    files_touched: list[str] | None = None,
) -> dict[str, Any]:
    """Record liveness for an accepted/active task without completing it."""
    db = mongo_store.get_db()
    actor_n = (actor or "").strip().lower()
    task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found"}
    if not actor_n:
        return {"ok": False, "error": "actor_required"}
    if task.get("owner") not in (None, actor_n):
        return {"ok": False, "error": "ownership_conflict", "owner": task.get("owner"), "actor": actor_n}
    active_statuses = {"accepted", "in_progress", "blocked", "awaiting_approval", "verification", "partial"}
    if task.get("status") not in active_statuses:
        return {"ok": False, "error": "task_not_active", "status": task.get("status")}

    now = _now()
    patch: dict[str, Any] = {
        "last_heartbeat_at": now,
        "updated_at": now,
        "updated_by": actor_n,
    }
    if next_action is not None:
        patch["next_action"] = next_action.strip() or None
    if blocker is not None:
        patch["blocker"] = blocker.strip() or None
    if files_touched is not None:
        patch["files_touched"] = [str(path).strip() for path in files_touched if str(path).strip()]
    history = {"at": now, "actor": actor_n, "next_action": patch.get("next_action"), "blocker": patch.get("blocker")}
    result = db[OPS_TASKS_COL].update_one(
        {"task_id": task_id, "status": task.get("status")},
        {"$set": patch, "$push": {"heartbeat_history": {"$each": [history], "$slice": -100}}},
    )
    return {
        "ok": result.modified_count == 1,
        "task_id": task_id,
        "status": task.get("status"),
        "last_heartbeat_at": now,
        "owner": task.get("owner") or actor_n,
    }


def update_ops_task_state(
    task_id: str,
    status: str,
    actor: str,
    evidence: dict[str, Any] | None = None,
    expected_revision: int | None = None,
    force_handoff: bool = False,
    allow_legacy_direct: bool = False,
) -> dict[str, Any]:
    """Apply a RACB state transition with ownership and optimistic locking."""
    from raphiia_openai import racb_protocol

    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found"}

    current_revision = int(task.get("revision") or 1)
    if expected_revision is not None and int(expected_revision) != current_revision:
        return {
            "ok": False,
            "error": "revision_conflict",
            "expected_revision": int(expected_revision),
            "current_revision": current_revision,
        }

    transition = racb_protocol.build_transition(
        current_status=str(task.get("status") or "pending"),
        target_status=status,
        actor=actor,
        current_revision=current_revision,
        owner=task.get("owner"),
        evidence=evidence,
        force_handoff=force_handoff,
        allow_legacy_direct=allow_legacy_direct,
    )
    if not transition.get("ok"):
        return {**transition, "task_id": task_id}
    if transition.get("idempotent"):
        return {
            "ok": True,
            "idempotent": True,
            "task_id": task_id,
            "status": racb_protocol.normalize_status(status),
            "revision": current_revision,
        }

    revision_filter = {
        "$or": [
            {"revision": current_revision},
            {"revision": {"$exists": False}},
        ]
    }
    result = db[OPS_TASKS_COL].update_one(
        {"task_id": task_id, "status": task.get("status"), **revision_filter},
        {"$set": transition["patch"], "$push": {"state_history": transition["history"]}},
    )
    if result.modified_count != 1:
        return {"ok": False, "error": "concurrent_transition", "task_id": task_id}

    bump_revision(reason=f"ops_task {task_id} → {transition['patch']['status']}", source=actor)
    return {
        "ok": True,
        "idempotent": False,
        "task_id": task_id,
        "status": transition["patch"]["status"],
        "revision": transition["revision"],
        "owner": transition["patch"].get("owner", task.get("owner")),
    }


def complete_ops_task(
    task_id: str,
    status: str = "completed",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    st = (status or "completed").strip().lower()
    transition = update_ops_task_state(
        task_id=task_id,
        status=st,
        actor="system",
        evidence=evidence,
        force_handoff=True,
        allow_legacy_direct=True,
    )
    if not transition.get("ok"):
        return transition
    db = mongo_store.get_db()
    task_doc = db[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
    notion_out: dict[str, Any] | None = None
    cid = task_doc.get("correlation_id")
    if cid:
        try:
            from raphiia_openai.notion_coordination import post_response_to_notion

            summary = (evidence or {}).get("summary") or str(evidence or "")[:500] or f"Task {st}"
            notion_out = post_response_to_notion(
                correlation_id=cid,
                status="Completed" if st == "completed" else "Failed",
                summary=summary,
                evidence=evidence,
            )
        except Exception as exc:
            notion_out = {"ok": False, "error": str(exc)}
    return {**transition, "notion_response": notion_out}


def list_ops_tasks(assignee: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if assignee:
        filt["assignee"] = assignee.strip().lower()
    if status:
        filt["status"] = status.strip().lower()
    items = list(db[OPS_TASKS_COL].find(filt, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 50))))
    return {"ok": True, "count": len(items), "tasks": items}
