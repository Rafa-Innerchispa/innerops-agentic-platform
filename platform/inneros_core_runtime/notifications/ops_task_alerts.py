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
NOTIFY_OPS_INTERNAL_BRIEF = os.getenv("NOTIFY_OPS_INTERNAL_CREATE", "0") == "1"  # reload via _internal_brief_enabled()
NOTIFY_VERIFICATION = os.getenv("NOTIFY_OPS_VERIFICATION", "1") == "1"

_STATE: dict[str, Any] = {"cooldowns": {}, "sent": []}


def _dedupe_key(kind: str, payload: str) -> str:
    return hashlib.sha256(f"{kind}:{payload}".encode()).hexdigest()[:16]


def _can_send(kind: str, key: str, *, force: bool = False) -> bool:
    if force:
        return True
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


def title_short(task: dict[str, Any]) -> str:
    return str(task.get("title") or "ops task")[:80]


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



def _notify_ops_auth_email_fallback(
    task: dict[str, Any],
    *,
    body: str,
    provider: str,
    tid: str,
) -> dict[str, Any]:
    """When Evolution/WhatsApp is down, reach owner via email (same CONFIRMAR/CANCELAR semantics)."""
    import os

    if os.getenv("NOTIFY_OPS_AUTH_EMAIL_FALLBACK", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"ok": False, "skipped": "email_fallback_disabled"}
    raw = (
        os.getenv("RALFIA_OPS_AUTH_EMAIL_TO")
        or os.getenv("INNEROS_ADMIN_EMAILS")
        or os.getenv("NOTIFY_EMAIL_TO")
        or ""
    ).strip()
    to_addr = raw.split(",")[0].strip() if raw else ""
    if not to_addr:
        return {"ok": False, "skipped": "no_owner_email_configured"}
    short = tid.replace("ops_", "")[:6]
    subject = f"[RalfIA OPS] Autorización {provider.upper()} · {short}"
    email_body = (
        f"{body}\n\n"
        f"---\n"
        f"WhatsApp no disponible; responde a este correo o usa MCP:\n"
        f"• CONFIRMAR {short}\n"
        f"• CANCELAR {short}\n"
        f'• cursor_authorize_ops_task(task_id="{tid}")\n'
    )
    from inneros_core_runtime.notifications.email_client import send_email

    sent = send_email(
        to_addr=to_addr,
        subject=subject,
        body=email_body,
        idempotency_key=f"ops_auth_email:{tid}",
        dedupe_window_seconds=3600,
    )
    return {"ok": bool(sent.get("ok")), "channel": "email", "email": sent, "task_id": tid}

def _internal_brief_enabled() -> bool:
    import os
    return os.getenv("NOTIFY_OPS_INTERNAL_CREATE", "0").strip().lower() in {"1", "true", "yes", "on"}


def notify_ops_owner_authorization_request(
    task: dict[str, Any],
    *,
    binding: dict[str, Any] | None = None,
    source_agent: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """WhatsApp al crear ops task: motivo externo vs interno y cómo autorizar."""
    if not NOTIFY_OPS_TASKS or not NOTIFY_OPS_CREATE_AUTH:
        return {"ok": False, "skipped": "notifications_disabled"}

    title = str(task.get("title") or "")
    lane = str(task.get("execution_lane") or "").strip().lower()
    if title.startswith("[Correo/") or lane == "email_intelligence":
        return {"ok": False, "skipped": "email_intelligence_no_ide_auth", "task_id": str(task.get("task_id") or "")}

    from inneros_core_runtime.execution_binding import (
        owner_execution_summary,
        requires_external_owner_authorization,
        resolve_execution_binding,
    )

    binding = binding or resolve_execution_binding(task)
    is_internal_carril = title.startswith("[Carril ") and "· interno" in title
    if is_internal_carril:
        return {"ok": False, "skipped": "internal_carril_no_owner_gate", "task_id": str(task.get("task_id") or "")}
    if not requires_external_owner_authorization(task, binding):
        if not is_internal_carril and not _internal_brief_enabled() and not NOTIFY_OPS_INTERNAL_BRIEF:
            return {"ok": False, "skipped": "internal_no_external_auth_gate"}
    summary = owner_execution_summary(task, binding)
    provider = str(summary.get("provider") or task.get("assignee") or "?")
    if summary.get("allowed_internal_runner") and not summary.get("requires_owner_authorization"):
        if not is_internal_carril and not _internal_brief_enabled() and not NOTIFY_OPS_INTERNAL_BRIEF:
            return {"ok": False, "skipped": "internal_runner_no_owner_gate"}
    if is_internal_carril:
        icon = "🏠"
        headline = title.split("]")[0].replace("[", "").strip()
    elif title.startswith("[Competencia/Externo"):
        icon = "🛂"
        headline = f"EXTERNO · {provider.upper()}"
    elif summary.get("allowed_internal_runner") and not summary.get("requires_owner_authorization"):
        icon = "⚙️"
        headline = "OPS interna (Dev Swarm/local)"
    else:
        icon = "🛂"
        headline = "OPS · autorización requerida"

    from_agent = (source_agent or task.get("from_agent") or "?").strip()
    model_line = f"\nModelo: {summary['preferred_model']}" if summary.get("preferred_model") else ""
    tid = str(task.get("task_id") or "")
    objective = str(task.get("objective") or task.get("title") or "")[:280]
    spends = (
        "Esta tarea *gasta créditos* del agente IDE al ejecutar."
        if summary.get("requires_owner_authorization") and not summary.get("allowed_internal_runner")
        else "Carril *interno* (no gasta Cursor/Codex/Antigravity)."
    )
    short = tid.replace("ops_", "")[:6]
    body = (
        f"{icon} *Autorización requerida* · {provider.upper()}\n"
        f"Referencia: `{tid}`\n"
        f"{objective[:140]}\n"
        f"{spends}\n\n"
        f"Usa los botones *Confirmar* / *Cancelar* si aparecen.\n"
        f"Si no ves botones, responde:\n"
        f"• *CONFIRMAR {short}*\n"
        f"• *CANCELAR {short}*"
    )
    key = _dedupe_key("owner_auth", tid)
    if not _can_send("owner_auth", tid, force=force):
        return {"ok": False, "skipped": "cooldown_or_dedupe", "task_id": tid}

    import os

    from inneros_core_runtime.notifications.ops_owner_delivery import deliver_ops_auth
    from raphiia_openai.notifications.evolution_client import send_alert_whatsapp, send_whatsapp_interactive
    from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending
    from inneros_core_runtime.notifications import telegram_client as tg

    owner_phone = (
        os.getenv("RALFIA_ALERTS_TO") or os.getenv("NOTIFY_WHATSAPP_TO") or ""
    ).strip()
    auth_ui = (os.getenv("NOTIFY_OPS_AUTH_UI") or "buttons").strip().lower()
    wa_channels = (os.getenv("NOTIFY_OPS_CHANNELS") or "whatsapp").lower()
    tg_only = tg.telegram_enabled() and tg.configured() and "whatsapp" not in wa_channels
    if tg_only:
        tg_result = deliver_ops_auth(body, task_id=tid, provider=provider)
        if tg_result.get("ok"):
            _mark_sent("owner_auth", tid)
            return {
                "ok": True,
                "result": tg_result,
                "task_id": tid,
                "summary": summary,
                "delivery_mode": "telegram_multichannel",
                "poll_message_id": "",
                "email_fallback": None,
            }
    poll_message_id = ""
    buttons = [
        {"id": f"ops.auth.yes.{tid}", "label": "Confirmar"},
        {"id": f"ops.auth.no.{tid}", "label": "Cancelar"},
    ]
    if auth_ui == "poll":
        from raphiia_openai.notifications.evolution_client import (
            OPS_AUTH_POLL_NO,
            OPS_AUTH_POLL_YES,
            send_alert_whatsapp_poll,
        )

        result = send_alert_whatsapp_poll(
            body,
            [OPS_AUTH_POLL_YES, OPS_AUTH_POLL_NO],
            number=owner_phone or None,
            selectable_count=1,
        )
        poll_message_id = str(result.get("poll_message_id") or "").strip()
        delivery_mode = "poll"
    else:
        result = send_whatsapp_interactive(
            body,
            buttons,
            number=owner_phone or None,
            footer="RalfIA · operaciones",
            fallback_text=None,
        )
        delivery_mode = "buttons_plus_text"
    if result.get("ok") and owner_phone:
        ops_pending.register_pending(
            phone=owner_phone,
            task_id=tid,
            provider=provider,
            poll_message_id=poll_message_id or None,
        )
    if not result.get("ok"):
        result = send_alert_whatsapp(body, prefix_node=True)
        delivery_mode = "text"
    email_fallback = None
    if not result.get("ok"):
        email_fallback = _notify_ops_auth_email_fallback(
            task, body=body, provider=provider, tid=tid
        )
        if email_fallback.get("ok"):
            result = {"ok": True, "status": "sent", "channel": "email_fallback", "email": email_fallback}
    if result.get("ok"):
        _mark_sent("owner_auth", tid)
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "task_id": tid,
        "summary": summary,
        "delivery_mode": delivery_mode,
        "poll_message_id": poll_message_id,
        "email_fallback": email_fallback,
    }


_AWAITING_CLAIM_STATUSES = frozenset(
    {
        "awaiting_cursor_claim",
        "awaiting_codex_claim",
        "awaiting_antigravity_claim",
        "awaiting_gemini_claim",
        "awaiting_chatgpt_claim",
        "awaiting_ide_claim",
    }
)


def notify_cursor_awaiting_claim(task: dict[str, Any], *, previous_status: str | None = None) -> dict[str, Any]:
    """Avisa al owner por WhatsApp cuando una ops task IDE espera claim (sin runner interno)."""
    if not NOTIFY_OPS_TASKS or not NOTIFY_CURSOR_CLAIM:
        return {"ok": False, "skipped": "notifications_disabled"}

    from inneros_core_runtime.execution_binding import requires_external_owner_authorization, resolve_execution_binding

    binding = resolve_execution_binding(task)
    if not requires_external_owner_authorization(task, binding):
        return {"ok": False, "skipped": "internal_task_no_ide_claim_gate"}

    status = str(task.get("status") or "").lower()
    if status not in _AWAITING_CLAIM_STATUSES:
        return {"ok": False, "skipped": f"status_not_awaiting:{status}"}

    prev = (previous_status or "").lower()
    if prev == status:
        return {"ok": False, "skipped": "no_status_change"}

    tid = str(task.get("task_id") or "")
    if owner_auth_notified(tid):
        return {"ok": False, "skipped": "already_notified_on_create", "task_id": tid}

    provider = str(task.get("preferred_provider") or task.get("assignee") or "cursor").lower()
    corr = str(task.get("correlation_id") or "").strip()
    from inneros_core_runtime import interactive_ops_runner as ior

    model = ior.pinned_model(provider) or "env"
    if provider == "codex" or status == "awaiting_codex_claim":
        hint = f"MCP codex_owner_order correlación {corr}" if corr else "codex_owner_order"
        title = "Codex OPS en espera"
        extra = "Owner: autoriza vía MCP/WhatsApp (gasta créditos Codex al ejecutar)."
    elif provider == "antigravity" or status == "awaiting_antigravity_claim":
        hint = f"MCP antigravity_owner_order correlación {corr}" if corr else "antigravity_owner_order"
        title = "Antigravity OPS en espera"
        extra = "Owner: autoriza vía MCP (gasta créditos Antigravity/Gemini al ejecutar)."
    elif provider == "gemini" or status == "awaiting_gemini_claim":
        hint = f"MCP gemini_owner_order correlación {corr}" if corr else "gemini_owner_order"
        title = "Gemini OPS en espera"
        extra = "Owner: autoriza vía MCP (gasta créditos Gemini al ejecutar)."
    else:
        hint = f"procede cursor {corr}" if corr else "procede cursor"
        title = "Cursor OPS en espera"
        extra = f"Owner: responde *{hint}* y luego *confirmar co_…* (gasta créditos Cursor al ejecutar)."
    body = (
        f"🖱️ RalfIA · {title}\n"
        f"{_format_task_line(task)}\n"
        f"Agente: {provider} · Modelo: {model}\n"
        f"{extra}\n"
        f"Puedes autorizar cuando quieras; la tarea espera (Temporal ~7 días).\n"
        f"{ralfia_time.format_log()}"
    )
    key = _dedupe_key("cursor_claim", f"{task.get('task_id')}:{status}")
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

    fin = ""
    if status == "completed":
        fin = "✅ TAREA TERMINADA\n"
    elif status in {"blocked", "failed"}:
        fin = "⚠️ TAREA BLOQUEADA\n" if status == "blocked" else "❌ TAREA FALLIDA\n"

    body = (
        f"{fin}🧠 RalfIA {icon} OPS {status.upper()}\n"
        f"{_format_task_line(task)}"
        f"{actor_line}{blocker_line}{extra}\n"
        f"{ralfia_time.format_log()}"
    )
    key = _dedupe_key("ops", f"{task.get('task_id')}:{status}:{prev}")
    if not _can_send("ops", key):
        return {"ok": False, "skipped": "cooldown_or_dedupe"}

    from inneros_core_runtime.notifications.ops_owner_delivery import deliver_text

    tid = str(task.get("task_id") or "")
    delivered = deliver_text(body, kind=f"ops_{status}", dedupe_key=tid or key)
    result = delivered.get("channels", {}).get(delivered.get("via", ""), delivered)
    if not delivered.get("ok"):
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
