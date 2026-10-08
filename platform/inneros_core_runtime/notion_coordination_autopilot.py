"""Autopilot Notion ↔ RACB: leer inbox, responder estado, ACK explícito."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.memory import agent_messages as am
from raphiia_openai.settings import COL_AGENT_MESSAGES

_STATUS_RE = re.compile(r"\b(checkpoint|estado|avances|qu[eé]\s+est[aá]s\s+haciendo|solicitud de estado)\b", re.I)
_EXECUTE_RE = re.compile(r"\b(EXECUTE|IMPLEMENTA|CURSOR IMPLEMENTA|encargo)\b", re.I)


def _open_messages(*, target: str = "cursor", limit: int = 30) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    return list(
        db[COL_AGENT_MESSAGES]
        .find({"target_agent": target, "status": "open"}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )


def _build_status_report(*, correlation_id: str | None = None) -> str:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if correlation_id:
        filt["correlation_id"] = correlation_id
    tasks = list(db["ralfia_ops_tasks"].find(filt, {"_id": 0, "task_id": 1, "status": 1, "title": 1}).sort("updated_at", -1).limit(8))
    lines = [
        "CHECKPOINT · Golden flow ops (4 carriles + WhatsApp SI/NO)",
        f"Correlación consulta: {correlation_id or '(todas)'}",
        "GitHub main: PR #128 mergeado + chore gitignore + WhatsApp SI ops_xxx (ecf577da+)",
        "Runtime: ralfiia-amd ↔ ralfiia-intel espejo (MCP + Temporal + Notion timer)",
        "Agentes IDE: Cursor, Codex, Antigravity, Gemini (MCP claim/complete simétrico)",
        "Owner WhatsApp: SI ops_xxx / NO ops_xxx (autoriza+claim; canary verification auto-cierra)",
        "Script canary: platform/scripts/ops_quad_lane_canary.py",
        "Golden correlación activa: golden-flow-quad-20261008",
        "",
        "Pendiente opinión Notion: ¿falta E2E Antigravity real con LLM o basta canary read-only?",
        "",
        "Ops recientes:",
    ]
    for t in tasks:
        lines.append(f"• {t.get('task_id')} · {t.get('status')} · {(t.get('title') or '')[:60]}")
    return "\n".join(lines)


def process_notion_inbox_for_cursor(*, auto_ack: bool = True, correlation_id: str | None = None) -> dict[str, Any]:
    """Lee mensajes Notion→Cursor, responde checkpoint/encargo, ACK cuando corresponde."""
    processed: list[dict[str, Any]] = []
    corr = (correlation_id or "inneros-core-autonomy-model-pin-20261008").strip()
    for msg in _open_messages():
        mid = str(msg.get("message_id") or "")
        title = str(msg.get("title") or "")
        body = str(msg.get("body") or "")
        msg_corr = str(msg.get("correlation_id") or corr)
        if corr and msg_corr != corr and corr not in body:
            continue
        needs_status = bool(_STATUS_RE.search(title + " " + body))
        needs_execute_ack = bool(_EXECUTE_RE.search(title + " " + body))
        if not (needs_status or needs_execute_ack):
            continue
        report = _build_status_report(correlation_id=msg_corr)
        reply = am.create_agent_message(
            from_agent="cursor",
            target_agent="notion",
            title=f"Checkpoint · {msg_corr}"[:200],
            body=report,
            correlation_id=msg_corr,
            message_type="message",
            reply_to=mid,
            idempotency_key=f"notion-autopilot-reply-{mid}",
        )
        ack = None
        if auto_ack:
            ack = am.ack_agent_message(message_id=mid, agent="cursor")
        processed.append({"message_id": mid, "reply": reply.get("message_id"), "ack": ack})
    return {"ok": True, "processed_count": len(processed), "processed": processed}


def sync_notion_outbox_ack(*, agent: str = "notion", limit: int = 20) -> dict[str, Any]:
    """ACK mensajes propios en inbox Notion que ya fueron respondidos (checkpoint_only)."""
    acked = []
    for msg in _open_messages(target=agent, limit=limit):
        if not msg.get("reply_to"):
            continue
        payload = msg.get("payload") or {}
        if payload.get("checkpoint_only") and str(msg.get("from_agent") or "").lower() == "cursor":
            res = am.ack_agent_message(message_id=str(msg.get("message_id")), agent=agent)
            acked.append({"message_id": msg.get("message_id"), "ack": res})
    return {"ok": True, "acked_count": len(acked), "acked": acked}
