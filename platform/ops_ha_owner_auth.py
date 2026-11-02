"""Home Assistant Companion notifications for OPS owner authorization (separate from Atlas bandeja)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

COLLECTION = "ralfia_ops_ha_authorization_pending"
EVENT = "inneros_ops_owner_approval_decision"
SCRIPT_ID = "inneros_ops_owner_approval_decide"
DEFAULT_URL_PATH = "inneros-ops-approvals"
DEFAULT_TTL_SEC = int(os.getenv("OPS_HA_APPROVAL_TTL_SEC", "7200"))


def ha_auth_enabled() -> bool:
    return os.getenv("NOTIFY_OPS_AUTH_HA", "0").strip().lower() in {"1", "true", "yes", "on"}


def _notify_service() -> str:
    raw = (
        os.getenv("OPS_HA_NOTIFY_SERVICE")
        or os.getenv("AMBIENT_GUARDIAN_MOBILE_NOTIFY_SERVICE")
        or "mobile_app_infinix_x6873"
    ).strip()
    return raw.split(".", 1)[-1] if raw.startswith("notify.") else raw


def _url_path() -> str:
    return (os.getenv("OPS_HA_APPROVAL_URL_PATH") or DEFAULT_URL_PATH).strip().strip("/")


def _owner_id() -> str:
    return (
        os.getenv("OPS_HA_OWNER_ID")
        or os.getenv("AMBIENT_GUARDIAN_MOBILE_OWNER_ID")
        or ""
    ).strip()


def _collection():
    db = mongo_store.get_db()
    col = db[COLLECTION]
    col.create_index("task_id", unique=True)
    col.create_index([("status", 1), ("created_at", -1)])
    return col


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at(ttl_sec: int | None = None) -> str:
    sec = int(ttl_sec if ttl_sec is not None else DEFAULT_TTL_SEC)
    return (datetime.now(timezone.utc) + timedelta(seconds=max(60, sec))).isoformat()


def _is_future(iso: str) -> bool:
    try:
        return datetime.fromisoformat(iso) > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def persist_pending(
    task: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
    headline: str = "",
    body: str = "",
    ttl_sec: int | None = None,
) -> dict[str, Any]:
    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    provider = str(task.get("assignee") or task.get("preferred_provider") or "?")
    revision = int(task.get("revision") or 0)
    alias = str(task.get("human_task_id") or task.get("task_alias") or tid)
    row = {
        "task_id": tid,
        "human_task_id": alias,
        "provider": provider,
        "revision": revision,
        "correlation_id": str(task.get("correlation_id") or ""),
        "headline": headline[:240],
        "body_preview": body[:1200],
        "summary": summary or {},
        "owner_id": _owner_id(),
        "nonce": secrets.token_urlsafe(32),
        "status": "awaiting_owner_approval",
        "channel": "home_assistant_companion_ops",
        "expires_at": _expires_at(ttl_sec),
        "updated_at": _now(),
    }
    col = _collection()
    existing = col.find_one({"task_id": tid}, {"status": 1, "revision": 1, "nonce": 1})
    if existing and existing.get("status") != "awaiting_owner_approval":
        return {"ok": False, "error": "approval_task_already_closed", "task_id": tid}
    if (
        existing
        and existing.get("status") == "awaiting_owner_approval"
        and int(existing.get("revision") or 0) == revision
        and existing.get("nonce")
    ):
        row["nonce"] = str(existing["nonce"])
    col.update_one({"task_id": tid}, {"$set": row, "$setOnInsert": {"created_at": _now()}}, upsert=True)
    return {"ok": True, "task_id": tid, "nonce": row["nonce"], "revision": revision}


def send_companion_push(row: dict[str, Any]) -> dict[str, Any]:
    from inneros_core_runtime import homeassistant_client as ha

    if not ha.configured():
        return {"ok": False, "skipped": "ha_not_configured"}
    service = _notify_service()
    path = _url_path()
    tid = str(row.get("task_id") or "")
    title = str(row.get("headline") or "InnerOS · autorización OPS").strip()
    alias = str(row.get("human_task_id") or tid)
    provider = str(row.get("provider") or "?").upper()
    message = f"{alias} · {provider}. Toca para revisar y autorizar."
    payload = {
        "title": title[:120],
        "message": message[:500],
        "data": {
            "tag": tid,
            "ttl": int(os.getenv("OPS_HA_PUSH_TTL_SEC", "3600")),
            "priority": "high",
            "channel": "InnerOS OPS",
            "importance": "high",
            "clickAction": f"/{path}/{tid}",
        },
    }
    result = ha.call_service("notify", service, data=payload)
    if result.get("ok"):
        _collection().update_one(
            {"task_id": tid},
            {"$set": {"approval_delivered_at": _now(), "updated_at": _now()}},
        )
    return {"ok": bool(result.get("ok")), "ha": result, "service": service, "clickAction": payload["data"]["clickAction"]}


def notify_ops_owner_ha_authorization(
    task: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
    headline: str = "",
    body: str = "",
) -> dict[str, Any]:
    if not ha_auth_enabled():
        return {"ok": False, "skipped": "notify_ops_auth_ha_disabled"}
    pending = persist_pending(task, summary=summary, headline=headline, body=body)
    if not pending.get("ok"):
        return pending
    row = _collection().find_one({"task_id": pending["task_id"]})
    if not row:
        return {"ok": False, "error": "pending_row_missing"}
    push = send_companion_push(row)
    return {
        "ok": bool(push.get("ok")),
        "task_id": pending["task_id"],
        "channel": "home_assistant_companion_ops",
        "push": push,
    }


def apply_owner_decision(
    *,
    task_id: str,
    nonce: str,
    decision: str,
    owner_user_id: str,
) -> dict[str, Any]:
    if decision not in {"approve", "cancel"}:
        return {"ok": False, "error": "invalid_decision"}
    owner_cfg = _owner_id()
    if owner_cfg and owner_user_id != owner_cfg:
        return {"ok": False, "error": "owner_mismatch"}
    col = _collection()
    row = col.find_one({"task_id": task_id, "status": "awaiting_owner_approval"})
    if not row or not _is_future(str(row.get("expires_at") or "")):
        return {"ok": False, "error": "approval_not_found_or_expired"}
    if not secrets.compare_digest(str(row.get("nonce") or ""), str(nonce or "")):
        return {"ok": False, "error": "nonce_mismatch"}
    new_status = "approved" if decision == "approve" else "cancelled"
    updated = col.find_one_and_update(
        {"task_id": task_id, "status": "awaiting_owner_approval", "nonce": row["nonce"]},
        {
            "$set": {
                "status": new_status,
                "authorized_at": _now(),
                "owner_user_id": owner_user_id,
                "updated_at": _now(),
            }
        },
        return_document=True,
    )
    if not updated:
        return {"ok": False, "error": "cas_failed"}
    if decision != "approve":
        return {"ok": True, "task_id": task_id, "decision": "cancel", "authorized": False}
    provider = str(row.get("provider") or "cursor").lower()
    owner_actor = owner_user_id or "RAFAEL"
    channel = "ha_companion_ops"
    if provider == "antigravity":
        from inneros_core_runtime import antigravity_ops_runner as ag

        auth = ag.authorize_ops_task_for_antigravity(task_id, owner_actor=owner_actor, channel=channel)
    elif provider == "codex":
        from inneros_core_runtime import codex_ops_runner as cx

        auth = cx.authorize_ops_task_for_codex(task_id, owner_actor=owner_actor, channel=channel)
    else:
        from inneros_core_runtime import interactive_ops_runner as ior

        auth = ior.authorize_ops_task(provider, task_id, owner_actor=owner_actor, channel=channel)
    if not auth.get("ok") and auth.get("error") == "task_not_found":
        col.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": "approved",
                    "authorize_note": "ops_task_missing_smoke_or_stale",
                    "updated_at": _now(),
                }
            },
        )
        return {
            "ok": True,
            "task_id": task_id,
            "decision": "approve",
            "authorized": False,
            "authorize_result": auth,
            "note": "decision_recorded_ops_task_missing",
        }
    autopilot: dict[str, Any] = {"skipped": "not_run"}
    if auth.get("ok"):
        try:
            from inneros_core_runtime import ops_post_owner_autopilot as autop

            autopilot = autop.try_finish_after_owner_auth(task_id)
        except Exception as exc:
            autopilot = {"ok": False, "error": str(exc)[:300]}
    return {
        "ok": bool(auth.get("ok")),
        "task_id": task_id,
        "decision": "approve",
        "authorized": bool(auth.get("ok")),
        "authorize_result": auth,
        "autopilot": autopilot,
    }


def notify_companion_scout_alert(*, title: str, message: str) -> dict[str, Any]:
    """Push Companion para alertas de coordinación / oportunidades (sin ops task)."""
    if not ha_auth_enabled():
        return {"ok": False, "skipped": "notify_ops_auth_ha_disabled"}
    from inneros_core_runtime import homeassistant_client as ha

    if not ha.configured():
        return {"ok": False, "skipped": "ha_not_configured"}
    service = _notify_service()
    payload = {
        "title": (title or "RalfIA")[:120],
        "message": (message or "")[:500],
        "data": {
            "tag": f"scout-{int(time.time()) // 3600}",
            "priority": "high",
            "channel": "InnerOS Scout",
            "importance": "default",
        },
    }
    result = ha.call_service("notify", service, data=payload)
    return {"ok": bool(result.get("ok")), "ha": result, "service": service}


def notify_companion_ops_outcome(
    task: dict[str, Any],
    *,
    status: str,
    detail: str = "",
) -> dict[str, Any]:
    """Push Companion when an OPS task finishes (headless Antigravity/Cursor, etc.)."""
    if not ha_auth_enabled():
        return {"ok": False, "skipped": "notify_ops_auth_ha_disabled"}
    from inneros_core_runtime import homeassistant_client as ha

    if not ha.configured():
        return {"ok": False, "skipped": "ha_not_configured"}
    tid = str(task.get("task_id") or "")
    alias = str(task.get("human_task_id") or task.get("task_alias") or tid)
    provider = str(task.get("assignee") or task.get("preferred_provider") or "ops").upper()
    st = (status or str(task.get("status") or "")).lower()
    icon = {"completed": "✅", "failed": "❌", "blocked": "⛔"}.get(st, "ℹ️")
    title = f"{icon} InnerOS · {provider} · {st.upper()}"
    message = f"{alias}: {st}"
    if detail:
        message = f"{message} — {detail[:180]}"
    service = _notify_service()
    payload = {
        "title": title[:120],
        "message": message[:500],
        "data": {
            "tag": f"ops-outcome-{tid}",
            "channel": "InnerOS OPS",
            "importance": "high",
        },
    }
    result = ha.call_service("notify", service, data=payload)
    return {"ok": bool(result.get("ok")), "ha": result, "task_id": tid, "status": st}


def dashboard_fingerprint(views: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(views, sort_keys=True).encode()).hexdigest()
