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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at(ttl_sec: int | None = None) -> str:
    sec = max(60, int(ttl_sec if ttl_sec is not None else DEFAULT_TTL_SEC))
    return (datetime.now(timezone.utc) + timedelta(seconds=sec)).isoformat()


def _is_future(iso: str) -> bool:
    try:
        return datetime.fromisoformat(iso) > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def _scope_hash(task: dict[str, Any]) -> str:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    blob = "|".join(
        [
            str(task.get("task_id") or ""),
            str(task.get("assignee") or task.get("preferred_provider") or ""),
            str(task.get("objective") or task.get("title") or ""),
            str(payload.get("preferred_provider") or ""),
            str(task.get("correlation_id") or ""),
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _collection():
    db = mongo_store.get_db()
    col = db[COLLECTION]
    col.create_index("task_id", unique=True)
    col.create_index([("status", 1), ("expires_at", 1)])
    return col


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
    existing = col.find_one({"task_id": tid})
    if existing and str(existing.get("status") or "") in TERMINAL_DECISIONS:
        return {"ok": False, "error": "decision_already_closed", "task_id": tid}
    if (
        existing
        and str(existing.get("status") or "") == "awaiting_owner_decision"
        and str(existing.get("scope_hash") or "") == scope
        and int(existing.get("revision") or 0) == revision
        and _is_future(str(existing.get("expires_at") or ""))
        and str(existing.get("nonce") or "")
    ):
        return {
            "ok": True,
            "task_id": tid,
            "nonce": str(existing["nonce"]),
            "duplicate": True,
        }
    row = {
        "task_id": tid,
        "human_task_id": str(task.get("human_task_id") or task.get("task_alias") or tid),
        "provider": provider,
        "revision": revision,
        "correlation_id": str(task.get("correlation_id") or ""),
        "scope_hash": scope,
        "nonce": secrets.token_urlsafe(32),
        "status": "awaiting_owner_decision",
        "decided_by": "",
        "decided_at": "",
        "expires_at": _expires_at(ttl_sec),
        "updated_at": _now(),
    }
    col.update_one({"task_id": tid}, {"$set": row, "$setOnInsert": {"created_at": _now()}}, upsert=True)
    return {"ok": True, "task_id": tid, "nonce": row["nonce"]}


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
    row = col.find_one({"task_id": tid, "status": "awaiting_owner_decision"})
    if not row or not _is_future(str(row.get("expires_at") or "")):
        return {"ok": False, "error": "decision_not_found_or_expired"}
    if not secrets.compare_digest(str(row.get("nonce") or ""), str(nonce or "")):
        return {"ok": False, "error": "nonce_mismatch"}
    new_status = "approved" if decision == "approve" else "cancelled"
    updated = col.find_one_and_update(
        {"task_id": tid, "status": "awaiting_owner_decision", "nonce": row["nonce"]},
        {
            "$set": {
                "status": new_status,
                "decided_by": channel,
                "decided_at": _now(),
                "owner_actor": owner_actor,
                "updated_at": _now(),
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
