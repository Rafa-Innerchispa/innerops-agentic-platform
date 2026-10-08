"""Integración Gmail/IMAP → ciclo AG-25 (poll, higiene, puente Dev Swarm).

Usa Swarm :8100 / Mongo email_accounts (mismo stack que ralfia-notify).
Las tareas operativas de correo con señales GitLab/InnerOS se promueven a
``proposed`` con repo y ``execution_lane`` para que Dev Swarm no las deje en
``email_ops_backlog``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

OPS_COL = "ralfia_ops_tasks"
ACTIONS_COL = "ralfia_email_actions"
INNEROS_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
GITLAB_UPSTREAM_REPO = "gitlab-org/gitlab"

DEV_SIGNAL_MARKERS = (
    "gitlab",
    "merge request",
    "merge_request",
    "merge requests",
    "pipeline failed",
    "pipeline has failed",
    "ci/cd",
    "ci failed",
    "github",
    "pull request",
    "dependabot",
    "inneros",
    "innerops",
    "dev swarm",
    "contributorops",
    "contributor ops",
    "resource fabric",
    "local execution",
    "gitlab.com",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _core_root() -> Path:
    return Path(os.environ.get("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core"))


def _state_path() -> Path:
    p = _core_root() / "var" / "inneros_autopilot" / "last-gmail-integration.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _save_state(patch: dict[str, Any]) -> None:
    state = _load_state()
    state.update(patch)
    state["updated_at"] = _now()
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def classify_dev_email_signal(text: str) -> dict[str, Any] | None:
    """Devuelve metadatos de repo/lane si el texto parece trabajo de código."""
    hay = (text or "").lower()
    if not hay.strip():
        return None
    if not any(marker in hay for marker in DEV_SIGNAL_MARKERS):
        return None
    gitlabish = any(
        m in hay
        for m in ("gitlab", "merge request", "merge_request", "gitlab.com", "gitlab-org")
    )
    if gitlabish:
        return {
            "related_project": "gitlab-org-gitlab",
            "repo": GITLAB_UPSTREAM_REPO,
            "execution_lane": "local_execution",
            "task_class": "code_change",
            "from_agent": "AG-25",
        }
    return {
        "related_project": "innerops-agentic-platform",
        "repo": INNEROS_REPO,
        "execution_lane": "local_execution",
        "task_class": "code_change",
        "from_agent": "AG-25",
    }


def _message_text(doc: dict[str, Any]) -> str:
    parts = [
        str(doc.get("subject") or ""),
        str(doc.get("from_addr") or ""),
        str(doc.get("body_text") or "")[:4000],
        str(doc.get("snippet") or "")[:4000],
        str(doc.get("view_url") or ""),
    ]
    review = doc.get("ralfia_review") or {}
    if isinstance(review, dict):
        parts.append(str(review.get("category") or ""))
        parts.append(str(review.get("document_type") or ""))
    return " ".join(parts)


def _promote_ops_task(task: dict[str, Any], binding: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return {"ok": False, "reason": "missing_task_id"}
    title = str(task.get("title") or "")
    clean_title = title
    if title.startswith("[Correo/"):
        subj = re.sub(r"^\[Correo/[^\]]+\]\s*", "", title).strip()
        clean_title = f"[DevMail] {subj[:120]}"
    tags = [str(t) for t in (task.get("tags") or []) if str(t).lower() not in {"email", "email_ops"}]
    if "email_dev_bridge" not in tags:
        tags.append("email_dev_bridge")
    patch: dict[str, Any] = {
        "title": clean_title,
        "related_project": binding["related_project"],
        "project_id": binding["related_project"],
        "repo": binding["repo"],
        "task_class": binding["task_class"],
        "execution_lane": binding["execution_lane"],
        "from_agent": binding.get("from_agent") or "AG-25",
        "source": "email_dev_bridge",
        "kind": "dev_email",
        "tags": tags,
        "coordination_bucket": None,
        "cleanup_bucket": None,
        "dev_swarm_retry_requested": True,
        "dev_swarm_last_skip_reason": None,
        "updated_at": _now(),
        "updated_by": "email_ag25_integration",
    }
    status = str(task.get("status") or "").lower()
    if status in {"queued", "blocked", "awaiting_approval"}:
        patch["status"] = "proposed"
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    payload = {**payload, "repo": binding["repo"], "related_project": binding["related_project"]}
    patch["payload"] = payload
    if dry_run:
        return {"ok": True, "dry_run": True, "task_id": task_id, "patch": patch}
    db = mongo_store.get_db()
    db[OPS_COL].update_one({"task_id": task_id}, {"$set": patch})
    return {"ok": True, "task_id": task_id, "promoted": True}


def promote_dev_email_ops(*, limit: int = 40, dry_run: bool = False) -> dict[str, Any]:
    """Promueve ops_tasks de correo con señales de desarrollo."""
    db = mongo_store.get_db()
    rows = list(
        db[OPS_COL]
        .find(
            {
                "status": {"$in": ["queued", "proposed", "blocked", "awaiting_approval"]},
                "$or": [
                    {"correlation_id": {"$regex": r"^email:"}},
                    {"title": {"$regex": r"^\[Correo/"}},
                    {"coordination_bucket": "email_ops_backlog"},
                ],
            },
            {"_id": 0},
        )
        .sort("updated_at", -1)
        .limit(max(5, min(limit, 200)))
    )
    promoted: list[dict[str, Any]] = []
    skipped: list[str] = []
    for task in rows:
        text = " ".join(
            [
                str(task.get("title") or ""),
                str(task.get("correlation_id") or ""),
                " ".join(str(x) for x in (task.get("checklist") or [])),
            ]
        )
        mail_id = None
        corr = str(task.get("correlation_id") or "")
        if corr.startswith("email:"):
            mail_id = corr.split(":", 1)[1]
        if mail_id:
            msg = db.email_messages.find_one({"mail_id": mail_id}, {"_id": 0}) or {}
            text = f"{text} {_message_text(msg)}"
        binding = classify_dev_email_signal(text)
        if not binding:
            skipped.append(str(task.get("task_id") or ""))
            continue
        out = _promote_ops_task(task, binding, dry_run=dry_run)
        promoted.append(out)
    return {
        "ok": True,
        "dry_run": dry_run,
        "reviewed": len(rows),
        "promoted_count": len(promoted),
        "promoted": promoted[:20],
        "skipped_task_ids": [x for x in skipped if x][:20],
    }


def ensure_dev_tasks_from_recent_mail(*, hours: int = 72, limit: int = 30, dry_run: bool = False) -> dict[str, Any]:
    """Crea ops_tasks proposed para correos recientes con señales dev (sin duplicar)."""
    from raphiia_openai import coordination_live

    db = mongo_store.get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
    rows = list(
        db.email_messages.find({"received_at": {"$gte": cutoff}}, {"_id": 0})
        .sort("received_at", -1)
        .limit(max(5, min(limit, 150)))
    )
    created: list[dict[str, Any]] = []
    for doc in rows:
        mail_id = str(doc.get("mail_id") or "").strip()
        if not mail_id:
            continue
        text = _message_text(doc)
        binding = classify_dev_email_signal(text)
        if not binding or "gitlab.com" not in text.lower():
            continue
        corr = f"email:{mail_id}"
        existing = db[OPS_COL].find_one(
            {"correlation_id": corr, "status": {"$nin": ["cancelled", "done", "completed"]}},
            {"task_id": 1},
        )
        if existing:
            continue
        subj = (doc.get("subject") or mail_id)[:100]
        title = f"[DevMail] {subj}"
        checklist = [
            f"Revisar correo dev: {subj}",
            f"mail_id: {mail_id}",
            f"repo: {binding['repo']}",
            "Ejecutar vía Dev Swarm / ContributorOps si aplica",
        ]
        if dry_run:
            created.append({"ok": True, "dry_run": True, "mail_id": mail_id, "title": title})
            continue
        task_result = coordination_live.create_ops_task(
            assignee="ralfia",
            title=title,
            checklist=checklist,
            priority="high" if "failed" in subj.lower() or "pipeline" in subj.lower() else "normal",
            from_agent=binding.get("from_agent") or "AG-25",
            correlation_id=corr,
            related_project=binding["related_project"],
            repo=binding["repo"],
            task_class=binding["task_class"],
            execution_lane=binding["execution_lane"],
            idempotency_key=f"devmail:{mail_id}",
        )
        if task_result.get("ok") and task_result.get("task_id"):
            db[OPS_COL].update_one(
                {"task_id": task_result["task_id"]},
                {
                    "$set": {
                        "source": "email_dev_bridge",
                        "kind": "dev_email",
                        "tags": ["email_dev_bridge"],
                        "updated_by": "email_ag25_integration",
                    }
                },
            )
        created.append({"mail_id": mail_id, **task_result})
    return {"ok": True, "dry_run": dry_run, "scanned": len(rows), "created": created[:20]}


def run_gmail_ag25_tick(*, cycle: int = 0, force_poll: bool = False) -> dict[str, Any]:
    """Un tick: poll IMAP (opcional), higiene ligera, puente dev."""
    enabled = os.environ.get("INNEROS_GMAIL_INTEGRATION", "1").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        return {"ok": True, "skipped": True, "reason": "INNEROS_GMAIL_INTEGRATION disabled"}

    poll_every = int(os.environ.get("AG25_EMAIL_POLL_EVERY_CYCLES", "2"))
    align_every = int(os.environ.get("AG25_EMAIL_ALIGN_EVERY_CYCLES", "24"))
    promote_every = int(os.environ.get("AG25_EMAIL_PROMOTE_EVERY_CYCLES", "1"))

    out: dict[str, Any] = {"ok": True, "cycle": cycle, "steps": {}}

    if force_poll or cycle % max(1, poll_every) == 0:
        try:
            from raphiia_openai.notifications import email_monitor

            out["steps"]["poll"] = email_monitor.trigger_email_poll()
        except Exception as exc:
            out["steps"]["poll"] = {"ok": False, "error": str(exc)[:200]}
        try:
            os.environ.setdefault("CONTRIBUTOROPS_INNEROS_BRIDGE", "1")
            from inneros_core_runtime import gitlab_contributorops_email_bridge as gl_email  # noqa: WPS433

            out["steps"]["contributorops_email"] = gl_email.run_after_email_poll(dry_run=False)
        except Exception as exc:
            out["steps"]["contributorops_email"] = {"ok": False, "error": str(exc)[:200]}

    if cycle % max(1, align_every) == 0:
        try:
            from raphiia_openai.notifications import email_ops_alignment

            out["steps"]["alignment"] = email_ops_alignment.run_email_ops_alignment(
                dry_run=False,
                hygiene_limit=120,
                reprocess_days=7,
                reprocess_limit=80,
            )
        except Exception as exc:
            out["steps"]["alignment"] = {"ok": False, "error": str(exc)[:200]}

    if cycle % max(1, promote_every) == 0:
        try:
            out["steps"]["promote_ops"] = promote_dev_email_ops(limit=40, dry_run=False)
            out["steps"]["ensure_from_mail"] = ensure_dev_tasks_from_recent_mail(
                hours=int(os.environ.get("AG25_EMAIL_DEV_LOOKBACK_HOURS", "72")),
                limit=25,
                dry_run=False,
            )
        except Exception as exc:
            out["steps"]["promote"] = {"ok": False, "error": str(exc)[:200]}

    accounts = {}
    try:
        from raphiia_openai.notifications import email_monitor

        accounts = email_monitor.list_monitored_accounts()
        out["accounts"] = accounts.get("count", 0)
    except Exception:
        pass

    _save_state({"last_tick": out, "last_cycle": cycle, "account_count": accounts.get("count")})
    try:
        mongo_store.log_coordination(
            agent="AG-25",
            summary=(
                f"Gmail AG-25 tick c={cycle} poll={bool(out['steps'].get('poll'))} "
                f"promoted={(out['steps'].get('promote_ops') or {}).get('promoted_count', 0)}"
            ),
            event="gmail_ag25_tick",
            project="ralfia-coordination",
            metadata={"steps_keys": list(out["steps"].keys()), "accounts": accounts.get("count")},
        )
    except Exception:
        pass
    return out
