"""Puente correo InnerOS (Mongo/IMAP) → GitLab ContributorOps autopilot."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

AGENT_SRC = Path("/home/rlopez/inneros/inneros_core/workspaces/gitlab-contributorops-agent/src")
INGRESS_FIELD = "contributorops_ingress"


def _agent_imports():
    if str(AGENT_SRC) not in sys.path:
        sys.path.insert(0, str(AGENT_SRC))
    from contributorops import email_ingress  # noqa: WPS433

    return email_ingress


def bridge_enabled() -> bool:
    if os.environ.get("CONTRIBUTOROPS_EMAIL_INGRESS", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return os.environ.get("CONTRIBUTOROPS_INNEROS_BRIDGE", "").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff(hours: int) -> datetime:
    # Mongo almacena received_at naive UTC en la mayoría de cuentas IMAP.
    return datetime.utcnow() - timedelta(hours=max(1, hours))


def _gitlab_email_query(cutoff: datetime) -> dict[str, Any]:
    gitlab_body = r"gitlab\.com|merge request|merge_requests|Pipeline.*MR"
    return {
        "received_at": {"$gte": cutoff},
        f"{INGRESS_FIELD}.at": {"$exists": False},
        "$or": [
            {"from_addr": {"$regex": r"gitlab\.com", "$options": "i"}},
            {"subject": {"$regex": r"gitlab|merge request|pipeline", "$options": "i"}},
            {"body_text": {"$regex": gitlab_body, "$options": "i"}},
            {"snippet": {"$regex": gitlab_body, "$options": "i"}},
        ],
    }


def _mark_ingress(mail_id: str, record: dict[str, Any]) -> None:
    mongo_store.get_db().email_messages.update_one(
        {"mail_id": mail_id},
        {"$set": {INGRESS_FIELD: {**record, "at": _now().isoformat()}}},
    )


def process_recent_gitlab_emails(
    *,
    hours: int = 72,
    limit: int = 40,
    dry_run: bool = False,
    spawn_repair: bool = True,
) -> dict[str, Any]:
    """Lee correos GitLab ya ingeridos por InnerOS y dispara autopilot si aplica."""
    if not bridge_enabled():
        return {"ok": True, "skipped": True, "reason": "contributorops_email_bridge_disabled"}

    email_ingress = _agent_imports()
    db = mongo_store.get_db()
    rows = list(
        db.email_messages.find(_gitlab_email_query(_cutoff(hours)), {"_id": 0})
        .sort("received_at", -1)
        .limit(max(5, min(limit, 200)))
    )

    handled: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    for doc in rows:
        mail_id = str(doc.get("mail_id") or "")
        evaluated = email_ingress.evaluate_email(doc)
        entry = {
            "mail_id": mail_id,
            "subject": (doc.get("subject") or "")[:120],
            "evaluated": evaluated,
        }
        if evaluated.get("skipped"):
            if not dry_run and mail_id:
                _mark_ingress(mail_id, {"status": "skipped", "reason": evaluated.get("reason")})
            handled.append(entry)
            continue

        event = evaluated.get("event") or {}
        decision = evaluated.get("decision") or {}
        entry["event_type"] = event.get("event_type")
        entry["auto_repair"] = bool(evaluated.get("auto_repair"))

        autopilot_out: dict[str, Any] | None = None
        if spawn_repair and evaluated.get("auto_repair") and not dry_run:
            from inneros_core_runtime import gitlab_contributorops_autopilot as autopilot  # noqa: WPS433

            autopilot_out = autopilot.handle_watch_result(
                {"event": event, "decision": decision},
                ledger=None,
            )
            repairs.append({"mail_id": mail_id, "autopilot": autopilot_out})
            entry["autopilot"] = autopilot_out

        if not dry_run and mail_id:
            _mark_ingress(
                mail_id,
                {
                    "status": "processed",
                    "event_type": event.get("event_type"),
                    "dedupe_key": decision.get("dedupe_key"),
                    "auto_repair": bool(evaluated.get("auto_repair")),
                    "autopilot": autopilot_out,
                },
            )
        handled.append(entry)

    return {
        "ok": True,
        "dry_run": dry_run,
        "scanned": len(rows),
        "handled": handled[:30],
        "repair_spawns": len(repairs),
        "repairs": repairs[:15],
    }


def run_after_email_poll(*, dry_run: bool = False) -> dict[str, Any]:
    """Llamar tras poll IMAP — no repite poll."""
    return process_recent_gitlab_emails(
        hours=int(os.environ.get("CONTRIBUTOROPS_EMAIL_LOOKBACK_HOURS", "96")),
        limit=int(os.environ.get("CONTRIBUTOROPS_EMAIL_INGRESS_LIMIT", "35")),
        dry_run=dry_run,
        spawn_repair=True,
    )
