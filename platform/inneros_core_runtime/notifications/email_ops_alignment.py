"""Alineación one-shot / periódica: cola ops correo, acciones Mongo, reprocess intel."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store

ACTIONS_COL = "ralfia_email_actions"
OPS_COL = "ralfia_ops_tasks"
NOISE_DOC_TYPES = frozenset({"spam_newsletter", "fyi"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mail_id_from_task(task: dict[str, Any]) -> str | None:
    corr = str(task.get("correlation_id") or "")
    if corr.startswith("email:"):
        return corr.split(":", 1)[1]
    for line in task.get("checklist") or []:
        m = re.search(r"mail_id:\s*(\S+)", str(line))
        if m:
            return m.group(1)
    return None


def _message_for_mail(mail_id: str) -> dict[str, Any] | None:
    return mongo_store.get_db().email_messages.find_one({"mail_id": mail_id}, {"_id": 0})


def classify_queued_email_op_noise(task: dict[str, Any]) -> tuple[bool, str]:
    title = str(task.get("title") or "")
    if not title.startswith("[Correo/"):
        return False, "not_email_ops"
    mail_id = _mail_id_from_task(task)
    if not mail_id:
        return False, "no_mail_id"
    msg = _message_for_mail(mail_id)
    if not msg:
        return True, "orphan_mail_missing"
    from raphiia_openai.notifications import email_intelligence

    decision = email_intelligence.decide_email(msg)
    if decision.get("document_type") in NOISE_DOC_TYPES:
        return True, f"noise_{decision.get('document_type')}"
    if decision.get("priority") == "low" and not decision.get("create_ops_task"):
        return True, "low_priority_no_task"
    review = msg.get("ralfia_review") or {}
    if review.get("category") in ("marketing", "security_code"):
        return True, "legacy_marketing"
    return False, "keep"


def cancel_queued_email_ops(*, dry_run: bool = True) -> dict[str, Any]:
    db = mongo_store.get_db()
    rows = list(db[OPS_COL].find({"status": "queued", "title": {"$regex": r"^\[Correo/"}}, {"_id": 0}))
    cancelled: list[dict[str, Any]] = []
    kept: list[str] = []
    for task in rows:
        task_id = str(task.get("task_id") or "")
        noisy, reason = classify_queued_email_op_noise(task)
        if not noisy:
            kept.append(task_id)
            continue
        entry = {"task_id": task_id, "title": task.get("title"), "reason": reason}
        cancelled.append(entry)
        if not dry_run and task_id:
            db[OPS_COL].update_one(
                {"task_id": task_id, "status": "queued"},
                {
                    "$set": {
                        "status": "cancelled",
                        "cleanup_bucket": "email_ops_noise",
                        "coordination_bucket": "email_ops_backlog",
                        "completed_at": _now(),
                        "updated_at": _now(),
                        "updated_by": "email_ops_alignment",
                        "dev_swarm_retry_requested": False,
                    },
                    "$push": {
                        "state_history": {
                            "from": "queued",
                            "to": "cancelled",
                            "actor": "email_ops_alignment",
                            "at": _now(),
                            "reason": reason,
                        }
                    },
                },
            )
    return {"ok": True, "dry_run": dry_run, "reviewed": len(rows), "cancelled": cancelled, "kept_task_ids": kept}


def dismiss_noise_email_actions(*, dry_run: bool = True, limit: int = 5000) -> dict[str, Any]:
    db = mongo_store.get_db()
    rows = list(
        db[ACTIONS_COL].find({"status": "pending", "document_type": {"$in": list(NOISE_DOC_TYPES)}}, {"_id": 1, "mail_id": 1})
        .limit(max(100, min(limit, 20000)))
    )
    updated = 0
    if not dry_run:
        for row in rows:
            db[ACTIONS_COL].update_one(
                {"_id": row["_id"]},
                {"$set": {"status": "dismissed", "updated_at": _now(), "dismiss_reason": "email_ops_alignment_noise"}},
            )
            updated += 1
    return {"ok": True, "dry_run": dry_run, "matched": len(rows), "updated": updated}


def reprocess_recent_mail(*, days: int = 14, limit: int = 400, create_task: bool = True) -> dict[str, Any]:
    from raphiia_openai.notifications import email_router

    db = mongo_store.get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    rows = list(
        db.email_messages.find({"received_at": {"$gte": cutoff}}, {"_id": 0})
        .sort("received_at", -1)
        .limit(max(10, min(limit, 2000)))
    )
    stats = {"processed": 0, "errors": 0, "tasks_created": 0, "noise": 0}
    for row in rows:
        try:
            out = email_router.process_email_intelligence(row, create_task=create_task)
            stats["processed"] += 1
            doc_type = (out.get("analysis") or {}).get("document_type")
            if doc_type in NOISE_DOC_TYPES:
                stats["noise"] += 1
            if (out.get("action") or {}).get("task", {}).get("task_id"):
                stats["tasks_created"] += 1
        except Exception:
            stats["errors"] += 1
    return {"ok": True, "days": days, "limit": limit, **stats}


def backfill_pending_email_actions(*, limit: int = 8000, dry_run: bool = True) -> dict[str, Any]:
    from raphiia_openai.notifications import email_intelligence

    db = mongo_store.get_db()
    rows = list(
        db[ACTIONS_COL].find(
            {"status": "pending", "$or": [{"document_type": {"$exists": False}}, {"document_type": None}]},
            {"_id": 1, "mail_id": 1},
        ).limit(max(100, min(limit, 25000)))
    )
    updated = dismissed = 0
    for row in rows:
        mail_id = str(row.get("mail_id") or "")
        if not mail_id:
            continue
        msg = _message_for_mail(mail_id) or {"mail_id": mail_id, "subject": "", "body_text": ""}
        decision = email_intelligence.decide_email(msg)
        patch = {
            "document_type": decision.get("document_type"),
            "category": decision.get("category"),
            "priority": decision.get("priority"),
            "agent_id": decision.get("route_agent"),
            "module": decision.get("route_module"),
            "suggested_actions": decision.get("suggested_actions"),
            "extracted_fields": decision.get("extracted_fields"),
            "requires_human_approval": decision.get("requires_human_approval"),
            "updated_at": _now(),
        }
        if decision.get("document_type") in NOISE_DOC_TYPES or decision.get("priority") == "low":
            patch["status"] = "dismissed"
            patch["dismiss_reason"] = "backfill_noise"
            dismissed += 1
        if not dry_run:
            db[ACTIONS_COL].update_one({"_id": row["_id"]}, {"$set": patch})
        updated += 1
    return {"ok": True, "dry_run": dry_run, "scanned": len(rows), "updated": updated, "dismissed": dismissed}


def run_email_ops_alignment(
    *,
    dry_run: bool = False,
    hygiene_limit: int = 400,
    reprocess_days: int = 14,
    reprocess_limit: int = 350,
) -> dict[str, Any]:
    from inneros_core_runtime import dev_swarm_scheduler

    hygiene = dev_swarm_scheduler.reconcile_coordination_backlog_hygiene(limit=hygiene_limit, dry_run=dry_run)
    cancel = cancel_queued_email_ops(dry_run=dry_run)
    dismiss = dismiss_noise_email_actions(dry_run=dry_run)
    backfill = backfill_pending_email_actions(limit=12000, dry_run=dry_run)
    reprocess = {}
    if not dry_run:
        reprocess = reprocess_recent_mail(days=reprocess_days, limit=reprocess_limit, create_task=True)
    return {
        "ok": True,
        "dry_run": dry_run,
        "hygiene": hygiene,
        "cancel_queued_email_ops": cancel,
        "dismiss_noise_actions": dismiss,
        "backfill_pending_actions": backfill,
        "reprocess_recent": reprocess,
        "finished_at": _now(),
    }
