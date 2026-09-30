"""WhatsApp alerts for ops tasks and Dev Swarm worker outcomes."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from raphiia_openai import ralfia_time
from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
from raphiia_openai.notifications.settings import NOTIFY_COOLDOWN_SEC

NOTIFY_OPS_TASKS = os.getenv("NOTIFY_OPS_TASKS", "1") == "1"
TERMINAL_OPS = frozenset({"completed", "failed", "blocked", "partial", "cancelled", "superseded"})
NOTIFY_VERIFICATION = os.getenv("NOTIFY_OPS_VERIFICATION", "1") == "1"

_STATE: dict[str, Any] = {"cooldowns": {}, "sent": []}


def _dedupe_key(kind: str, payload: str) -> str:
    return hashlib.sha256(f"{kind}:{payload}".encode()).hexdigest()[:16]


def _can_send(kind: str, key: str) -> bool:
    now = time.time()
    cd = _STATE.setdefault("cooldowns", {})
    last = float(cd.get(f"{kind}:{key}", 0))
    if now - last < NOTIFY_COOLDOWN_SEC:
        return False
    if key in set(_STATE.get("sent", [])):
        return False
    return True


def _mark_sent(kind: str, key: str) -> None:
    _STATE.setdefault("cooldowns", {})[f"{kind}:{key}"] = time.time()
    sent = _STATE.setdefault("sent", [])
    sent.append(key)
    _STATE["sent"] = sent[-200:]


def _format_task_line(task: dict[str, Any]) -> str:
    tid = str(task.get("task_id") or "?")
    title = str(task.get("title") or "")[:90]
    assignee = str(task.get("assignee") or "?")
    owner = str(task.get("owner") or "?")
    repo = str(task.get("related_project") or task.get("repo") or "")
    repo_line = f"\nRepo: {repo}" if repo else ""
    return f"{tid}\n{title}\nOwner: {owner} · Assignee: {assignee}{repo_line}"


def notify_ops_transition(
    task: dict[str, Any],
    *,
    previous_status: str | None = None,
    actor: str | None = None,
    blocker: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send WhatsApp when an ops task reaches a terminal or verification state."""
    if not NOTIFY_OPS_TASKS:
        return {"ok": False, "skipped": "NOTIFY_OPS_TASKS=0"}

    status = str(task.get("status") or "").lower()
    notify = status in TERMINAL_OPS or (status == "verification" and NOTIFY_VERIFICATION)
    if not notify:
        return {"ok": False, "skipped": f"status_not_notifiable:{status}"}

    prev = (previous_status or "").lower()
    if prev == status:
        return {"ok": False, "skipped": "no_status_change"}

    icon = {"completed": "✅", "verification": "🔍", "partial": "🟡", "failed": "❌", "blocked": "⛔"}.get(
        status, "ℹ️"
    )
    actor_line = f"\nActor: {actor}" if actor else ""
    blocker_line = f"\nBlocker: {str(blocker or task.get('blocker') or '')[:400]}" if status in {"blocked", "failed"} else ""
    ev = evidence or {}
    sha = str(ev.get("commit_sha") or ev.get("sha") or "")[:12]
    branch = str(ev.get("branch") or "")
    extra = ""
    if sha or branch:
        extra = f"\nBranch: {branch or '?'} · SHA: {sha or '?'}"

    body = (
        f"🧠 RalfIA {icon} OPS {status.upper()}\n"
        f"{_format_task_line(task)}"
        f"{actor_line}{blocker_line}{extra}\n"
        f"{ralfia_time.format_log()}"
    )
    key = _dedupe_key("ops", f"{task.get('task_id')}:{status}:{prev}")
    if not _can_send("ops", key):
        return {"ok": False, "skipped": "cooldown_or_dedupe"}

    result = send_alert_whatsapp(body, prefix_node=False)
    if result.get("ok"):
        _mark_sent("ops", key)
    return {"ok": bool(result.get("ok")), "result": result, "task_id": task.get("task_id"), "status": status}


def notify_dev_swarm_outcome(
    *,
    task_id: str,
    repo: str,
    branch: str,
    outcome: str,
    blocker: str | None = None,
    files_touched: list[str] | None = None,
    commit_head: str | None = None,
) -> dict[str, Any]:
    """Send WhatsApp when a Dev Swarm worker finishes PASS/FAIL."""
    if not NOTIFY_OPS_TASKS:
        return {"ok": False, "skipped": "NOTIFY_OPS_TASKS=0"}

    outcome_u = (outcome or "FAIL").upper()
    icon = "✅" if outcome_u == "PASS" else "⛔"
    files = ", ".join((files_touched or [])[:5])
    files_line = f"\nFiles: {files}" if files else ""
    blocker_line = f"\nBlocker: {str(blocker or '')[:400]}" if outcome_u != "PASS" else ""
    sha_line = f"\nSHA: {commit_head}" if commit_head else ""

    body = (
        f"🧠 RalfIA {icon} Dev Swarm {outcome_u}\n"
        f"Ops: {task_id}\n"
        f"Repo: {repo}\n"
        f"Branch: {branch}{sha_line}{files_line}{blocker_line}\n"
        f"{ralfia_time.format_log()}"
    )
    key = _dedupe_key("swarm", f"{task_id}:{outcome_u}:{branch}")
    if not _can_send("swarm", key):
        return {"ok": False, "skipped": "cooldown_or_dedupe"}

    result = send_alert_whatsapp(body, prefix_node=False)
    if result.get("ok"):
        _mark_sent("swarm", key)
    return {"ok": bool(result.get("ok")), "result": result, "task_id": task_id, "outcome": outcome_u}
