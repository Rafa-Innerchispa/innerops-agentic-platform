"""Puente RalfIA → Notion API con contrato doc_id y dedupe por sync_hash."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store, ralfia_time
from raphiia_openai.notion_contract import (
    NOTION_DOCS_DB_SCHEMA,
    NOTION_SAFE_READ_TOOLS,
    NOTION_SAFE_WRITE_TOOLS,
    build_doc_record,
    list_sync_candidates,
    load_coordination_doc,
    normalize_doc_id,
)
from raphiia_openai.settings import (
    NOTION_API_TOKEN,
    NOTION_AUDIT_DATABASE_ID,
    NOTION_DOCS_DATABASE_ID,
    NOTION_DOCS_PARENT_PAGE_ID,
    NOTION_MAX_DOC_CHARS,
    NOTION_VERSION,
)

NOTION_API_BASE = "https://api.notion.com/v1"
SYNC_COL = "ralfia_notion_sync"
AUDIT_COL = "ralfia_notion_audit"
_MAX_BLOCK_CHARS = 1800
_MAX_CONTENT_CHARS = max(1000, NOTION_MAX_DOC_CHARS)


def _headers() -> dict[str, str]:
    token = (NOTION_API_TOKEN or "").strip()
    if not token:
        raise ValueError("NOTION_API_TOKEN no configurado en .env")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _ok_or_error(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if resp.is_success:
        return {"ok": True, **data} if isinstance(data, dict) else {"ok": True, "data": data}
    message = data.get("message") if isinstance(data, dict) else resp.text
    return {"ok": False, "status": resp.status_code, "error": message, "details": data}


def _rich_text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": str(content)[:_MAX_BLOCK_CHARS]}}]


def _prop_title(title: str) -> dict[str, Any]:
    return {"title": _rich_text(title)}


def _prop_rich(text: str) -> dict[str, Any]:
    return {"rich_text": _rich_text(text)}


def _prop_select(name: str) -> dict[str, Any]:
    return {"select": {"name": name}}


def _prop_date(iso: str | None) -> dict[str, Any]:
    if not iso:
        return {"date": None}
    return {"date": {"start": iso[:10] if len(iso) >= 10 else iso}}


def get_notion_status() -> dict[str, Any]:
    token = (NOTION_API_TOKEN or "").strip()
    if not token:
        return {
            "ok": False,
            "configured": False,
            "message": "Falta NOTION_API_TOKEN en .env",
            "docs_database_id": NOTION_DOCS_DATABASE_ID or None,
            "parent_page_id": NOTION_DOCS_PARENT_PAGE_ID or None,
            "contract": "doc_id jerárquico (02.01.004) + Patrón 1",
        }
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(f"{NOTION_API_BASE}/users/me", headers=_headers())
        parsed = _ok_or_error(resp)
        if not parsed.get("ok"):
            return {
                "ok": False,
                "configured": True,
                "connected": False,
                "docs_database_id": NOTION_DOCS_DATABASE_ID or None,
                **parsed,
            }
        return {
            "ok": True,
            "configured": True,
            "connected": True,
            "bot_id": parsed.get("id"),
            "docs_database_id": NOTION_DOCS_DATABASE_ID or None,
            "audit_database_id": NOTION_AUDIT_DATABASE_ID or None,
            "parent_page_id": NOTION_DOCS_PARENT_PAGE_ID or None,
            "module": "MOD-NOTION",
            "contract_version": "1.0",
            "doc_id_format": "02.01.004 (jerárquico)",
            "content_pattern": "Patrón 1 — metadata en DB, cuerpo en página",
            "safe_profiles": {
                "read": NOTION_SAFE_READ_TOOLS,
                "write": NOTION_SAFE_WRITE_TOOLS,
            },
        }
    except Exception as exc:
        return {"ok": False, "configured": True, "connected": False, "error": str(exc)}


def get_notion_schema_blueprint() -> dict[str, Any]:
    return {
        "ok": True,
        "database": NOTION_DOCS_DB_SCHEMA,
        "required_env": [
            "NOTION_API_TOKEN",
            "NOTION_DOCS_PARENT_PAGE_ID",
            "NOTION_DOCS_DATABASE_ID (tras bootstrap_schema)",
        ],
        "frontmatter_example": (
            "---\n"
            "doc_id: 02.01.004\n"
            "status: Active\n"
            "domain: Ops\n"
            "audience: internal\n"
            "---\n"
        ),
    }


def bootstrap_notion_schema(*, dry_run: bool = True) -> dict[str, Any]:
    parent = (NOTION_DOCS_PARENT_PAGE_ID or "").strip()
    if not parent:
        return {"ok": False, "error": "NOTION_DOCS_PARENT_PAGE_ID requerido para crear la DB"}
    if NOTION_DOCS_DATABASE_ID:
        return {
            "ok": True,
            "reused": True,
            "database_id": NOTION_DOCS_DATABASE_ID,
            "message": "DB ya configurada en .env",
        }
    body = {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": NOTION_DOCS_DB_SCHEMA["title"]}}],
        "properties": {
            "Título": {"title": {}},
            **NOTION_DOCS_DB_SCHEMA["properties"],
        },
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "would_create": body, "parent_page_id": parent}
    with httpx.Client(timeout=45) as client:
        resp = client.post(f"{NOTION_API_BASE}/databases", headers=_headers(), json=body)
    parsed = _ok_or_error(resp)
    if not parsed.get("ok"):
        return parsed
    return {
        "ok": True,
        "dry_run": False,
        "database_id": parsed.get("id"),
        "url": parsed.get("url"),
        "hint": "Copia database_id a NOTION_DOCS_DATABASE_ID en .env y reconecta la integración a esa DB",
    }


def _db_id() -> str:
    dbid = (NOTION_DOCS_DATABASE_ID or "").strip()
    if not dbid:
        raise ValueError("NOTION_DOCS_DATABASE_ID no configurado — ejecuta bootstrap_notion_schema primero")
    return dbid


def _load_by_doc_id(doc_id: str) -> dict[str, Any] | None:
    db = mongo_store.get_db()
    return db[SYNC_COL].find_one({"doc_id": normalize_doc_id(doc_id)}, {"_id": 0})


def _save_sync_record(record: dict[str, Any]) -> None:
    db = mongo_store.get_db()
    doc_id = normalize_doc_id(record.get("doc_id") or "")
    record = {**record, "doc_id": doc_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    db[SYNC_COL].update_one({"doc_id": doc_id}, {"$set": record}, upsert=True)


def _query_notion_by_doc_id(client: httpx.Client, doc_id: str) -> dict[str, Any] | None:
    body = {
        "filter": {
            "property": "doc_id",
            "rich_text": {"equals": doc_id},
        },
        "page_size": 1,
    }
    resp = client.post(f"{NOTION_API_BASE}/databases/{_db_id()}/query", headers=_headers(), json=body)
    parsed = _ok_or_error(resp)
    if not parsed.get("ok"):
        return None
    results = parsed.get("results") or []
    return results[0] if results else None


def notion_upsert_doc_metadata(
    doc_id: str,
    fields: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    did = normalize_doc_id(doc_id)
    if not did:
        return {"ok": False, "error": "doc_id_required"}
    fields = fields or {}
    props = {
        "Título": _prop_title(str(fields.get("title") or did)),
        "doc_id": _prop_rich(did),
    }
    for key, notion_key in (
        ("status", "Estado"),
        ("domain", "Dominio"),
        ("audience", "audience"),
    ):
        if fields.get(key):
            props[notion_key] = _prop_select(str(fields[key]))
    if fields.get("source_path"):
        props["source_path"] = _prop_rich(str(fields["source_path"]))
    if fields.get("sync_hash"):
        props["sync_hash"] = _prop_rich(str(fields["sync_hash"]))
    if fields.get("source_last_modified"):
        props["source_last_modified"] = _prop_date(str(fields["source_last_modified"]))
    props["last_sync_at"] = _prop_date(datetime.now(timezone.utc).isoformat())

    if dry_run:
        return {"ok": True, "dry_run": True, "doc_id": did, "would_update_properties": props}

    with httpx.Client(timeout=30) as client:
        page = _query_notion_by_doc_id(client, did)
        if page:
            resp = client.patch(
                f"{NOTION_API_BASE}/pages/{page['id']}",
                headers=_headers(),
                json={"properties": props},
            )
            parsed = _ok_or_error(resp)
            if not parsed.get("ok"):
                return parsed
            out = {"ok": True, "doc_id": did, "notion_page_id": page["id"], "url": parsed.get("url"), "updated": True}
        else:
            create = {
                "parent": {"database_id": _db_id()},
                "properties": props,
            }
            resp = client.post(f"{NOTION_API_BASE}/pages", headers=_headers(), json=create)
            parsed = _ok_or_error(resp)
            if not parsed.get("ok"):
                return parsed
            out = {
                "ok": True,
                "doc_id": did,
                "notion_page_id": parsed.get("id"),
                "url": parsed.get("url"),
                "created": True,
            }
    _save_sync_record({**out, **fields, "doc_id": did})
    return out


def _markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rich_text(line[4:].strip())}})
        elif line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text(line[3:].strip())}})
        elif line.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": _rich_text(line[2:].strip())}})
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _rich_text(line[2:].strip())},
                }
            )
        else:
            start = 0
            while start < len(line):
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": _rich_text(line[start : start + _MAX_BLOCK_CHARS])},
                    }
                )
                start += _MAX_BLOCK_CHARS
    return blocks[:100]


def _replace_page_body(client: httpx.Client, page_id: str, content_md: str) -> dict[str, Any]:
    listed = client.get(f"{NOTION_API_BASE}/blocks/{page_id}/children?page_size=100", headers=_headers())
    children = _ok_or_error(listed)
    if children.get("ok"):
        for block in children.get("results") or []:
            bid = block.get("id")
            if bid:
                client.patch(f"{NOTION_API_BASE}/blocks/{bid}", headers=_headers(), json={"archived": True})
    blocks = _markdown_to_blocks(content_md)[:99]
    meta = {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": _rich_text(f"RalfIA sync · {ralfia_time.format_log()} · hash pending"),
        },
    }
    append = client.patch(
        f"{NOTION_API_BASE}/blocks/{page_id}/children",
        headers=_headers(),
        json={"children": [meta, *blocks]},
    )
    return _ok_or_error(append)


def notion_push_doc(
    doc_id: str,
    title: str,
    content_md: str,
    source_path: str,
    *,
    status: str = "Active",
    domain: str = "Ops",
    source_last_modified: str | None = None,
    sync_hash: str | None = None,
    audience: str = "internal",
    dry_run: bool = False,
) -> dict[str, Any]:
    did = normalize_doc_id(doc_id)
    if not did:
        return {"ok": False, "error": "doc_id_required"}
    body = (content_md or "")[:_MAX_CONTENT_CHARS]
    content_hash = sync_hash or hashlib.sha256(body.encode("utf-8")).hexdigest()
    prior = _load_by_doc_id(did)
    action = "skip"
    if not prior:
        action = "create"
    elif prior.get("sync_hash") != content_hash:
        action = "update"
    else:
        return {
            "ok": True,
            "dry_run": dry_run,
            "action": "skip",
            "doc_id": did,
            "message": "sync_hash sin cambios",
            "notion_page_id": prior.get("notion_page_id"),
            "url": prior.get("url"),
        }

    plan = {
        "ok": True,
        "dry_run": dry_run,
        "action": action,
        "doc_id": did,
        "title": title,
        "source_path": source_path,
        "sync_hash": content_hash,
        "status": status,
        "domain": domain,
        "audience": audience,
    }
    if dry_run:
        return plan

    meta = notion_upsert_doc_metadata(
        did,
        {
            "title": title,
            "status": status,
            "domain": domain,
            "audience": audience,
            "source_path": source_path,
            "sync_hash": content_hash,
            "source_last_modified": source_last_modified,
        },
        dry_run=False,
    )
    if not meta.get("ok"):
        return meta
    page_id = meta.get("notion_page_id")
    with httpx.Client(timeout=60) as client:
        body_result = _replace_page_body(client, page_id, body)
    if not body_result.get("ok"):
        return body_result
    out = {
        **plan,
        "dry_run": False,
        "notion_page_id": page_id,
        "url": meta.get("url"),
        "content_blocks": len(_markdown_to_blocks(body)),
    }
    _save_sync_record(out)
    notion_append_audit_event(did, "push_doc", {"action": action, "sync_hash": content_hash}, dry_run=False)
    return out


def notion_push_from_path(relative_path: str, *, dry_run: bool = False) -> dict[str, Any]:
    loaded = load_coordination_doc(relative_path)
    if not loaded.get("ok"):
        return loaded
    return notion_push_doc(
        loaded["doc_id"],
        loaded["title"],
        loaded["content_md"],
        loaded["source_path"],
        status=loaded["status"],
        domain=loaded["domain"],
        source_last_modified=loaded.get("source_last_modified"),
        sync_hash=loaded["sync_hash"],
        audience=loaded.get("audience") or "internal",
        dry_run=dry_run,
    )


def push_coordination_doc_to_notion(relative_path: str, *, parent_page_id: str | None = None, max_chars: int = 12000) -> dict[str, Any]:
    """Compat — delega al contrato doc_id."""
    _ = parent_page_id, max_chars
    return notion_push_from_path(relative_path, dry_run=False)


def preview_notion_sync(limit: int = 50) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for rel in list_sync_candidates(limit=limit):
        loaded = load_coordination_doc(rel)
        if not loaded.get("ok"):
            continue
        prior = _load_by_doc_id(loaded["doc_id"])
        action = "create"
        if prior and prior.get("sync_hash") == loaded["sync_hash"]:
            action = "skip"
        elif prior:
            action = "update"
        items.append(
            {
                "doc_id": loaded["doc_id"],
                "title": loaded["title"],
                "source_path": loaded["source_path"],
                "action": action,
                "canonical_id": loaded.get("canonical_id"),
                "domain": loaded["domain"],
                "status": loaded["status"],
            }
        )
    return {"ok": True, "count": len(items), "items": items, "dry_run": True}


def sync_documentation_to_notion(*, mode: str = "dry_run", limit: int = 50) -> dict[str, Any]:
    apply = mode.strip().lower() in {"apply", "write", "push"}
    results: list[dict[str, Any]] = []
    for rel in list_sync_candidates(limit=limit):
        if apply:
            results.append(notion_push_from_path(rel, dry_run=False))
        else:
            loaded = load_coordination_doc(rel)
            if not loaded.get("ok"):
                continue
            prior = _load_by_doc_id(loaded["doc_id"])
            action = "create"
            if prior and prior.get("sync_hash") == loaded["sync_hash"]:
                action = "skip"
            elif prior:
                action = "update"
            results.append(
                {
                    "ok": True,
                    "dry_run": True,
                    "doc_id": loaded["doc_id"],
                    "relative_path": rel,
                    "action": action,
                }
            )
    return {
        "ok": True,
        "mode": "apply" if apply else "dry_run",
        "count": len(results),
        "results": results,
    }


def notion_append_audit_event(
    doc_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    did = normalize_doc_id(doc_id)
    event = {
        "doc_id": did,
        "event_type": (event_type or "event").strip(),
        "payload": payload or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "would_append": event}
    db = mongo_store.get_db()
    db[AUDIT_COL].insert_one(event)
    mongo_store.log_sync("notion_audit_event", doc_id=did, event_type=event["event_type"])
    return {"ok": True, "doc_id": did, "event_type": event["event_type"]}


def search_notion_pages(query: str, limit: int = 10) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query_required"}
    body = {
        "query": q,
        "page_size": max(1, min(limit, 25)),
        "filter": {"value": "page", "property": "object"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{NOTION_API_BASE}/search", headers=_headers(), json=body)
    parsed = _ok_or_error(resp)
    if not parsed.get("ok"):
        return parsed
    pages = []
    for item in parsed.get("results") or []:
        props = item.get("properties") or {}
        doc_id_val = ""
        if isinstance(props.get("doc_id"), dict):
            rt = props["doc_id"].get("rich_text") or []
            doc_id_val = "".join(p.get("plain_text", "") for p in rt)
        pages.append(
            {
                "id": item.get("id"),
                "doc_id": doc_id_val or None,
                "title": _page_title(item),
                "url": item.get("url"),
                "last_edited_time": item.get("last_edited_time"),
            }
        )
    return {"ok": True, "count": len(pages), "pages": pages}


def _page_title(page: dict[str, Any]) -> str:
    props = page.get("properties") or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            parts = prop.get("title") or []
            return "".join(part.get("plain_text", "") for part in parts if isinstance(part, dict))
    return page.get("id") or "untitled"


def add_notion_page_comment(page_id: str, comment: str) -> dict[str, Any]:
    pid = (page_id or "").strip()
    text = (comment or "").strip()
    if not pid or not text:
        return {"ok": False, "error": "page_id_and_comment_required"}
    body = {"parent": {"page_id": pid}, "rich_text": _rich_text(text)}
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{NOTION_API_BASE}/comments", headers=_headers(), json=body)
    parsed = _ok_or_error(resp)
    if parsed.get("ok"):
        return {"ok": True, "comment_id": parsed.get("id"), "page_id": pid}
    return parsed


def get_notion_sync_log(limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    items = list(db[SYNC_COL].find({}, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(items), "items": items}
