"""Registro único de decisiones del propietario para autorizaciones OPS.

Telegram y Alexa (Atlas Control) comparten este registro: la misma solicitud
se anuncia en ambos canales con un único alcance, vencimiento e identidad
autorizadora. La primera decisión válida gana de forma atómica mediante
compare-and-set; la segunda se rechaza en el servidor.

Atlas Control conserva la validación de Voice ID + PIN nativo de Amazon y el
anuncio sin micrófono abierto. Este módulo solo registra y consume decisiones.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

COLLECTION = "atlas_ops_owner_decisions"
DEFAULT_TTL_SEC = 900

TERMINAL_DECISIONS = frozenset({"approved", "cancelled", "expired"})

_AWAITING_AUTH = frozenset(
    {
        "awaiting_owner_auth",
        "awaiting_owner_authorization",
        "awaiting_owner_approval",
        "awaiting_authorization",
        "awaiting_codex_claim",
        "awaiting_cursor_claim",
        "awaiting_antigravity_claim",
        "awaiting_gemini_claim",
        "awaiting_chatgpt_claim",
        "awaiting_ide_claim",
        "queued",
    }
)


def _task_still_needs_owner_auth(task: dict[str, Any]) -> bool:
    if task.get("owner_authorized_at") or task.get("owner_approved"):
        return False
    return str(task.get("status") or "").lower() in _AWAITING_AUTH


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _expires_at_epoch(ttl_sec: int | None = None) -> float:
    sec = max(60, int(ttl_sec if ttl_sec is not None else DEFAULT_TTL_SEC))
    return _now_epoch() + sec


def _is_future_epoch(value: Any) -> bool:
    try:
        return float(value) > _now_epoch()
    except (ValueError, TypeError):
        return False


def _scope_hash(task: dict[str, Any]) -> str:
    """Mismo algoritmo que el broker de Atlas para que los hashes coincidan."""
    import json

    fields = (
        "task_id", "assignee", "preferred_provider", "preferred_model",
        "objective", "title", "repo", "base_ref", "work_branch",
        "task_class", "execution_lane", "execution_policy", "payload",
    )
    return hashlib.sha256(
        json.dumps({k: task.get(k) for k in fields}, sort_keys=True, default=str).encode()
    ).hexdigest()


def _collection():
    db = mongo_store.get_db()
    col = db[COLLECTION]
    col.create_index("task_id", unique=True)
    col.create_index([("status", 1), ("expires_at", 1)])
    return col


def _atlas_doc(task: dict[str, Any], *, scope: str, nonce: str, now: float, expires: float) -> dict[str, Any]:
    """Formato compatible con el broker de Atlas: _id = task_id, status pending, tiempos epoch."""
    tid = str(task.get("task_id") or "").strip()
    return {
        "_id": tid,
        "task_id": tid,
        "human_task_id": str(task.get("human_task_id") or task.get("task_alias") or tid),
        "provider": str(task.get("assignee") or task.get("preferred_provider") or "?"),
        "revision": int(task.get("revision") or 0),
        "correlation_id": str(task.get("correlation_id") or ""),
        "scope_hash": scope,
        "nonce": nonce,
        "status": "pending",
        "created_at": now,
        "expires_at": expires,
        "updated_at": now,
    }


def publish_decision_request(
    task: dict[str, Any],
    *,
    ttl_sec: int | None = None,
) -> dict[str, Any]:
    """Publica o reutiliza la solicitud única de decisión para una tarea."""
    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?")
    revision = int(task.get("revision") or 0)
    scope = _scope_hash(task)
    col = _collection()
    existing = col.find_one({"_id": tid}) or col.find_one({"task_id": tid})
    if existing and str(existing.get("status") or "") in TERMINAL_DECISIONS:
        if str(existing.get("status") or "") == "expired" and _task_still_needs_owner_auth(task):
            pass
        else:
            return {"ok": False, "error": "decision_already_closed", "task_id": tid}
    if (
        existing
        and str(existing.get("status") or "") in {"awaiting_owner_decision", "pending"}
        and str(existing.get("scope_hash") or "") == scope
        and int(existing.get("revision") or 0) == revision
        and _is_future_epoch(existing.get("expires_at"))
        and str(existing.get("nonce") or "")
    ):
        return {
            "ok": True,
            "task_id": tid,
            "nonce": str(existing["nonce"]),
            "duplicate": True,
        }
    nonce = secrets.token_hex(8)
    now = _now_epoch()
    row = _atlas_doc(task, scope=scope, nonce=nonce, now=now, expires=_expires_at_epoch(ttl_sec))
    row_set = {k: v for k, v in row.items() if k not in {"_id", "created_at"}}
    col.update_one({"_id": tid}, {"$set": row_set, "$setOnInsert": {"_id": tid, "created_at": now}}, upsert=True)
    return {"ok": True, "task_id": tid, "nonce": nonce}


def list_pending_authorizations(limit: int = 20) -> list[dict[str, Any]]:
    """Pendientes de autorización owner (PWA InnerOS)."""
    col = _collection()
    now = _now_epoch()
    cursor = (
        col.find(
            {
                "status": {"$in": ["pending", "awaiting_owner_decision"]},
                "expires_at": {"$gt": now},
            },
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(max(1, min(int(limit), 50)))
    )
    return list(cursor)


def close_pending_after_owner_grant(
    task_id: str,
    *,
    channel: str = "explicit",
    owner_actor: str = "RAFAEL",
) -> dict[str, Any]:
    """Cierra Atlas + bandeja inbox cuando authorize_ops_task no pasó por PWA/decide."""
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    col = _collection()
    row = col.find_one({"$or": [{"_id": tid}, {"task_id": tid}]})
    closed_registry = False
    if row and str(row.get("status") or "") in {"pending", "awaiting_owner_decision"}:
        now = _now_epoch()
        col.update_one(
            {"_id": row["_id"]},
            {
                "$set": {
                    "status": "approved",
                    "decided_by": channel,
                    "decided_at": now,
                    "owner_actor": owner_actor,
                    "updated_at": now,
                    "closed_via_owner_grant": True,
                }
            },
        )
        closed_registry = True
    try:
        from inneros_core_runtime import owner_push_history as inbox

        inbox.record_decision(task_id=tid, decision="approve", channel=channel, ok=True)
    except Exception:
        pass
    return {"ok": True, "task_id": tid, "closed_registry": closed_registry}


def consume_decision(
    *,
    task_id: str,
    nonce: str,
    decision: str,
    channel: str,
    owner_actor: str = "RAFAEL",
) -> dict[str, Any]:
    """Consume atómico: la primera decisión válida gana, la segunda se rechaza."""
    tid = (task_id or "").strip()
    if decision not in {"approve", "cancel"}:
        return {"ok": False, "error": "invalid_decision"}
    col = _collection()
    row = col.find_one({"_id": tid, "status": "pending"})
    if not row:
        row = col.find_one({"task_id": tid, "status": "awaiting_owner_decision"})
    if not row or not _is_future_epoch(row.get("expires_at")):
        return {"ok": False, "error": "decision_not_found_or_expired"}
    if not secrets.compare_digest(str(row.get("nonce") or ""), str(nonce or "")):
        return {"ok": False, "error": "nonce_mismatch"}
    new_status = "approved" if decision == "approve" else "cancelled"
    now = _now_epoch()
    updated = col.find_one_and_update(
        {"_id": row["_id"], "status": row["status"], "nonce": row["nonce"]},
        {
            "$set": {
                "status": new_status,
                "decided_by": channel,
                "decided_at": now,
                "owner_actor": owner_actor,
                "updated_at": now,
            }
        },
        return_document=True,
    )
    if not updated:
        loser = col.find_one({"task_id": tid}) or {}
        return {
            "ok": False,
            "error": "decision_already_resolved",
            "decided_by": str(loser.get("decided_by") or ""),
            "status": str(loser.get("status") or ""),
        }
    return {"ok": True, "task_id": tid, "decision": decision, "decided_by": channel}
