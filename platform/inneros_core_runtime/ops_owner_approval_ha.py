"""Owner approval HA view/push: scope, NL budget, grants, cost observed vs estimate."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime import execution_binding as eb
from raphiia_openai import mongo_store, ralfia_time

COL_GRANTS = "ops_owner_approval_grants"
COL_EVENTS = "ops_owner_approval_events"

_UNKNOWN = object()


def _now() -> str:
    return ralfia_time.now_utc_iso()


def _grant_id(task_id: str, scope_key: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{scope_key}".encode("utf-8")).hexdigest()[:16]
    return f"grant_{digest}"


def _budget_field(value: Any) -> int | float | None:
    if value is None or value is _UNKNOWN:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().lower()
    if not text or text in {"unknown", "?", "n/a", "na", "null", "none"}:
        return None
    try:
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError):
        return None


def parse_natural_language_budget(text: str) -> dict[str, Any]:
    """Best-effort parse of owner NL budget hints; unknown fields stay null (never zero)."""
    blob = (text or "").strip()
    out: dict[str, Any] = {
        "provider": None,
        "model": None,
        "quote_usd_min": None,
        "quote_usd_max": None,
        "token_limit": None,
        "credit_limit": None,
        "usd_hard_limit": None,
        "expires_at": None,
        "raw_excerpt": blob[:500] if blob else "",
    }
    if not blob:
        return out
    prov = re.search(r"(?:provider|agente|agent)\s*[:=]\s*([a-z0-9_-]+)", blob, re.I)
    if prov:
        out["provider"] = eb.normalize_provider(prov.group(1))
    model = re.search(r"(?:model|modelo)\s*[:=]\s*([^\s,;]+)", blob, re.I)
    if model:
        out["model"] = model.group(1).strip()
    usd_range = re.search(
        r"(?:usd|presupuesto|budget)\s*[:=]?\s*\$?\s*([\d.]+)\s*(?:-|–|to|a)\s*\$?\s*([\d.]+)",
        blob,
        re.I,
    )
    if usd_range:
        out["quote_usd_min"] = _budget_field(usd_range.group(1))
        out["quote_usd_max"] = _budget_field(usd_range.group(2))
    elif re.search(r"(?:usd|presupuesto)\s*[:=]?\s*\$?\s*([\d.]+)", blob, re.I):
        single = re.search(r"(?:usd|presupuesto)\s*[:=]?\s*\$?\s*([\d.]+)", blob, re.I)
        if single:
            out["quote_usd_max"] = _budget_field(single.group(1))
    tok = re.search(r"(?:tokens?|token_limit)\s*[:=]\s*([\d,]+)", blob, re.I)
    if tok:
        out["token_limit"] = _budget_field(tok.group(1).replace(",", ""))
    cred = re.search(r"(?:credits?|créditos?)\s*[:=]\s*([\d.]+)", blob, re.I)
    if cred:
        out["credit_limit"] = _budget_field(cred.group(1))
    exp = re.search(r"(?:expires?|expira|vence)\s*[:=]\s*([^\n;]+)", blob, re.I)
    if exp:
        out["expires_at"] = exp.group(1).strip()[:64]
    return out


def _latest_grant(task_id: str) -> dict[str, Any] | None:
    db = mongo_store.get_db()
    return db[COL_GRANTS].find_one({"task_id": task_id, "status": "active"}, sort=[("created_at", -1)])


def _parse_utc_instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _journal_cost_observed(task: dict[str, Any]) -> dict[str, Any]:
    journal = task.get("model_execution_journal") if isinstance(task.get("model_execution_journal"), list) else []
    tokens_in = tokens_out = 0
    usd_observed: float | None = None
    credits_observed: float | None = None
    for row in journal:
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        tokens_in += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        tokens_out += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        if usage.get("usd") is not None:
            usd_observed = (usd_observed or 0.0) + float(usage["usd"])
        if usage.get("credits") is not None:
            credits_observed = (credits_observed or 0.0) + float(usage["credits"])
    total_tokens = tokens_in + tokens_out
    return {
        "journal_entries": len(journal),
        "tokens_input_observed": tokens_in or None,
        "tokens_output_observed": tokens_out or None,
        "tokens_total_observed": total_tokens or None,
        "usd_observed": usd_observed,
        "credits_observed": credits_observed,
    }


def _grant_durable_limits(grant: dict[str, Any]) -> dict[str, int | float | None]:
    return {
        "usd_limit": _budget_field(grant.get("usd_limit")),
        "token_limit": _budget_field(grant.get("token_limit")),
        "credit_limit": _budget_field(grant.get("credit_limit")),
    }


def _grant_has_durable_ceiling(grant: dict[str, Any]) -> bool:
    limits = _grant_durable_limits(grant)
    return any(limits[k] is not None for k in limits)


def _grant_expired(grant: dict[str, Any], *, now: datetime | None = None) -> bool:
    instant = _parse_utc_instant(grant.get("expires_at"))
    if instant is None:
        return False
    ref = now or datetime.now(timezone.utc)
    return instant <= ref


def _grant_scope_mismatch(task: dict[str, Any], grant: dict[str, Any], provider: str) -> str | None:
    bound_provider = str(grant.get("provider") or "").strip()
    if bound_provider and eb.normalize_provider(bound_provider) != eb.normalize_provider(provider):
        return "owner_grant_provider_mismatch"
    bound_model = str(grant.get("model") or "").strip()
    if bound_model:
        task_model = str(task.get("preferred_model") or task.get("model") or "").strip()
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        if payload.get("model"):
            task_model = str(payload.get("model"))
        if task_model and task_model.lower() != bound_model.lower():
            return "owner_grant_model_mismatch"
    return None


def _consumption_exceeds_grant(task: dict[str, Any], grant: dict[str, Any]) -> str | None:
    limits = _grant_durable_limits(grant)
    observed = _journal_cost_observed(task)
    journal_entries = int(observed.get("journal_entries") or 0)
    usd_limit = limits["usd_limit"]
    if usd_limit is not None:
        usd_obs = observed.get("usd_observed")
        if usd_obs is None:
            if journal_entries > 0:
                return "owner_grant_usd_consumption_unknown"
        elif float(usd_obs) > float(usd_limit):
            return "owner_grant_usd_exceeded"
    token_limit = limits["token_limit"]
    if token_limit is not None:
        total = observed.get("tokens_total_observed")
        if total is None:
            if journal_entries > 0:
                return "owner_grant_token_consumption_unknown"
        elif int(total) > int(token_limit):
            return "owner_grant_token_exceeded"
    credit_limit = limits["credit_limit"]
    if credit_limit is not None:
        credits = observed.get("credits_observed")
        if credits is None:
            if journal_entries > 0:
                return "owner_grant_credit_consumption_unknown"
        elif float(credits) > float(credit_limit):
            return "owner_grant_credit_exceeded"
    return None


def build_owner_approval_view(task_id: str) -> dict[str, Any]:
    tid = (task_id or "").strip()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": tid}
    binding = eb.resolve_execution_binding(task)
    summary = eb.owner_execution_summary(task, binding)
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    estimate = payload.get("budget_estimate") if isinstance(payload.get("budget_estimate"), dict) else {}
    nl = parse_natural_language_budget(str(task.get("objective") or "") + "\n" + str(payload.get("budget_nl") or ""))
    grant = _latest_grant(tid)
    observed = _journal_cost_observed(task)
    events = list(db[COL_EVENTS].find({"task_id": tid}, {"_id": 0}).sort("created_at", -1).limit(20))
    repo = str(task.get("repo") or "").strip()
    deep_link = f"https://github.com/{repo}/issues" if repo else None
    task_deep_link = f"https://github.com/{repo}/blob/main/platform/docs/ops" if repo else None
    summary_lines = [
        f"Task {tid} · status={task.get('status')}",
        f"Provider/model: {summary.get('provider')} / {summary.get('preferred_model') or task.get('preferred_model')}",
        f"Grant: {'active' if grant else 'missing'}",
    ]
    if grant:
        gl = _grant_durable_limits(grant)
        summary_lines.append(f"Limits USD/tokens/credits: {gl['usd_limit']}/{gl['token_limit']}/{gl['credit_limit']}")
    summary_lines.append(f"Observed USD/tokens: {observed.get('usd_observed')}/{observed.get('tokens_total_observed')}")
    return {
        "ok": True,
        "task_id": tid,
        "status": task.get("status"),
        "correlation_id": task.get("correlation_id"),
        "scope": {
            "title": task.get("title"),
            "objective_excerpt": str(task.get("objective") or "")[:800],
            "task_class": task.get("task_class"),
            "execution_lane": task.get("execution_lane"),
        },
        "provider_model": {
            "provider": summary.get("provider"),
            "preferred_model": summary.get("preferred_model") or task.get("preferred_model"),
            "requires_external_credit_authorization": summary.get("requires_external_credit_authorization"),
        },
        "budget": {
            "natural_language": nl,
            "estimate": {
                "usd_min": _budget_field(estimate.get("usd_min")),
                "usd_max": _budget_field(estimate.get("usd_max")),
                "tokens": _budget_field(estimate.get("tokens")),
                "credits": _budget_field(estimate.get("credits")),
            },
            "observed": observed,
        },
        "grant": grant,
        "owner_authorized_at": task.get("owner_authorized_at"),
        "deep_links": {"github_repo": deep_link, "ops_docs": task_deep_link, "task_id": tid},
        "owner_summary_nl": "\n".join(summary_lines),
        "event_history": events,
        "rejection_allowed": True,
    }


def record_owner_grant(
    task_id: str,
    *,
    owner_actor: str = "RAFAEL",
    channel: str = "ha_companion",
    usd_limit: float | None = None,
    token_limit: int | None = None,
    credit_limit: float | None = None,
    expires_at: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    scope_note: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}
    ikey = (idempotency_key or f"grant|{tid}|{owner_actor}|{channel}").strip()
    gid = _grant_id(tid, ikey)
    db = mongo_store.get_db()
    existing = db[COL_GRANTS].find_one({"grant_id": gid}, {"_id": 0})
    if existing:
        return {"ok": True, "duplicate": True, "grant_id": gid, "grant": existing}
    limits = {
        "usd_limit": _budget_field(usd_limit),
        "token_limit": _budget_field(token_limit),
        "credit_limit": _budget_field(credit_limit),
    }
    if not any(limits[k] is not None for k in limits):
        return {"ok": False, "error": "owner_grant_limits_required", "task_id": tid}
    exp_instant = _parse_utc_instant(expires_at)
    if expires_at and exp_instant is None:
        return {"ok": False, "error": "owner_grant_expires_at_invalid", "task_id": tid}
    now = _now()
    doc = {
        "grant_id": gid,
        "task_id": tid,
        "status": "active",
        "owner_actor": owner_actor,
        "channel": channel,
        "usd_limit": limits["usd_limit"],
        "token_limit": limits["token_limit"],
        "credit_limit": limits["credit_limit"],
        "provider": eb.normalize_provider(provider) if provider else None,
        "model": (model or "").strip() or None,
        "expires_at": exp_instant.isoformat() if exp_instant else None,
        "scope_note": (scope_note or "")[:1000],
        "idempotency_key": ikey,
        "created_at": now,
        "updated_at": now,
    }
    db[COL_GRANTS].insert_one(doc)
    db[COL_EVENTS].insert_one(
        {
            "event_id": f"evt_{gid}",
            "task_id": tid,
            "type": "grant_recorded",
            "actor": owner_actor,
            "channel": channel,
            "payload": {k: doc[k] for k in ("usd_limit", "token_limit", "credit_limit", "expires_at", "provider", "model")},
            "created_at": now,
        }
    )
    return {"ok": True, "grant_id": gid, "grant": doc}


def reject_owner_scope(
    task_id: str,
    *,
    owner_actor: str = "RAFAEL",
    reason: str = "",
) -> dict[str, Any]:
    tid = (task_id or "").strip()
    now = _now()
    db = mongo_store.get_db()
    db[COL_GRANTS].update_many({"task_id": tid, "status": "active"}, {"$set": {"status": "rejected", "updated_at": now}})
    db[COL_EVENTS].insert_one(
        {
            "event_id": f"evt_reject_{hashlib.sha256((tid + now).encode()).hexdigest()[:12]}",
            "task_id": tid,
            "type": "scope_rejected",
            "actor": owner_actor,
            "reason": (reason or "")[:500],
            "created_at": now,
        }
    )
    return {"ok": True, "task_id": tid, "status": "rejected"}


def paid_execution_allowed(task_id: str, *, provider: str = "") -> dict[str, Any]:
    """Fail-closed: paid provider CLI requires durable owner grant + authorization timestamp."""
    tid = (task_id or "").strip()
    db = mongo_store.get_db()
    task = db[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0})
    if not task:
        return {"allowed": False, "error": "task_not_found", "task_id": tid}
    prov = eb.normalize_provider(provider or task.get("assignee") or task.get("preferred_provider"))
    if prov not in eb.EXTERNAL_SPEND_IDE_PROVIDERS:
        return {"allowed": True, "reason": "non_external_spend_provider", "provider": prov}
    if not task.get("owner_authorized_at"):
        return {"allowed": False, "error": "owner_authorization_not_recorded", "task_id": tid}
    grant = _latest_grant(tid)
    if not grant:
        return {
            "allowed": False,
            "error": "owner_budget_grant_required",
            "task_id": tid,
            "hint": "record_owner_grant via HA Companion before paid model execution",
        }
    if not _grant_has_durable_ceiling(grant):
        return {
            "allowed": False,
            "error": "owner_grant_limits_required",
            "task_id": tid,
            "grant_id": grant.get("grant_id"),
        }
    if _grant_expired(grant):
        return {"allowed": False, "error": "owner_grant_expired", "grant_id": grant.get("grant_id")}
    scope_err = _grant_scope_mismatch(task, grant, prov)
    if scope_err:
        return {"allowed": False, "error": scope_err, "grant_id": grant.get("grant_id"), "provider": prov}
    over = _consumption_exceeds_grant(task, grant)
    if over:
        return {"allowed": False, "error": over, "grant_id": grant.get("grant_id")}
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    budget_est = payload.get("budget_estimate") if isinstance(payload.get("budget_estimate"), dict) else {}
    est_usd = _budget_field(budget_est.get("usd_max"))
    if est_usd is None:
        est_usd = _budget_field(budget_est.get("usd_min"))
    if est_usd == 0:
        return {
            "allowed": False,
            "error": "owner_budget_estimate_zero_not_verified",
            "task_id": tid,
            "grant_id": grant.get("grant_id"),
        }
    return {"allowed": True, "grant_id": grant.get("grant_id"), "provider": prov}


def push_owner_approval_ha(task_id: str, *, actor: str = "inneros", notes: str = "") -> dict[str, Any]:
    view = build_owner_approval_view(task_id)
    if not view.get("ok"):
        return view
    from inneros_core_runtime import ops_owner_checkpoint as ocp

    budget = view.get("budget") or {}
    nl = budget.get("natural_language") or {}
    est = budget.get("estimate") or {}
    obs = budget.get("observed") or {}
    body_notes = (
        f"{notes}\n"
        f"{view.get('owner_summary_nl')}\n"
        f"NL budget: {nl}\n"
        f"Estimate USD/tokens/credits: {est}\n"
        f"Observed: {obs}\n"
        f"Grant: {view.get('grant')}\n"
        f"Deep link: {view.get('deep_links')}"
    ).strip()
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or {}
    return ocp.publish_ops_owner_checkpoint(
        task,
        phase="owner_approval_ha",
        evidence={"owner_approval_view": view},
        actor=actor,
        notes=body_notes[:3500],
    )


def verify_companion_receipt(receipt: dict[str, Any], *, expected_task_id: str) -> dict[str, Any]:
    tid = (expected_task_id or "").strip()
    if not isinstance(receipt, dict):
        return {"ok": False, "error": "receipt_required"}
    if str(receipt.get("task_id") or "") != tid:
        return {"ok": False, "error": "receipt_task_mismatch"}
    secret = os.getenv("INNEROS_HA_COMPANION_RECEIPT_SECRET", "").strip()
    sig = str(receipt.get("signature") or "").strip()
    if secret:
        payload = f"{tid}|{receipt.get('grant_id')}|{receipt.get('at')}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {"ok": False, "error": "receipt_signature_invalid"}
    return {"ok": True, "verified": True, "task_id": tid}
