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
NOTIFY_CURSOR_CLAIM = os.getenv("NOTIFY_CURSOR_AWAITING_CLAIM", "1") == "1"
NOTIFY_OPS_CREATE_AUTH = os.getenv("NOTIFY_OPS_CREATE_AUTHORIZATION", "1") == "1"
NOTIFY_OPS_INTERNAL_BRIEF = os.getenv("NOTIFY_OPS_INTERNAL_CREATE", "0") == "1"
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


def owner_auth_notified(task_id: str) -> bool:
    return str(task_id) in set(_STATE.get("sent", []))


def notify_ops_owner_authorization_request(
    task: dict[str, Any],
    *,
    binding: dict[str, Any] | None = None,
    source_agent: str = "",
) -> dict[str, Any]:
    """WhatsApp al crear ops task: motivo externo vs interno y cómo autorizar."""
    if not NOTIFY_OPS_TASKS or not NOTIFY_OPS_CREATE_AUTH:
        return {"ok": False, "skipped": "notifications_disabled"}

    from inneros_core_runtime.execution_binding import owner_execution_summary, resolve_execution_binding

    binding = binding or resolve_execution_binding(task)
    summary = owner_execution_summary(task, binding)
    if summary.get("allowed_internal_runner") and not summary.get("requires_owner_authorization"):
        if not NOTIFY_OPS_INTERNAL_BRIEF:
            return {"ok": False, "skipped": "internal_runner_no_owner_gate"}
    if summary.get("allowed_internal_runner") and not summary.get("requires_owner_authorization"):
        icon = "⚙️"
        headline = "OPS interna (Dev Swarm/local)"
    else:
        icon = "🛂"
        headline = "OPS · autorización requerida"

    from_agent = (source_agent or task.get("from_agent") or "?").strip()
    model_line = f"\nModelo: {summary['preferred_model']}" if summary.get("preferred_model") else ""
    body = (
        f"{icon} RalfIA · {headline}\n"
        f"Solicitado por: {from_agent}\n"
        f"{_format_task_line(task)}\n"
        f"Agente: {summary.get('provider')} · Carril: {summary.get('execution_lane')}{model_line}\n\n"
        f"*Por qué no runner interno:*\n{summary.get('why_not_internal')}\n\n"
        f"{summary.get('internal_alternative')}\n\n"
        f"*Tu acción:*\n{summary.get('owner_action_hint')}\n"
        f"{ralfia_time.format_log()}"
    )
    tid = str(task.get("task_id") or "")
    key = _dedupe_key("owner_auth", tid)
    if not _can_send("owner_auth", tid):
        return {"ok": False, "skipped": "cooldown_or_dedupe", "task_id": tid}

    result = send_alert_whatsapp(body, prefix_node=True)
    if result.get("ok"):
        _mark_sent("owner_auth", tid)
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "task_id": tid,
        "summary": summary,
    }


def notify_cursor_awaiting_claim(task: dict[str, Any], *, previous_status: str | None = None) -> dict[str, Any]:
    """Avisa al owner por WhatsApp cuando una ops task espera claim Cursor (sin runner interno)."""
    if not NOTIFY_OPS_TASKS or not NOTIFY_CURSOR_CLAIM:
        return {"ok": False, "skipped": "notifications_disabled"}

    status = str(task.get("status") or "").lower()
    if status not in {"awaiting_cursor_claim", "awaiting_codex_claim"}:
        return {"ok": False, "skipped": f"status_not_awaiting:{status}"}

    prev = (previous_status or "").lower()
    if prev == status:
        return {"ok": False, "skipped": "no_status_change"}

    tid = str(task.get("task_id") or "")
    if owner_auth_notified(tid):
        return {"ok": False, "skipped": "already_notified_on_create", "task_id": tid}

    provider = str(task.get("preferred_provider") or task.get("assignee") or "").lower()
    if provider and provider not in {"cursor", "codex"} and "cursor" not in provider:
        assignee = str(task.get("assignee") or "").lower()
        if assignee != "cursor":
            return {"ok": False, "skipped": "not_cursor_task"}

    corr = str(task.get("correlation_id") or "").strip()
    if status == "awaiting_codex_claim" or str(task.get("assignee") or "").lower() == "codex":
        hint = f"MCP codex_owner_order correlación {corr}" if corr else "codex_owner_order"
        title = "Codex OPS en espera"
    else:
        hint = f"procede cursor {corr}" if corr else "procede cursor"
        title = "Cursor OPS en espera"
    body = (
        f"🖱️ RalfIA · {title}\n"
        f"{_format_task_line(task)}\n"
        f"Modelo: composer-2.5-fast\n"
        f"Owner: responde *{hint}* y luego *confirmar co_…*\n"
        f"{ralfia_time.format_log()}"
    )
    key = _dedupe_key("cursor_claim", f"{task.get('task_id')}:awaiting_cursor_claim")
    if not _can_send("cursor_claim", key):
        return {"ok": False, "skipped": "cooldown_or_dedupe"}

    result = send_alert_whatsapp(body, prefix_node=True)
    if result.get("ok"):
        _mark_sent("cursor_claim", key)
    return {"ok": bool(result.get("ok")), "result": result, "task_id": task.get("task_id"), "status": status}


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
