"""Two-phase, identity-bound WhatsApp maintenance jobs; never arbitrary shell."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store, whatsapp_identity, whatsapp_service_ops
from raphiia_openai.notifications.evolution_client import send_whatsapp

COLLECTION = "ralfia_whatsapp_admin_jobs"
AUDIT_COLLECTION = "ralfia_whatsapp_admin_audit"
LOCK_COLLECTION = "ralfia_whatsapp_service_locks"
PACKAGES = ("ffmpeg", "tesseract-ocr", "tesseract-ocr-spa", "tesseract-ocr-eng")
CONFIRM_TTL_SECONDS = 180
LOCK_TTL_SECONDS = 120
COOLDOWN_SECONDS = 45
MAX_PENDING_PER_FIVE_MINUTES = 5


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _new_id() -> str:
    return f"wajob_{secrets.token_urlsafe(8).lower()}"


def _challenge() -> str:
    return secrets.token_hex(3).upper()


def _chat_hash(chat_id: str | None, sender: str) -> str:
    binding = str(chat_id or sender or "").strip().lower()
    return hashlib.sha256(binding.encode("utf-8")).hexdigest()[:20]


def _identity(sender: str, chat_id: str | None) -> dict[str, Any]:
    return whatsapp_identity.resolve_identity(sender, chat_id=chat_id, is_group=str(chat_id or "").endswith("@g.us"))


def _authorized(identity: dict[str, Any]) -> bool:
    return whatsapp_identity.has_scope(identity, "whatsapp:maintenance:request")


def _can_confirm(identity: dict[str, Any]) -> bool:
    return whatsapp_identity.is_owner(identity) and whatsapp_identity.has_scope(
        identity, "whatsapp:maintenance:confirm"
    )


def _notify_owner_for_approval(text: str, *, node: str) -> list[dict[str, Any]]:
    deliveries: list[dict[str, Any]] = []
    try:
        destinations = whatsapp_identity.notification_destinations()
    except Exception:
        destinations = []
    for destination in destinations[:1]:
        result = send_whatsapp(text, number=str(destination).lstrip("+"), node=node)
        deliveries.append({"ok": bool(result.get("ok")) if isinstance(result, dict) else False})
    return deliveries


def _rate_limited(principal_id: str) -> bool:
    cutoff = (_now_dt() - timedelta(minutes=5)).isoformat()
    count = mongo_store.get_db()[COLLECTION].count_documents(
        {"principal_id": principal_id, "created_at": {"$gte": cutoff}}
    )
    return count >= MAX_PENDING_PER_FIVE_MINUTES


def _cooldown_job(principal_id: str, node: str, service: str) -> dict[str, Any] | None:
    cutoff = (_now_dt() - timedelta(seconds=COOLDOWN_SECONDS)).isoformat()
    return mongo_store.get_db()[COLLECTION].find_one(
        {
            "principal_id": principal_id,
            "node": node,
            "service": service,
            "status": "completed",
            "finished_at": {"$gte": cutoff},
        },
        {"_id": 0, "job_id": 1, "finished_at": 1},
        sort=[("finished_at", -1)],
    )


def request_install(sender: str, node: str = "primary", *, chat_id: str | None = None) -> dict[str, Any]:
    identity = _identity(sender, chat_id)
    if not _can_confirm(identity):
        return {"ok": False, "error": "unauthorized_principal"}
    db = mongo_store.get_db()
    now = _now()
    job_id = _new_id()
    challenge = _challenge()
    doc = {
        "job_id": job_id,
        "job_name": "whatsapp-media-runtime",
        "packages": list(PACKAGES),
        "principal_id": identity["principal_id"],
        "approval_principal_id": whatsapp_identity.OWNER_PRINCIPAL_ID,
        "requested_by_hash": identity["sender_hash"],
        "requested_by_e164": whatsapp_identity.normalize_e164(sender),
        "chat_hash": _chat_hash(chat_id, sender),
        "node": whatsapp_service_ops.normalize_node(node),
        "status": "pending_confirmation",
        "challenge": challenge,
        "created_at": now,
        "updated_at": now,
        "expires_at": (_now_dt() + timedelta(seconds=CONFIRM_TTL_SECONDS)).isoformat(),
        "execution": "disabled_until_sudo_policy",
    }
    db[COLLECTION].insert_one(doc)
    return {
        "ok": True,
        "job_id": job_id,
        "status": doc["status"],
        "packages": list(PACKAGES),
        "text": f"Solicitud {job_id} creada. Esta instalación sigue deshabilitada: no enviaré ni pediré una clave sudo por WhatsApp.",
    }


def request_service_action(
    sender: str,
    *,
    chat_id: str,
    service: str,
    node: str,
    action: str,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = _identity(sender, chat_id)
    if not _authorized(identity):
        return {"ok": False, "error": "unauthorized_principal"}
    if str(chat_id or "").endswith("@g.us"):
        return {"ok": False, "error": "maintenance_not_allowed_in_groups"}
    spec = whatsapp_service_ops.SERVICE_BY_ID.get((service or "").lower())
    normalized_node = whatsapp_service_ops.normalize_node(node)
    normalized_action = (action or "").lower()
    if not spec:
        return {"ok": False, "error": "service_not_allowlisted"}
    if normalized_action not in {"start", "restart", "recover"}:
        return {"ok": False, "error": "action_not_allowlisted"}
    if not spec.unit(normalized_node) and not spec.container(normalized_node):
        return {"ok": False, "error": "service_not_available_on_node"}
    if _rate_limited(str(identity["principal_id"])):
        return {"ok": False, "error": "maintenance_rate_limited"}
    trace = trace or {}
    event_key = str(trace.get("correlation_id") or trace.get("message_id") or "").strip()
    if not event_key:
        event_key = str(int(_now_dt().timestamp()) // COOLDOWN_SECONDS)
    idempotency_key = hashlib.sha256(
        f"{identity['principal_id']}|{_chat_hash(chat_id, sender)}|{normalized_node}|{spec.service_id}|{normalized_action}|{event_key}".encode()
    ).hexdigest()[:24]
    db = mongo_store.get_db()
    existing = db[COLLECTION].find_one(
        {
            "idempotency_key": idempotency_key,
            "status": {"$in": ["pending_confirmation", "approved", "running", "completed"]},
        },
        {"_id": 0},
    )
    if existing:
        return {
            "ok": True,
            "idempotent": True,
            "job_id": existing.get("job_id"),
            "status": existing.get("status"),
            "text": f"La operación ya existe: {existing.get('job_id')} ({existing.get('status')}).",
        }
    cooldown = _cooldown_job(str(identity["principal_id"]), normalized_node, spec.service_id)
    if cooldown:
        return {
            "ok": False,
            "error": "maintenance_cooldown",
            "job_id": cooldown.get("job_id"),
            "retry_after_seconds": COOLDOWN_SECONDS,
            "text": f"Ese servicio fue operado hace menos de {COOLDOWN_SECONDS} segundos. Espera antes de repetir.",
        }
    before = whatsapp_service_ops.service_status(spec.service_id, normalized_node)
    if normalized_action in {"start", "recover"} and before.get("healthy"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_healthy",
            "service": spec.service_id,
            "node": normalized_node,
            "before": before,
            "text": f"{spec.label} en {whatsapp_service_ops.NODE_LABELS[normalized_node]} ya está saludable; no ejecutaré nada.",
        }
    now_dt = _now_dt()
    job_id = _new_id()
    challenge = _challenge()
    doc = {
        "job_id": job_id,
        "job_name": f"{normalized_action}:{normalized_node}:{spec.service_id}",
        "service": spec.service_id,
        "service_label": spec.label,
        "action": normalized_action,
        "node": normalized_node,
        "principal_id": identity["principal_id"],
        "approval_principal_id": whatsapp_identity.OWNER_PRINCIPAL_ID,
        "requested_by_hash": identity["sender_hash"],
        "requested_by_e164": whatsapp_identity.normalize_e164(sender),
        "chat_hash": _chat_hash(chat_id, sender),
        "status": "pending_confirmation",
        "challenge": challenge,
        "idempotency_key": idempotency_key,
        "trace_id": trace.get("correlation_id"),
        "source_message_id": trace.get("message_id"),
        "before": before,
        "created_at": now_dt.isoformat(),
        "updated_at": now_dt.isoformat(),
        "expires_at": (now_dt + timedelta(seconds=CONFIRM_TTL_SECONDS)).isoformat(),
        "execution": "typed_service_action",
    }
    db[COLLECTION].insert_one(doc)
    db[AUDIT_COLLECTION].insert_one(
        {
            "operation_id": job_id,
            "event": "requested",
            "principal_id": identity["principal_id"],
            "sender_hash": identity["sender_hash"],
            "chat_hash": doc["chat_hash"],
            "node": normalized_node,
            "service": spec.service_id,
            "action": normalized_action,
            "trace_id": doc.get("trace_id"),
            "at": now_dt.isoformat(),
        }
    )
    confirm_instruction = (
        f"Confirma desde este mismo chat en 3 minutos: *confirmar {challenge}*"
        if _can_confirm(identity)
        else f"Rafael debe confirmar desde su línea principal en 3 minutos: *confirmar {challenge}*"
    )
    prompt_text = (
        f"Propongo *{normalized_action}* de {spec.label} en {whatsapp_service_ops.NODE_LABELS[normalized_node]}.\n"
        f"Estado: {before.get('system_state')} / {before.get('health')}.\n"
        f"{confirm_instruction}"
    )
    result = {
        "ok": True,
        "job_id": job_id,
        "challenge": challenge,
        "status": "pending_confirmation",
        "before": before,
        "text": prompt_text,
    }
    if _can_confirm(identity):
        result["interactive"] = {
            "kind": "buttons",
            "buttons": [
                {"id": f"maint.confirm.{challenge}", "label": "Confirmar"},
                {"id": f"maint.cancel.{job_id}", "label": "Cancelar"},
            ],
            "fallback_text": prompt_text + f"\nPara cancelar: *cancelar {job_id}*",
        }
    else:
        owner_prompt = (
            f"Solicitud operativa {job_id} recibida de {identity.get('preferred_name') or 'línea autorizada'}.\n"
            + prompt_text
        )
        result["approval_notifications"] = _notify_owner_for_approval(
            owner_prompt, node=normalized_node
        )
        result["text"] = (
            f"Solicitud {job_id} creada y enviada a Rafael para aprobación. "
            "Esta línea no puede confirmar ni ejecutar la operación."
        )
    return result


def request_service_restart(
    sender: str,
    service: str,
    node: str = "primary",
    *,
    chat_id: str | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return request_service_action(
        sender,
        chat_id=str(chat_id or sender),
        service=service,
        node=node,
        action="restart",
        trace=trace,
    )


def confirm_job(sender: str, token: str, *, chat_id: str | None = None) -> dict[str, Any]:
    identity = _identity(sender, chat_id)
    if not _can_confirm(identity):
        return {"ok": False, "error": "unauthorized_principal"}
    db = mongo_store.get_db()
    lookup = str(token or "").strip()
    job = db[COLLECTION].find_one(
        {"$or": [{"job_id": lookup.lower()}, {"challenge": lookup.upper()}]}
    )
    approval_principal = (job or {}).get("approval_principal_id") or (job or {}).get("principal_id")
    if not job or approval_principal != identity.get("principal_id"):
        return {"ok": False, "error": "job_not_found_or_principal_mismatch"}
    if job.get("principal_id") == identity.get("principal_id"):
        if job.get("requested_by_hash") != identity.get("sender_hash"):
            return {"ok": False, "error": "sender_mismatch"}
        if job.get("chat_hash") != _chat_hash(chat_id, sender):
            return {"ok": False, "error": "chat_mismatch"}
    if job.get("status") != "pending_confirmation":
        return {"ok": False, "error": "job_not_pending", "status": job.get("status")}
    if str(job.get("expires_at") or "") < _now():
        db[COLLECTION].update_one(
            {"job_id": job["job_id"], "status": "pending_confirmation"},
            {"$set": {"status": "expired", "updated_at": _now()}},
        )
        return {"ok": False, "error": "confirmation_expired"}
    updated = db[COLLECTION].update_one(
        {"job_id": job["job_id"], "status": "pending_confirmation"},
        {"$set": {
            "status": "approved",
            "approved_at": _now(),
            "approved_by_hash": identity.get("sender_hash"),
            "approval_chat_hash": _chat_hash(chat_id, sender),
            "updated_at": _now(),
        }},
    )
    if getattr(updated, "modified_count", 1) != 1:
        return {"ok": False, "error": "confirmation_race_lost"}
    if job.get("execution") == "disabled_until_sudo_policy":
        text = "Solicitud confirmada, pero no se ejecutará: no existe una política privilegiada allowlisted."
    else:
        text = f"Operación {job['job_id']} confirmada. El runner seguro verificará estado antes y después."
    db[AUDIT_COLLECTION].insert_one(
        {
            "operation_id": job["job_id"],
            "event": "approved",
            "principal_id": identity["principal_id"],
            "sender_hash": identity["sender_hash"],
            "chat_hash": job.get("chat_hash"),
            "at": _now(),
        }
    )
    return {"ok": True, "job_id": job["job_id"], "status": "approved", "text": text}


def confirm_install(sender: str, job_id: str, *, chat_id: str | None = None) -> dict[str, Any]:
    return confirm_job(sender, job_id, chat_id=chat_id)


def cancel_job(sender: str, token: str, *, chat_id: str | None = None) -> dict[str, Any]:
    identity = _identity(sender, chat_id)
    if not (_can_confirm(identity) or _authorized(identity)):
        return {"ok": False, "error": "unauthorized_principal"}
    db = mongo_store.get_db()
    lookup = str(token or "").strip()
    job = db[COLLECTION].find_one(
        {"$or": [{"job_id": lookup.lower()}, {"challenge": lookup.upper()}]}
    )
    if not job:
        return {"ok": False, "error": "job_not_found_or_principal_mismatch"}
    requester = job.get("principal_id") == identity.get("principal_id")
    approver = job.get("approval_principal_id") == identity.get("principal_id") and _can_confirm(identity)
    if not (requester or approver):
        return {"ok": False, "error": "job_not_found_or_principal_mismatch"}
    if requester:
        if job.get("requested_by_hash") != identity.get("sender_hash"):
            return {"ok": False, "error": "sender_mismatch"}
        if job.get("chat_hash") != _chat_hash(chat_id, sender):
            return {"ok": False, "error": "chat_mismatch"}
    if job.get("status") != "pending_confirmation":
        return {"ok": False, "error": "job_not_pending", "status": job.get("status")}
    updated = db[COLLECTION].update_one(
        {"job_id": job["job_id"], "status": "pending_confirmation"},
        {"$set": {"status": "cancelled", "cancelled_at": _now(), "updated_at": _now()}},
    )
    if getattr(updated, "modified_count", 1) != 1:
        return {"ok": False, "error": "cancellation_race_lost"}
    db[AUDIT_COLLECTION].insert_one(
        {
            "operation_id": job["job_id"],
            "event": "cancelled",
            "principal_id": identity["principal_id"],
            "sender_hash": identity["sender_hash"],
            "chat_hash": job.get("chat_hash"),
            "at": _now(),
        }
    )
    return {"ok": True, "job_id": job["job_id"], "status": "cancelled", "text": "Cancelado. No ejecuté nada."}


def _acquire_lock(job: dict[str, Any]) -> bool:
    db = mongo_store.get_db()
    lock_id = f"{job.get('node')}:{job.get('service')}"
    now = _now()
    current = db[LOCK_COLLECTION].find_one({"_id": lock_id})
    if current and str(current.get("expires_at") or "") > now and current.get("operation_id") != job.get("job_id"):
        return False
    db[LOCK_COLLECTION].update_one(
        {"_id": lock_id},
        {
            "$set": {
                "operation_id": job.get("job_id"),
                "principal_id": job.get("principal_id"),
                "acquired_at": now,
                "expires_at": (_now_dt() + timedelta(seconds=LOCK_TTL_SECONDS)).isoformat(),
            }
        },
        upsert=True,
    )
    return True


def _release_lock(job: dict[str, Any]) -> None:
    mongo_store.get_db()[LOCK_COLLECTION].delete_one(
        {"_id": f"{job.get('node')}:{job.get('service')}", "operation_id": job.get("job_id")}
    )


def _send_result(job: dict[str, Any], text: str) -> bool:
    destination = str(job.get("requested_by_e164") or "").lstrip("+")
    if not destination:
        return False
    preferred = str(job.get("node") or "primary")
    fallback = "amd" if preferred == "primary" else "primary"
    first = send_whatsapp(text, number=destination, node=preferred)
    if first.get("ok"):
        return True
    return bool(send_whatsapp(text, number=destination, node=fallback).get("ok"))


def run_next_approved_job() -> dict[str, Any]:
    db = mongo_store.get_db()
    job = db[COLLECTION].find_one(
        {"status": "approved", "execution": "typed_service_action"},
        {"_id": 0},
        sort=[("approved_at", 1)],
    )
    if not job:
        return {"ok": True, "status": "idle"}
    if not _acquire_lock(job):
        return {"ok": True, "status": "locked", "job_id": job.get("job_id")}
    try:
        claimed = db[COLLECTION].update_one(
            {"job_id": job["job_id"], "status": "approved"},
            {"$set": {"status": "running", "started_at": _now(), "updated_at": _now()}},
        )
        if getattr(claimed, "modified_count", 1) != 1:
            return {"ok": True, "status": "claim_lost", "job_id": job["job_id"]}
        result = whatsapp_service_ops.execute_service_action(
            str(job.get("service") or ""),
            str(job.get("node") or "primary"),
            str(job.get("action") or "recover"),
        )
        status = "completed" if result.get("ok") else "failed"
        db[COLLECTION].update_one(
            {"job_id": job["job_id"], "status": "running"},
            {
                "$set": {
                    "status": status,
                    "result": result,
                    "before": result.get("before") or job.get("before"),
                    "after": result.get("after"),
                    "finished_at": _now(),
                    "updated_at": _now(),
                }
            },
        )
        db[AUDIT_COLLECTION].insert_one(
            {
                "operation_id": job["job_id"],
                "event": status,
                "principal_id": job.get("principal_id"),
                "sender_hash": job.get("requested_by_hash"),
                "chat_hash": job.get("chat_hash"),
                "node": job.get("node"),
                "service": job.get("service"),
                "action": job.get("action"),
                "before": result.get("before"),
                "after": result.get("after"),
                "trace_id": job.get("trace_id"),
                "at": _now(),
            }
        )
        after = result.get("after") or {}
        message = (
            f"{'✅' if result.get('ok') else '❌'} Operación {job['job_id']} {status}.\n"
            f"{job.get('service_label')} en {whatsapp_service_ops.NODE_LABELS.get(str(job.get('node')), str(job.get('node')))}.\n"
            f"Estado final: {after.get('system_state', '?')} / {after.get('health', '?')}."
        )
        _send_result(job, message)
        return {"ok": bool(result.get("ok")), "job_id": job["job_id"], "status": status, "result": result}
    finally:
        _release_lock(job)
