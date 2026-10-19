"""Human-readable task alias (human_task_id) for owner-facing coordination surfaces."""

from __future__ import annotations

import re
from typing import Any

from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from raphiia_openai import mongo_store

# Stable overrides for known business intents (correlation_id → alias).
CORRELATION_ALIAS_OVERRIDES: dict[str, str] = {
    "amd-ai-league-umbrella-20261019": "AMD-LEAGUE-WRAPUP",
    "r9700-rocm101-vllm-production-promotion-20261019": "AMD-ROCM101-PROMOTION",
    "joshua-second-brain-operative-p0-20261013": "JOSHUA-SECOND-BRAIN-P0",
}

ACTIVE_STATUSES = frozenset(
    {
        "queued",
        "waiting_for_binding",
        "waiting_for_model_binding",
        "awaiting_ide_claim",
        "awaiting_cursor_claim",
        "awaiting_codex_claim",
        "awaiting_antigravity_claim",
        "awaiting_gemini_claim",
        "proposed",
        "accepted",
        "claimed",
        "in_progress",
        "running",
        "verification",
        "worker_starting",
    }
)
TERMINAL_STATUSES = frozenset({"completed", "failed", "blocked", "cancelled", "superseded", "archived"})

_DATE_SUFFIX = re.compile(r"-?\d{8}$")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_STOPWORDS = frozenset({"the", "a", "an", "for", "and", "or", "de", "la", "el", "now", "p0", "p1"})


def normalize_human_task_id(value: str) -> str:
    raw = str(value or "").strip().upper()
    raw = _NON_ALNUM.sub("-", raw).strip("-")
    parts = [p for p in raw.split("-") if p]
    if not parts:
        return "OPS-TASK"
    compact = "-".join(parts[:6])
    return compact[:48]


def _title_action_tokens(title: str, *, max_parts: int = 2) -> list[str]:
    words = []
    for w in re.split(r"\s+", str(title or "").strip()):
        w = re.sub(r"[^A-Za-z0-9]", "", w)
        if len(w) < 3 or w.lower() in _STOPWORDS:
            continue
        words.append(w.upper())
        if len(words) >= max_parts:
            break
    return words


def generate_human_task_id(
    *,
    correlation_id: str | None = None,
    title: str | None = None,
    related_project: str | None = None,
    objective: str | None = None,
    explicit: str | None = None,
) -> str:
    if explicit and str(explicit).strip():
        return normalize_human_task_id(explicit)
    corr = str(correlation_id or "").strip().lower()
    if corr in CORRELATION_ALIAS_OVERRIDES:
        return CORRELATION_ALIAS_OVERRIDES[corr]
    tokens = [t for t in re.split(r"[-_\s]+", corr) if t and not _DATE_SUFFIX.search(t)]
    domain = (tokens[0] if tokens else "ops").upper()
    if domain in {"RAFA", "INNERCHISPA"} and len(tokens) > 1:
        domain = tokens[1].upper()
    mid = [t.upper() for t in tokens[1:4] if t.upper() not in {domain}]
    action = _title_action_tokens(title or objective or "")
    if not action and "umbrella" in corr:
        action = ["WRAPUP"]
    if "promotion" in corr or "promote" in str(title or "").lower():
        action = action or ["PROMOTION"]
    if "concurrency" in corr or "concurrency" in str(title or "").lower():
        action = action or ["CONCURRENCY"]
    body = mid + action
    if not body:
        body = _title_action_tokens(related_project or "", max_parts=2) or ["TASK"]
    return normalize_human_task_id("-".join([domain, *body[:4]]))


def _explicit_from_task_fields(task: dict[str, Any]) -> str | None:
    for key in ("human_task_id", "task_alias"):
        if task.get(key):
            return str(task[key])
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    for key in ("human_task_id", "task_alias"):
        if payload.get(key):
            return str(payload[key])
    return None


def _inherit_from_db(
    *,
    correlation_id: str | None,
    parent_task_id: str | None,
    superseded_task_id: str | None,
    related_ops_task_id: str | None,
) -> str | None:
    db = mongo_store.get_db()
    try:
        col = db[OPS_TASKS_COL]
    except KeyError:
        # Minimal/offline coordination stores may omit the optional historical
        # collection.  No alias can be inherited there; derive it from the
        # current task without losing normal OPS admission or Temporal linkage.
        return None
    for tid in (parent_task_id, superseded_task_id, related_ops_task_id):
        if not tid:
            continue
        row = col.find_one({"task_id": str(tid).strip()}, {"human_task_id": 1})
        if row and row.get("human_task_id"):
            return str(row["human_task_id"])
    corr = str(correlation_id or "").strip()
    if corr:
        row = col.find_one(
            {"correlation_id": corr, "human_task_id": {"$exists": True, "$ne": ""}},
            {"human_task_id": 1},
            sort=[("updated_at", -1)],
        )
        if row and row.get("human_task_id"):
            return str(row["human_task_id"])
    return None


def resolve_human_task_id_for_create(task: dict[str, Any]) -> str:
    explicit = _explicit_from_task_fields(task)
    if explicit:
        return normalize_human_task_id(explicit)
    inherited = _inherit_from_db(
        correlation_id=str(task.get("correlation_id") or ""),
        parent_task_id=str(task.get("parent_task_id") or task.get("parent_ops_task_id") or ""),
        superseded_task_id=str(task.get("supersedes_task_id") or task.get("supersedes") or ""),
        related_ops_task_id=str(task.get("related_ops_task_id") or task.get("existing_task_id") or ""),
    )
    if inherited:
        return normalize_human_task_id(inherited)
    return generate_human_task_id(
        correlation_id=str(task.get("correlation_id") or ""),
        title=str(task.get("title") or ""),
        related_project=str(task.get("related_project") or task.get("repo") or ""),
        objective=str(task.get("objective") or ""),
    )


def attach_human_task_id(doc: dict[str, Any]) -> dict[str, Any]:
    alias = resolve_human_task_id_for_create(doc)
    doc["human_task_id"] = alias
    doc["task_alias"] = alias  # legacy-friendly mirror
    attempts = list(doc.get("human_task_attempts") or [])
    tid = str(doc.get("task_id") or "")
    if tid and not any(a.get("task_id") == tid for a in attempts):
        attempts.append(
            {
                "task_id": tid,
                "assignee": doc.get("assignee"),
                "status": doc.get("status"),
                "created_at": doc.get("created_at"),
            }
        )
    doc["human_task_attempts"] = attempts
    return doc


def owner_surface(task: dict[str, Any], *, related: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    alias = str(task.get("human_task_id") or task.get("task_alias") or generate_human_task_id(
        correlation_id=str(task.get("correlation_id") or ""),
        title=str(task.get("title") or ""),
    ))
    siblings = related or []
    active = [t for t in siblings if str(t.get("status") or "").lower() in ACTIVE_STATUSES]
    historical = [t for t in siblings if t not in active]
    active_id = str((active[0] if active else task).get("task_id") or "")
    return {
        "human_task_id": alias,
        "title": task.get("title"),
        "status": task.get("status"),
        "assignee": task.get("assignee"),
        "active_ops_task_id": active_id or task.get("task_id"),
        "correlation_id": task.get("correlation_id"),
        "workflow_id": task.get("workflow_id"),
        "run_id": task.get("run_id"),
        "technical": {
            "task_id": task.get("task_id"),
            "parent_task_id": task.get("parent_task_id"),
            "prior_attempts": [
                {"task_id": t.get("task_id"), "status": t.get("status"), "assignee": t.get("assignee")}
                for t in historical
            ],
        },
    }


def format_list_line(task: dict[str, Any]) -> str:
    alias = str(task.get("human_task_id") or task.get("task_alias") or "?")
    status = str(task.get("status") or "?")
    assignee = str(task.get("assignee") or "?")
    tid = str(task.get("task_id") or "?")
    title = str(task.get("title") or "")[:80]
    return f"{alias} | {status} | {assignee} | {tid} | {title}"


def format_whatsapp_owner_body(
    *,
    task: dict[str, Any],
    headline: str,
    provider: str,
    objective: str,
    spends: str,
    detail: str,
    alert_kind: str,
    short_ops_suffix: str,
    related: list[dict[str, Any]] | None = None,
) -> str:
    alias = str(task.get("human_task_id") or task.get("task_alias") or generate_human_task_id(
        correlation_id=str(task.get("correlation_id") or ""),
        title=str(task.get("title") or ""),
    ))
    tid = str(task.get("task_id") or "")
    status = str(task.get("status") or "")
    siblings = related or []
    prior = [
        t.get("task_id")
        for t in siblings
        if str(t.get("task_id")) != tid and str(t.get("status") or "").lower() in TERMINAL_STATUSES | {"blocked"}
    ]
    lines = [
        f"[{alias}]",
        f"Estado: {status}",
        f"Agente: {provider.upper()}",
        f"Tarea: {objective[:140]}",
        f"OPS actual: {tid}",
    ]
    if task.get("parent_task_id"):
        lines.append(f"Parent: {task.get('parent_task_id')}")
    if task.get("run_id"):
        lines.append(f"Run: {str(task.get('run_id'))[:24]}…")
    if prior:
        lines.append(f"OPS anteriores: {', '.join(str(x) for x in prior[:4])}")
    if task.get("correlation_id"):
        lines.append(f"Correlation: {task.get('correlation_id')}")
    lines.append("")
    lines.append(f"{headline} · {provider.upper()}")
    lines.append(spends)
    if detail.strip():
        lines.append(detail.strip())
    if alert_kind == "external_spend":
        lines.append(
            "\nUsa los botones *Confirmar* / *Cancelar* si aparecen.\n"
            "Si no ves botones, responde:\n"
            f"• *CONFIRMAR {short_ops_suffix}*\n"
            f"• *CANCELAR {short_ops_suffix}*"
        )
    return "\n".join(lines)


def group_tasks_by_human_id(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        alias = str(task.get("human_task_id") or task.get("task_alias") or "")
        if not alias:
            alias = generate_human_task_id(
                correlation_id=str(task.get("correlation_id") or ""),
                title=str(task.get("title") or ""),
            )
        buckets.setdefault(alias, []).append(task)
    groups: list[dict[str, Any]] = []
    for alias, rows in buckets.items():
        rows_sorted = sorted(rows, key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
        active = [r for r in rows_sorted if str(r.get("status") or "").lower() in ACTIVE_STATUSES]
        primary = active[0] if active else rows_sorted[0]
        groups.append(
            {
                "human_task_id": alias,
                "active": owner_surface(primary, related=rows_sorted),
                "attempts": [
                    {
                        "task_id": r.get("task_id"),
                        "status": r.get("status"),
                        "assignee": r.get("assignee"),
                        "updated_at": r.get("updated_at"),
                    }
                    for r in rows_sorted
                ],
                "list_line": format_list_line(primary),
            }
        )
    groups.sort(key=lambda g: str((g.get("active") or {}).get("active_ops_task_id") or ""), reverse=True)
    return groups


def find_tasks_by_human_task_id(human_task_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    alias = normalize_human_task_id(human_task_id)
    db = mongo_store.get_db()
    return list(
        db[OPS_TASKS_COL]
        .find({"$or": [{"human_task_id": alias}, {"task_alias": alias}]}, {"_id": 0})
        .sort("updated_at", -1)
        .limit(max(1, min(limit, 100)))
    )


def backfill_task(task: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    doc = dict(task)
    alias = resolve_human_task_id_for_create(doc)
    update = {"human_task_id": alias, "task_alias": alias}
    if dry_run:
        return {"ok": True, "dry_run": True, "task_id": doc.get("task_id"), "human_task_id": alias}
    mongo_store.get_db()[OPS_TASKS_COL].update_one({"task_id": doc["task_id"]}, {"$set": update})
    return {"ok": True, "dry_run": False, "task_id": doc.get("task_id"), "human_task_id": alias}
