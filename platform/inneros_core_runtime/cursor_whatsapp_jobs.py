"""WhatsApp two-step: procede cursor → confirmar co_xxx → autoriza + claim."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from raphiia_openai import mongo_store

from inneros_core_runtime.cursor_ops_orchestrator import owner_order_execute, parse_correlation_from_text

COL = "ralfia_whatsapp_cursor_ops_jobs"
TTL_MIN = 15
REQUEST_RE = re.compile(
    r"^(?:procede|autoriza|ejecuta)\s+cursor(?:\s+ops)?(?:\s+(.+))?$",
    re.I | re.S,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_id() -> str:
    return f"co_{secrets.token_hex(4)}"


def request_order(sender: str, message: str, *, chat_id: str | None = None) -> dict[str, Any]:
    m = REQUEST_RE.match((message or "").strip())
    if not m:
        return {"ok": False, "error": "pattern_mismatch"}
    arg = (m.group(1) or "").strip()
    correlation_id = parse_correlation_from_text(arg)
    task_id = None
    if arg.startswith("ops_"):
        task_id = arg.split()[0]

    job_id = _job_id()
    doc = {
        "job_id": job_id,
        "sender": sender,
        "chat_id": chat_id or sender,
        "correlation_id": correlation_id,
        "task_id": task_id,
        "status": "pending",
        "created_at": _now(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=TTL_MIN)).isoformat(),
    }
    mongo_store.get_db()[COL].insert_one(doc)
    preview = correlation_id or task_id or "próxima tarea Cursor claimable"
    text = (
        f"*Cursor OPS · confirmación*\n\n"
        f"Encargo: `{preview}`\n"
        f"Modelo: composer-2.5-fast (fijado)\n\n"
        f"Responde en {TTL_MIN} min:\n"
        f"*confirmar {job_id}*\n\n"
        f"Cancelar: *cancelar {job_id}*"
    )
    return {"ok": True, "job_id": job_id, "text": text, "pending": doc}


def confirm_job(sender: str, job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip().lower()
    db = mongo_store.get_db()
    job = db[COL].find_one({"job_id": jid, "sender": sender, "status": "pending"})
    if not job:
        return {"ok": False, "error": "job_not_found_or_expired", "job_id": jid}
    exp = job.get("expires_at")
    if exp and str(exp) < _now():
        db[COL].update_one({"job_id": jid}, {"$set": {"status": "expired"}})
        return {"ok": False, "error": "job_expired", "job_id": jid}

    out = owner_order_execute(
        correlation_id=job.get("correlation_id"),
        task_id=job.get("task_id"),
        owner_actor="RAFAEL",
        channel="whatsapp",
        owner_approved=True,
    )
    status = "completed" if out.get("ok") else "failed"
    db[COL].update_one(
        {"job_id": jid},
        {"$set": {"status": status, "finished_at": _now(), "result": {k: out.get(k) for k in ("ok", "error", "stage")}}},
    )
    if out.get("ok"):
        c = out.get("claim") or {}
        text = (
            f"✅ Cursor claim OK\n"
            f"{c.get('task_id')}\n"
            f"{c.get('title', '')[:100]}\n"
            f"Modelo: {c.get('pinned_model')}"
        )
    else:
        text = f"❌ No se pudo claim: {out.get('error') or out.get('stage')}"
    return {**out, "ok": bool(out.get("ok")), "text": text, "job_id": jid}


def cancel_job(sender: str, job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip().lower()
    res = mongo_store.get_db()[COL].update_one(
        {"job_id": jid, "sender": sender, "status": "pending"},
        {"$set": {"status": "cancelled", "finished_at": _now()}},
    )
    if res.modified_count:
        return {"ok": True, "text": f"Cancelado {jid}.", "job_id": jid}
    return {"ok": False, "error": "job_not_found", "job_id": jid}
