"""Normalize important agent messages into durable, linked ops tasks."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai import agent_identity, coordination_live, mongo_store, ralfia_time
from raphiia_openai.settings import COL_AGENT_MESSAGES


_TASK_TITLE = re.compile(r"^\s*\[(?:OPS|P[0-3]|E2E\s+P[0-3])(?:\s+[^]]*)?\]", re.IGNORECASE)
_TASK_BODY = re.compile(r"\b(?:INSTRUCCI[ÓO]N|TAREA|ORDEN)\s+P[0-3]\b", re.IGNORECASE)
_FIELD = re.compile(r"^\s*(correlation_id|project|conversation_ref)\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _body_fields(body: str) -> dict[str, str]:
    return {match.group(1).lower(): match.group(2).strip() for match in _FIELD.finditer(body or "")}


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _checklist_from_body(body: str) -> list[str]:
    items: list[str] = []
    for line in (body or "").splitlines():
        match = re.match(r"^\s*-\s*(?:\[[ xX]\]\s*)?(.+?)\s*$", line)
        if match:
            item = match.group(1).strip()
            if item and not re.match(r"^(correlation_id|project|conversation_ref)\s*:", item, re.IGNORECASE):
                items.append(item)
    if items:
        return items
    meaningful = [
        line.strip()
        for line in (body or "").splitlines()
        if line.strip() and not _FIELD.match(line)
    ]
    return [" ".join(meaningful)[:2000]] if meaningful else []


def should_create_task(*, title: str, body: str, message_type: str, payload: dict[str, Any] | None) -> bool:
    payload = payload or {}
    return bool(
        str(message_type or "").strip().lower() == "task"
        or payload.get("auto_create_ops_task") is True
        or _TASK_TITLE.search(title or "")
        or _TASK_BODY.search(body or "")
    )


def ingest_agent_message(
    *,
    from_agent: str,
    target_agent: str,
    title: str,
    body: str,
    priority: str = "normal",
    correlation_id: str | None = None,
    message_type: str = "message",
    payload: dict[str, Any] | None = None,
    reply_to: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Persist a message and, when explicitly task-like, create a linked ops task."""
    from raphiia_openai.memory import agent_messages

    payload_n = payload or {}
    from_identity = agent_identity.identity_from_payload(from_agent, payload_n)
    target_identity = agent_identity.identity_from_payload(target_agent, payload_n)
    fields = _body_fields(body)
    correlation = (correlation_id or fields.get("correlation_id") or "").strip() or None
    project = str(payload_n.get("project") or fields.get("project") or "").strip() or None
    conversation_ref = str(payload_n.get("conversation_ref") or fields.get("conversation_ref") or "").strip() or None
    message = agent_messages.create_agent_message(
        from_agent=from_identity["mailbox"],
        target_agent=target_identity["mailbox"],
        title=title,
        body=body,
        priority=priority,
        correlation_id=correlation,
        message_type=message_type,
        payload=payload_n,
        reply_to=reply_to,
        idempotency_key=idempotency_key,
        related_project=project,
    )
    if not message.get("ok") or not should_create_task(
        title=title,
        body=body,
        message_type=message_type,
        payload=payload_n,
    ):
        return message

    message_id = str(message.get("message_id") or "")
    correlation = str(message.get("correlation_id") or correlation or message_id)
    task = coordination_live.create_ops_task(
        assignee=target_identity["mailbox"],
        title=re.sub(r"^\s*\[[^]]+\]\s*", "", title).strip() or title.strip(),
        checklist=_list_value(payload_n.get("checklist")) or _checklist_from_body(body),
        evidence_required=_list_value(payload_n.get("evidence_required")),
        priority=priority,
        from_agent=from_identity["actor_id"],
        correlation_id=correlation,
        source_message_id=message_id,
        conversation_ref=conversation_ref,
        related_project=project,
    )
    if task.get("ok"):
        now = ralfia_time.now_utc_iso()
        task_id = task.get("task_id")
        mongo_store.get_db()[COL_AGENT_MESSAGES].update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "type": "task",
                    "task_id": task_id,
                    "correlation_id": correlation,
                    "related_project": project,
                    "conversation_ref": conversation_ref,
                    "from_identity": from_identity,
                    "target_identity": target_identity,
                    "normalized_at": now,
                    "updated_at": now,
                },
                "$addToSet": {"tags": {"$each": ["ops_task", str(task_id), correlation]}},
            },
        )
        task["source_message_id"] = message_id
    return {**message, "normalization": task}
