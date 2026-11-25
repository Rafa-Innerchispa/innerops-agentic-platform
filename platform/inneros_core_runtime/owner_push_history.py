"""Bandeja e historial de pushes owner (app InnerOS)."""

from __future__ import annotations

import time
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "ralfia_owner_push_inbox"


def _col():
    db = mongo_store.get_db()
    col = db[COLLECTION]
    col.create_index([("created_at", -1)])
    col.create_index("task_id")
    return col


def _now() -> float:
    return time.time()


def record_auth_push(
    *,
    task_id: str,
    human_task_id: str,
    provider: str,
    title: str,
    message: str,
    nonce: str,
    ntfy_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = {
        "kind": "auth_request",
        "task_id": task_id,
        "human_task_id": human_task_id,
        "provider": provider,
        "title": title[:240],
        "message": message[:2000],
        "nonce": nonce,
        "ntfy_id": ntfy_id,
        "status": "pending",
        "created_at": _now(),
        "extra": extra or {},
    }
    _col().insert_one(doc)
    return {"ok": True, "id": str(doc.get("_id"))}


def record_decision(
    *,
    task_id: str,
    decision: str,
    channel: str = "inneros_push",
    ok: bool,
) -> dict[str, Any]:
    _col().update_many(
        {"task_id": task_id, "kind": "auth_request", "status": "pending"},
        {"$set": {"status": "approved" if decision == "approve" else "cancelled", "resolved_at": _now()}},
    )
    doc = {
        "kind": "decision",
        "task_id": task_id,
        "decision": decision,
        "channel": channel,
        "ok": ok,
        "created_at": _now(),
    }
    _col().insert_one(doc)
    return {"ok": True}


def list_inbox(*, limit: int = 40, kinds: list[str] | None = None) -> list[dict[str, Any]]:
    q: dict[str, Any] = {}
    if kinds:
        q["kind"] = {"$in": kinds}
    rows = (
        _col()
        .find(q, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(int(limit), 100)))
    )
    return list(rows)


def fetch_ntfy_topic_cache(*, since: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """Mensajes aún en caché del servidor ntfy (complementa Mongo)."""
    import os

    import httpx

    base = (os.getenv("INNEROS_NTFY_URL") or "http://127.0.0.1:2586").rstrip("/")
    topic = (os.getenv("INNEROS_NTFY_TOPIC") or "ralfia-owner-ops").strip().lstrip("/")
    params: dict[str, str] = {"poll": "1"}
    if since:
        params["since"] = since
    try:
        r = httpx.get(f"{base}/{topic}/json", params=params, timeout=12.0)
        if r.status_code != 200:
            return []
        items: list[dict[str, Any]] = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import json

                items.append(json.loads(line))
            except Exception:
                continue
        return items[-limit:]
    except Exception:
        return []