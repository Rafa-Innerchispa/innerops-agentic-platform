"""AG-57 Backlog Steward — recordatorio diario WhatsApp + asignar agentes locales.

Lee Mongo ralfia_dev_backlog (no logs). Permite a Rafael:
  - Ver pendientes / olvidados / en progreso
  - Decir «desarrolla 3» o «haz dedupe contifico»
  - Asignar ops_task + dispatch local cuando aplique
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import dev_backlog, mongo_store, ralfia_time
from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.notifications.evolution_client import send_whatsapp
from raphiia_openai.notifications.settings import NOTIFY_WHATSAPP_TO

AGENT_ID = "AG-57_BACKLOG_STEWARD"
SESSION_COL = "whatsapp_backlog_sessions"

_STATUS_EMOJI = {
    "planned": "📋",
    "in_progress": "🔧",
    "discussed": "💭",
    "deferred": "⏸",
    "forgotten": "😴",
    "done": "✅",
    "cancelled": "🚫",
    "superseded": "↪",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _priority_rank(item: dict[str, Any]) -> tuple[int, str]:
    tags = [t.lower() for t in (item.get("tags") or [])]
    status = (item.get("status") or "").lower()
    score = 50
    if "p0" in tags or status == "in_progress":
        score = 0
    elif status == "planned":
        score = 10
    elif status == "discussed":
        score = 30
    elif status == "forgotten":
        score = 40
    elif status == "deferred":
        score = 60
    return score, item.get("updated_at") or ""


def _fetch_open_items(limit: int = 25) -> list[dict[str, Any]]:
    result = dev_backlog.list_dev_backlog(
        status=None,
        limit=limit * 2,
    )
    open_status = {"planned", "in_progress", "discussed", "deferred", "forgotten"}
    items = [i for i in result.get("items", []) if (i.get("status") or "") in open_status]
    items.sort(key=_priority_rank)
    return items[:limit]


def format_backlog_whatsapp_text(*, greeting: bool = True, limit: int = 12) -> str:
    summary = dev_backlog.get_dev_backlog_summary(stale_days=14)
    items = _fetch_open_items(limit=limit)
    by = summary.get("by_status") or {}
    lines = []
    if greeting:
        hour = datetime.now().hour
        saludo = "Buenos días" if hour < 12 else ("Buenas tardes" if hour < 19 else "Buenas noches")
        lines.extend([f"*{saludo} Rafael* 👋", f"*{AGENT_ID.replace('_', ' ')}*", ""])
    lines.append(
        f"Tienes *{by.get('planned', 0)}* planificados, "
        f"*{by.get('in_progress', 0)}* en curso, "
        f"*{by.get('discussed', 0)}* conversados y "
        f"*{summary.get('stale_open_count', 0)}* sin tocar +14 días."
    )
    lines.append("")
    if not items:
        lines.append("No hay pendientes abiertos en el backlog 🎉")
        return "\n".join(lines)

    lines.append("*Prioridad ahora:*")
    for idx, item in enumerate(items, start=1):
        st = item.get("status") or "?"
        emoji = _STATUS_EMOJI.get(st, "•")
        title = (item.get("title") or "")[:72]
        proj = item.get("project") or ""
        suffix = f" ({proj})" if proj else ""
        lines.append(f"{idx}. {emoji} [{st}] {title}{suffix}")

    lines.extend(
        [
            "",
            "*Responde:*",
            "• *pendientes* — lista completa",
            "• *desarrolla 1* — asignar item #1 a agentes",
            "• *cursor: …* / *codex: …* — orden directa",
            "• *local: guardian* — agente local inmediato",
        ]
    )
    return "\n".join(lines)


def _save_session(sender: str, items: list[dict[str, Any]]) -> None:
    _db()[SESSION_COL].update_one(
        {"sender": sender},
        {
            "$set": {
                "sender": sender,
                "item_ids": [i.get("item_id") for i in items],
                "items_snapshot": [
                    {"n": n, "item_id": i.get("item_id"), "title": i.get("title"), "status": i.get("status")}
                    for n, i in enumerate(items, start=1)
                ],
                "updated_at": _now(),
            }
        },
        upsert=True,
    )


def _load_session(sender: str) -> dict[str, Any] | None:
    return _db()[SESSION_COL].find_one({"sender": sender})


def _resolve_item(sender: str, ref: str) -> dict[str, Any] | None:
    ref = (ref or "").strip()
    session = _load_session(sender)
    if ref.isdigit() and session:
        n = int(ref)
        snap = session.get("items_snapshot") or []
        for row in snap:
            if row.get("n") == n:
                item_id = row.get("item_id")
                if item_id:
                    from raphiia_openai.settings import COL_DEV_BACKLOG

                    doc = _db()[COL_DEV_BACKLOG].find_one({"item_id": item_id})
                    if doc:
                        return mongo_store._serialize(doc)
    # búsqueda por título
    from raphiia_openai.settings import COL_DEV_BACKLOG

    q = ref.lower()
    if len(q) < 4:
        return None
    doc = _db()[COL_DEV_BACKLOG].find_one({"title": {"$regex": re.escape(q[:40]), "$options": "i"}})
    if doc:
        return mongo_store._serialize(doc)
    doc = _db()[COL_DEV_BACKLOG].find_one({"title": {"$regex": q.split()[0], "$options": "i"}})
    return mongo_store._serialize(doc) if doc else None


def _default_assignee(item: dict[str, Any]) -> str:
    project = (item.get("project") or "").lower()
    source = (item.get("source_agent") or "").lower()
    if source in ("codex",):
        return "codex"
    if project in ("xprize", "hackathon"):
        return "antigravity"
    return "cursor"


def dispatch_backlog_item(
    item: dict[str, Any],
    *,
    sender: str,
    assignee: str | None = None,
    auto_local: bool = True,
) -> dict[str, Any]:
    """Marca in_progress, crea ops_task y opcionalmente dispara agente local."""
    from raphiia_openai import coordination_live

    item_id = item.get("item_id") or ""
    title = (item.get("title") or "Backlog item")[:160]
    body = (item.get("body") or title).strip()
    assignee_u = (assignee or _default_assignee(item)).lower()
    correlation = f"backlog-{item_id}"

    dev_backlog.update_dev_backlog_item(
        item_id,
        status="in_progress",
        note=f"Asignado vía WhatsApp por {sender[-4:]}",
    )

    task = coordination_live.create_ops_task(
        assignee=assignee_u,
        title=title,
        checklist=[body, f"Origen backlog: {item_id}", "Reportar PASS/PARTIAL/FAIL con evidencia"],
        evidence_required=["status OK/PARTIAL/FAIL", "archivos tocados o bloqueo único"],
        priority="high" if "p0" in (item.get("tags") or []) else "normal",
        from_agent="RAFAEL",
        correlation_id=correlation,
        conversation_ref=f"whatsapp:{sender[-6:]}",
        related_project=item.get("project"),
    )

    local_result = None
    if auto_local:
        local_result = _try_local_dispatch(item, body)

    record_agent_run(
        AGENT_ID,
        action="dispatch_backlog_item",
        summary=f"{item_id} → {assignee_u} task={task.get('task_id')}",
        project=item.get("project") or "coordination",
        metadata={"item_id": item_id, "task_id": task.get("task_id"), "local": local_result},
    )

    lines = [
        f"✅ *Asignado:* {title[:80]}",
        f"• Backlog → *in_progress*",
        f"• Ops task → `{task.get('task_id')}` → *{assignee_u}*",
    ]
    if local_result and local_result.get("ok"):
        lines.append(f"• Local → {local_result.get('agent_id', 'AG-49')} ejecutado")
    elif local_result and local_result.get("skipped"):
        lines.append("• Local → no aplica (desarrollo vía ops_task)")
    lines.append("\nTe aviso cuando haya evidencia en coordinación.")

    return {
        "ok": True,
        "item_id": item_id,
        "task_id": task.get("task_id"),
        "assignee": assignee_u,
        "local": local_result,
        "text": "\n".join(lines),
    }


def _try_local_dispatch(item: dict[str, Any], body: str) -> dict[str, Any]:
    """Solo tareas operativas inmediatas; desarrollo queda en ops_task."""
    text = f"{item.get('title', '')} {body}".lower()
    from raphiia_openai.agents import ag49_local_dispatcher as ag49

    if any(k in text for k in ("guardian", "servicio", "health", "self heal", "reparar servicio")):
        return {**ag49.dispatch_local_agent("guardian", dry_run=False), "skipped": False}
    if any(k in text for k in ("cotizar", "cotizacion", "quote", "femar")):
        ref = "FEMAR" if "femar" in text else (body[:40] or "cliente")
        return {**ag49.dispatch_local_agent("quote", client_ref=ref, message=body, dry_run=True), "skipped": False}
    if any(k in text for k in ("informe", "reporte tecnico", "report")):
        return {**ag49.dispatch_local_agent("report", client_ref=body[:40], message=body, dry_run=True), "skipped": False}
    if any(k in text for k in ("hackathon", "funding", "grant")):
        return {**ag49.dispatch_local_agent("funding", message=body, dry_run=False), "skipped": False}
    return {"ok": True, "skipped": True, "reason": "development_via_ops_task"}


def parse_backlog_command(message: str) -> tuple[str | None, str]:
    text = (message or "").strip()
    patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"^(?:pendientes|proyectos|backlog|ideas|olvidados?)\b", re.I), "list"),
        (re.compile(r"^(?:resumen|brief)\s+(?:backlog|pendientes)\b", re.I), "summary"),
        (re.compile(r"^(?:desarrolla|haz|asigna|ejecuta|si\s+haz|sí\s+haz)\s+(?:el\s+|la\s+|#)?(\d+)\b", re.I), "dispatch_num"),
        (re.compile(r"^(?:desarrolla|haz|asigna|ejecuta|si\s+haz|sí\s+haz)\s+(.+)$", re.I | re.S), "dispatch_text"),
        (re.compile(r"^local:\s*(\w+)(?:\s+(.+))?$", re.I | re.S), "local"),
    ]
    for pat, cmd in patterns:
        m = pat.search(text)
        if m:
            arg = m.group(1).strip() if m.lastindex else ""
            if cmd == "local" and m.lastindex and m.lastindex >= 2:
                arg = f"{m.group(1).strip()} {(m.group(2) or '').strip()}".strip()
            return cmd, arg
    return None, ""


def handle_backlog_command(message: str, sender: str) -> dict[str, Any] | None:
    cmd, arg = parse_backlog_command(message)
    if not cmd:
        return None

    if cmd == "list":
        items = _fetch_open_items(limit=20)
        _save_session(sender, items)
        text = format_backlog_whatsapp_text(greeting=False, limit=20)
        return {"ok": True, "command": "backlog_list", "text": text, "count": len(items)}

    if cmd == "summary":
        summary = dev_backlog.get_dev_backlog_summary()
        by = summary.get("by_status") or {}
        text = (
            "*Backlog resumen*\n"
            f"Total: {summary.get('total', 0)}\n"
            f"Planificados: {by.get('planned', 0)} | En curso: {by.get('in_progress', 0)}\n"
            f"Conversados: {by.get('discussed', 0)} | Olvidados/stale: {summary.get('stale_open_count', 0)}\n"
            f"Hechos recientes: {len(summary.get('recent_done') or [])}"
        )
        return {"ok": True, "command": "backlog_summary", "text": text, "summary": summary}

    if cmd == "dispatch_num":
        item = _resolve_item(sender, arg)
        if not item:
            return {"ok": False, "command": "backlog_dispatch", "text": f"No encontré el item #{arg}. Escribe *pendientes* primero."}
        return dispatch_backlog_item(item, sender=sender)

    if cmd == "dispatch_text":
        item = _resolve_item(sender, arg)
        if not item:
            # crear discussed → planned on the fly
            cap = dev_backlog.capture_backlog_item(
                title=arg[:120],
                body=arg,
                status="planned",
                kind="task",
                source_agent="RAFAEL",
                tags=["whatsapp-adhoc"],
            )
            item = cap.get("item") or {}
        if not item:
            return {"ok": False, "command": "backlog_dispatch", "text": "No pude registrar esa idea."}
        return dispatch_backlog_item(item, sender=sender)

    if cmd == "local":
        from raphiia_openai.agents import ag49_local_dispatcher as ag49

        parts = arg.split(None, 1)
        kind = parts[0].lower()
        msg = parts[1] if len(parts) > 1 else ""
        result = ag49.dispatch_local_agent(kind, message=msg, client_ref=msg[:40], dry_run=False)
        text = f"Local *{kind}*: {'OK' if result.get('ok') else 'FAIL'}"
        if result.get("error"):
            text += f"\n{result['error']}"
        return {"ok": result.get("ok", False), "command": "local_dispatch", "text": text, "result": result}

    return None


def send_daily_backlog_whatsapp(*, target_number: str | None = None, node: str = "primary") -> dict[str, Any]:
    number = (target_number or NOTIFY_WHATSAPP_TO).strip()
    text = format_backlog_whatsapp_text(greeting=True)
    items = _fetch_open_items(limit=15)
    _save_session(number, items)
    sent = send_whatsapp(text, number=number, node=node)
    record_agent_run(
        AGENT_ID,
        action="daily_backlog_whatsapp",
        summary=f"sent={sent.get('ok')} items={len(items)}",
        project="coordination",
        metadata={"target": number[-4:]},
    )
    mongo_store.log_coordination(
        agent=AGENT_ID,
        summary=f"Recordatorio backlog WhatsApp ({len(items)} items abiertos)",
        event="backlog_daily_reminder",
        project="coordination",
        tool_used="send_daily_backlog_whatsapp",
    )
    return {"ok": bool(sent.get("ok", sent)), "text_chars": len(text), "items": len(items), "send": sent}


def run_backlog_steward(message: str = "", *, sender: str | None = None) -> dict[str, Any]:
    if message.strip() and sender:
        handled = handle_backlog_command(message, sender)
        if handled:
            return handled
    summary = dev_backlog.get_dev_backlog_summary()
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "summary": summary,
        "preview": format_backlog_whatsapp_text(greeting=False)[:1500],
    }
