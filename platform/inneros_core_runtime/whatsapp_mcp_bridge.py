"""Puentes MCP para MOD-COMMUNICATIONS (WhatsApp + contactos)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.notifications.evolution_client import dual_whatsapp_status, send_whatsapp, send_whatsapp_document as _send_doc, send_whatsapp_status as _send_status
from raphiia_openai.operational.constants import COL_OPS_CONTACTS, COL_OPS_WHATSAPP_GROUPS
from raphiia_openai import whatsapp_automation, whatsapp_contacts


def get_whatsapp_status(dual: bool = True) -> dict[str, Any]:
    if dual:
        status = dual_whatsapp_status()
        return {"ok": True, "dual": True, "nodes": status}
    primary = dual_whatsapp_status().get("primary", {})
    return {"ok": True, "dual": False, **primary}


def send_whatsapp_message(
    message: str,
    number: str | None = None,
    contact_ref: str | None = None,
    node: str = "primary",
) -> dict[str, Any]:
    target = (number or "").strip()
    if contact_ref and not target:
        resolved = whatsapp_contacts.resolve_contact(contact_ref, limit=1)
        match = resolved.get("matches") or []
        if match:
            target = (match[0].get("whatsapp") or match[0].get("phone") or "").strip()
    if not target:
        return {"ok": False, "error": "number or contact_ref required"}
    result = send_whatsapp(message, number=target, node=node)
    return {"ok": bool(result.get("ok")), "result": result, "number": target}


def send_whatsapp_draft(draft: str, number: str | None = None, contact_ref: str | None = None, node: str = "primary") -> dict[str, Any]:
    return send_whatsapp_message(draft, number=number, contact_ref=contact_ref, node=node)


def send_whatsapp_status(
    content: str = "",
    status_type: str = "text",
    caption: str = "",
    file_path: str | None = None,
    all_contacts: bool = False,
    status_jid_list: list[str] | None = None,
    background_color: str = "#008000",
    font: int = 1,
    node: str = "primary",
) -> dict[str, Any]:
    result = _send_status(
        content,
        status_type=status_type,
        caption=caption,
        file_path=file_path,
        all_contacts=all_contacts,
        status_jid_list=status_jid_list,
        background_color=background_color,
        font=font,
        node=node,
    )
    return {"ok": bool(result.get("ok")), "result": result}


def send_whatsapp_document(
    file_path: str,
    number: str | None = None,
    contact_ref: str | None = None,
    caption: str = "",
    node: str = "primary",
) -> dict[str, Any]:
    target = (number or "").strip()
    if contact_ref and not target:
        resolved = whatsapp_contacts.resolve_contact(contact_ref, limit=1)
        match = resolved.get("matches") or []
        if match:
            target = (match[0].get("whatsapp") or match[0].get("phone") or "").strip()
    if not target:
        return {"ok": False, "error": "number or contact_ref required"}
    result = _send_doc(file_path, number=target, caption=caption, node=node)
    return {"ok": bool(result.get("ok")), "result": result, "number": target}


def save_whatsapp_group(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.save_whatsapp_group(payload)


def list_whatsapp_groups(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.list_whatsapp_groups(query=query, entity_id=entity_id, limit=limit)


def resolve_whatsapp_group(identifier: str, limit: int = 10) -> dict[str, Any]:
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.resolve_whatsapp_group(identifier, limit=limit)


def broadcast_whatsapp_groups(
    message: str,
    group_ids: list[str] | None = None,
    labels: list[str] | None = None,
    entity_ids: list[str] | None = None,
    limit: int = 200,
    dry_run: bool = True,
    approved_by: str | None = None,
) -> dict[str, Any]:
    from raphiia_openai import whatsapp_contacts

    return whatsapp_contacts.broadcast_whatsapp_groups(
        message,
        group_ids=group_ids,
        labels=labels,
        entity_ids=entity_ids,
        limit=limit,
        dry_run=dry_run,
        approved_by=approved_by,
    )


def list_ops_contacts(query: str | None = None, entity_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if entity_id:
        filt["entity_ids"] = entity_id
    if query:
        import re
        q = re.escape(query.strip())
        filt["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"whatsapp": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
        ]
    items = list(db[COL_OPS_CONTACTS].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(items), "contacts": items}


def save_ops_contact(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = datetime.now(timezone.utc).isoformat()
    name = str(payload.get("name") or "").strip()
    phone = str(payload.get("phone") or payload.get("whatsapp") or "").strip()
    whatsapp = str(payload.get("whatsapp") or phone).strip()
    digits = "".join(c for c in whatsapp if c.isdigit())
    if not name or not digits:
        return {"ok": False, "error": "name and phone/whatsapp required"}
    contact_id = str(payload.get("contact_id") or f"contact_{digits[-12:]}")
    entity_ids = payload.get("entity_ids") or ([payload["entity_id"]] if payload.get("entity_id") else ["ent_pcdoctor"])
    doc = {
        "contact_id": contact_id,
        "name": name,
        "phone": phone,
        "phone_digits": digits,
        "whatsapp": whatsapp,
        "whatsapp_digits": digits,
        "company": str(payload.get("company") or "").strip(),
        "tags": payload.get("tags") or [],
        "entity_ids": entity_ids,
        "entity_id": entity_ids[0] if entity_ids else None,
        "notes": str(payload.get("notes") or "").strip(),
        "source": str(payload.get("source") or "mcp"),
        "updated_at": now,
    }
    db[COL_OPS_CONTACTS].update_one(
        {"contact_id": contact_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    db["contacts"].update_one(
        {"contact_id": contact_id},
        {"$set": {**doc, "organization_name": doc["company"]}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, "contact_id": contact_id, "contact": doc}


def process_whatsapp_inbound_event(payload: dict[str, Any]) -> dict[str, Any]:
    return whatsapp_automation.ingest_inbound_event(payload)


def create_whatsapp_reminder(body: str, due_at: str | None = None, target_number: str | None = None, entity_id: str | None = None) -> dict[str, Any]:
    return whatsapp_automation.create_reminder(body=body, due_at=due_at, target_number=target_number, entity_id=entity_id)


def list_whatsapp_reminders(limit: int = 20) -> dict[str, Any]:
    return whatsapp_automation.list_reminders(limit=limit)


def run_due_whatsapp_reminders() -> dict[str, Any]:
    return whatsapp_automation.run_due_reminders()
