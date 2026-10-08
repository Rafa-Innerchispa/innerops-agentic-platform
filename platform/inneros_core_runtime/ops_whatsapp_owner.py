"""WhatsApp owner: SI ops_xxx / NO ops_xxx — autorización clara para ops tasks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

AUTH_RE = re.compile(r"^(?:SI|SÍ|AUTORIZO|OK)\s+(?:ops[_\s-]*)?([a-f0-9]{8,12})\s*$", re.I)
DENY_RE = re.compile(r"^(?:NO|RECHAZO|CANCELAR)\s+(?:ops[_\s-]*)?([a-f0-9]{8,12})\s*$", re.I)
BUTTON_AUTH_RE = re.compile(r"^ops\.auth\.(yes|no)\.(ops_[a-f0-9]{12})$", re.I)
NUMERIC_AUTH_RE = re.compile(r"^[12]$")


def _resolve_task_id(fragment: str) -> str | None:
    frag = (fragment or "").strip().lower()
    if frag.startswith("ops_"):
        return frag
    from raphiia_openai import mongo_store
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    db = mongo_store.get_db()
    exact = f"ops_{frag}" if not frag.startswith("ops_") else frag
    if db[OPS_TASKS_COL].find_one({"task_id": exact}, {"task_id": 1}):
        return exact
    matches = list(
        db[OPS_TASKS_COL]
        .find({"task_id": {"$regex": f"{re.escape(frag)}$"}}, {"task_id": 1})
        .sort("updated_at", -1)
        .limit(5)
    )
    if len(matches) == 1:
        return str(matches[0]["task_id"])
    return None


def _git_head(path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "rev-parse failed")
    return proc.stdout.strip()


def _maybe_auto_complete_verification(provider: str, task: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any] | None:
    """Canary solo lectura: cierra con commit_sha del worktree (0 créditos LLM)."""
    objective = str(task.get("objective") or "").lower()
    if str(task.get("task_class") or "") != "verification" or "rev-parse" not in objective:
        return None
    wt = str(claim.get("worktree") or "").strip()
    if not wt:
        return None
    from inneros_core_runtime import interactive_ops_runner as ior

    sha = _git_head(wt)
    tok = str(claim.get("claim_token") or "")
    tid = str(task.get("task_id") or "")
    return ior.complete_ops_task(
        provider,
        tid,
        claim_token=tok,
        status="completed",
        evidence={"commit_sha": sha, "notes": "whatsapp SI → auto complete verification canary"},
    )


def handle_owner_reply(
    message: str,
    *,
    owner_actor: str = "RAFAEL",
    phone: str | None = None,
) -> dict[str, Any] | None:
    text = (message or "").strip()
    btn = BUTTON_AUTH_RE.match(text)
    if btn:
        text = f"{'SI' if btn.group(1).lower() == 'yes' else 'NO'} {btn.group(2)}"
    if NUMERIC_AUTH_RE.match(text) and phone:
        from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending

        pending = ops_pending.latest_pending(phone)
        if pending:
            tid = str(pending.get("task_id") or "")
            text = f"{'SI' if text == '1' else 'NO'} {tid}"
    deny = DENY_RE.match(text)
    if deny:
        tid = _resolve_task_id(deny.group(1)) or deny.group(1)
        from inneros_core_runtime import durable_coordination_spine
        from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending

        out = durable_coordination_spine.signal_task_workflow(tid, "cancel", "owner_rejected_whatsapp")
        ops_pending.clear_pending(tid)
        return {
            "ok": bool(out.get("ok")),
            "text": f"❌ Tarea {tid} rechazada/cancelada.",
            "task_id": tid,
            "action": "deny",
        }

    auth = AUTH_RE.match(text)
    if not auth:
        if re.fullmatch(r"^(?:SI|SÍ|OK)$", text, re.I):
            from raphiia_openai import mongo_store
            from inneros_core_runtime.coordination_live import OPS_TASKS_COL

            pending = list(
                mongo_store.get_db()[OPS_TASKS_COL]
                .find(
                    {
                        "status": {
                            "$regex": "^awaiting_",
                        },
                        "owner_authorized_at": {"$exists": False},
                    },
                    {"task_id": 1},
                )
                .sort("updated_at", -1)
                .limit(2)
            )
            if len(pending) == 1:
                tid = str(pending[0]["task_id"])
                text = f"SI {tid}"
                auth = AUTH_RE.match(text)
        if not auth:
            return None

    tid = _resolve_task_id(auth.group(1)) or auth.group(1)
    from raphiia_openai import mongo_store
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime import execution_binding as eb
    from inneros_core_runtime import interactive_ops_runner as ior
    from inneros_core_runtime.interactive_ops_orchestrator import owner_order_execute

    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "text": f"No encontré la tarea {tid}.", "task_id": tid, "action": "auth"}

    provider = eb.normalize_provider(task.get("preferred_provider") or task.get("assignee"))
    binding = eb.resolve_execution_binding(task)
    if binding.get("allowed") and provider in {"dev_swarm", "dev-swarm", "local"}:
        ior.authorize_ops_task(provider, tid, owner_actor=owner_actor, channel="whatsapp")
        try:
            from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending

            ops_pending.clear_pending(tid)
        except Exception:
            pass
        return {
            "ok": True,
            "text": f"✅ {tid} autorizada (carril interno). Temporal ejecuta sin IDE.",
            "task_id": tid,
            "action": "auth_internal",
        }

    out = owner_order_execute(
        provider,
        task_id=tid,
        owner_actor=owner_actor,
        channel="whatsapp",
        owner_approved=True,
    )
    claim = out.get("claim") or {}
    if not out.get("ok"):
        return {
            "ok": False,
            "text": f"❌ No pude autorizar/claim {tid} ({provider}): {out.get('error') or claim.get('error')}",
            "task_id": tid,
            "action": "auth",
            "details": out,
        }

    auto = _maybe_auto_complete_verification(provider, task, claim)
    lines = [
        f"✅ Autorizado · {provider} · {tid}",
        f"Modelo: {claim.get('pinned_model') or 'env'}",
    ]
    if claim.get("worktree"):
        lines.append(f"Worktree: …{str(claim.get('worktree'))[-48:]}")
    if auto and auto.get("ok"):
        lines.append("Cierre canary verification enviado (Temporal gate).")
    elif provider in {"cursor", "codex", "antigravity", "gemini"}:
        lines.append("Siguiente: ejecuta en el IDE y cierra con evidencia (o espera auto si canary).")
    try:
        from inneros_core_runtime import whatsapp_ops_auth_pending as ops_pending

        ops_pending.clear_pending(tid)
    except Exception:
        pass
    try:
        from inneros_core_runtime.notifications.ops_task_alerts import notify_ops_transition

        task2 = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or task
        notify_ops_transition(task2, previous_status=str(task.get("status") or ""), actor=owner_actor)
    except Exception:
        pass
    return {
        "ok": True,
        "text": "\n".join(lines),
        "task_id": tid,
        "action": "auth",
        "claim": claim,
        "auto_complete": auto,
    }
