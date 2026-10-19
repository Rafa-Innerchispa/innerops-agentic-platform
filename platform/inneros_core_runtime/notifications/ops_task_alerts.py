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


def _owner_auth_sent_mongo(task_id: str) -> bool:
    tid = (task_id or "").strip()
    if not tid:
        return False
    try:
        from raphiia_openai import mongo_store
        from inneros_core_runtime.coordination_live import OPS_TASKS_COL

        row = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"owner_whatsapp_auth_sent_at": 1})
        return bool(row and row.get("owner_whatsapp_auth_sent_at"))
    except Exception:
        return False


def _mark_owner_auth_sent_mongo(task_id: str) -> None:
    tid = (task_id or "").strip()
    if not tid:
        return
    try:
        from datetime import datetime, timezone
        from raphiia_openai import mongo_store
        from inneros_core_runtime.coordination_live import OPS_TASKS_COL

        mongo_store.get_db()[OPS_TASKS_COL].update_one(
            {"task_id": tid},
            {"$set": {"owner_whatsapp_auth_sent_at": datetime.now(timezone.utc).isoformat()}},
        )
    except Exception:
        pass


def owner_auth_notified(task_id: str) -> bool:
    tid = str(task_id or "")
    if tid in set(_STATE.get("sent", [])):
        return True
    return _owner_auth_sent_mongo(tid)



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


def _synthetic_ops_task_skip(task: dict[str, Any]) -> str | None:
    """Never ask the owner to authorize fixtures, canaries, or read-only smoke tasks."""
    source_message_id = str(task.get("source_message_id") or "").strip()
    if source_message_id.startswith("msg_test"):
        return "synthetic_source_message"
    if str(task.get("task_class") or "") == "coordination_canary":
        return "coordination_canary"
    lane = str(task.get("execution_lane") or "").lower()
    if lane == "canary":
        return "canary_lane"
    correlation = str(task.get("correlation_id") or "").lower()
    if correlation.startswith("fixture:") or "synthetic" in correlation:
        return "synthetic_correlation"
    if str(task.get("from_agent") or "") in {"ops_quad_lane_canary", "cursor_overnight"}:
        return "automated_smoke_producer"
    title = str(task.get("title") or "")
    if title.startswith("[quad-canary]") or title.startswith("[phase3]"):
        return "quad_canary_title"
    if str(task.get("task_class") or "") == "verification" and "solo lectura" in str(task.get("objective") or "").lower():
        return "read_only_verification"
    if task.get("suppress_owner_whatsapp_auth") is True:
        return "suppress_flag"
    return None


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

    try:
        from raphiia_openai.notifications.evolution_client import any_whatsapp_connected

        if not any_whatsapp_connected():
            return {
                "ok": False,
                "skipped": "evolution_whatsapp_down",
                "task_id": str(task.get("task_id") or ""),
            }
    except Exception:
        pass

    skip = _synthetic_ops_task_skip(task)
    if skip:
        return {"ok": False, "skipped": skip, "task_id": str(task.get("task_id") or "")}

    title = str(task.get("title") or "")
    lane = str(task.get("execution_lane") or "").strip().lower()
    if title.startswith("[Correo/") or lane == "email_intelligence":
        return {"ok": False, "skipped": "email_intelligence_no_ide_auth", "task_id": str(task.get("task_id") or "")}

    from inneros_core_runtime.execution_binding import (
        owner_execution_summary,
        resolve_execution_binding,
    )

    binding = binding or resolve_execution_binding(task)
    summary = owner_execution_summary(task, binding)
    alert_kind = str(summary.get("owner_whatsapp_alert_kind") or "internal_fix")
    is_internal_carril = title.startswith("[Carril ") and "· interno" in title
    provider = str(summary.get("provider") or task.get("assignee") or "?")
    if alert_kind == "internal_ready":
        if not is_internal_carril and not _internal_brief_enabled() and not NOTIFY_OPS_INTERNAL_BRIEF:
            return {"ok": False, "skipped": "internal_runner_no_owner_gate"}
    if is_internal_carril:
        icon = "🏠"
        headline = title.split("]")[0].replace("[", "").strip()
    elif title.startswith("[Competencia/Externo"):
        icon = "🛂"
        headline = f"EXTERNO · {provider.upper()}"
    elif alert_kind == "internal_ready":
        icon = "⚙️"
        headline = "OPS interna (Dev Swarm/local)"
    elif alert_kind == "internal_fix":
        icon = "🚧"
        headline = "OPS · carril interno bloqueado (contrato)"
    else:
        icon = "🛂"
        headline = "OPS · autorización requerida"

    tid = str(task.get("task_id") or "")
    objective = str(task.get("objective") or task.get("title") or "")[:280]
    why = str(summary.get("why_not_internal") or "")[:320]
    action = str(summary.get("owner_action_hint") or "")[:240]
    internal_alt = str(summary.get("internal_alternative") or "")[:240]
    if alert_kind == "external_spend":
        spends = "Esta tarea *gasta créditos* del agente IDE al ejecutar."
        detail = f"\nPor qué no runner interno: {why}\n{action}\n{internal_alt}"
    elif alert_kind == "internal_fix":
        spends = "Bloqueo de *ruta interna*; no es autorización de consumo externo ni gasto de créditos IDE."
        detail = f"\nPor qué no runner interno: {why}\n{internal_alt}\nAcción: registra `repo` owner/repo y reintenta."
    else:
        spends = "Carril *interno* (no gasta Cursor/Codex/Antigravity)."
        detail = ""
    short = tid.replace("ops_", "")[:6]
    body = (
        f"{icon} *{headline}* · {provider.upper()}\n"
        f"Referencia: `{tid}`\n"
        f"{objective[:140]}\n"
        f"{spends}{detail}\n"
    )
    if alert_kind == "external_spend":
        body += (
            "\nUsa los botones *Confirmar* / *Cancelar* si aparecen.\n"
            "Si no ves botones, responde:\n"
            f"• *CONFIRMAR {short}*\n"
            f"• *CANCELAR {short}*"
        )
    key = _dedupe_key("owner_auth", tid)
    if not _can_send("owner_auth", tid, force=force):
        return {"ok": False, "skipped": "cooldown_or_dedupe", "task_id": tid}

    import os

    from raphiia_openai.notifications.evolution_client import send_alert_whatsapp, send_whatsapp_interactive

    if alert_kind != "external_spend":
        result = send_alert_whatsapp(body, prefix_node=True)
        if result.get("ok"):
            _mark_sent("owner_auth", tid)
        return {
            "ok": bool(result.get("ok")),
            "result": result,
            "task_id": tid,
            "summary": summary,
            "delivery_mode": "text_internal_fix" if alert_kind == "internal_fix" else "text_internal_brief",
            "poll_message_id": "",
            "email_fallback": None,
        }

    from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending

    owner_phone = (
        os.getenv("RALFIA_ALERTS_TO") or os.getenv("NOTIFY_WHATSAPP_TO") or ""
    ).strip()
    auth_ui = (os.getenv("NOTIFY_OPS_AUTH_UI") or "buttons").strip().lower()
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
        _mark_owner_auth_sent_mongo(tid)
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
