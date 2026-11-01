#!/usr/bin/env python3
"""Limpia cola OPS sin quemar créditos: archiva ruido viejo, protege trabajo útil pendiente."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INTERACTIVE = frozenset({"cursor", "codex", "antigravity", "gemini", "chatgpt"})
PAID_IDE = frozenset({"cursor", "codex", "antigravity", "gemini"})
TERMINAL = frozenset({"completed", "done", "cancelled", "canceled", "superseded", "archived"})
STALE_TITLE = re.compile(
    r"cross-smoke|quad-canary|rev-parse|competencia/externo|cursor-ha-e2e|"
    r"integrator|CIERRE TOTAL|re-certific|P0 CURSOR CIERRE|autonomous repair|"
    r"GitLab \d+ review",
    re.I,
)
EMAIL_TITLE = re.compile(r"\[Correo/", re.I)
BENEFICIAL_TITLE = re.compile(
    r"HA Companion|WordPress Page Builder|vigilancia Gmail|Bellini|MergeTober|"
    r"QuoteOps|endpoint público|Notion|coordination|offline canary",
    re.I,
)
DEFAULT_PROTECT_TASK_IDS = frozenset({
    "ops_d7ac9d1e90ec",  # Codex HA Companion #227
    "ops_e8c6e290c53f",  # P1 Gmail vigilance
    "ops_446a47bf778d",  # WordPress fase 1 local
    "ops_16debf885fed",  # Bellini Kantech preflight read-only
    "ops_e022d663d70b",  # MergeTober preflight
    "ops_b0e5c11596e7",  # offline canary (already fenced)
})
INCIDENT_TASK_PREFIXES = ("ops_7039e9cc4f11", "ops_97310078a555", "ops_96a584f15485")


def _protect_ids() -> frozenset[str]:
    raw = (os.getenv("INNEROS_OPS_HYGIENE_PROTECT_TASK_IDS") or "").strip()
    extra = {x.strip() for x in raw.split(",") if x.strip()}
    return DEFAULT_PROTECT_TASK_IDS | extra


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _task_age_days(task: dict) -> float | None:
    for key in ("updated_at", "created_at"):
        ts = _parse_ts(task.get(key))
        if ts:
            return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    return None


def _is_protected(task: dict, *, protect: frozenset[str]) -> bool:
    tid = str(task.get("task_id") or "")
    if tid in protect or tid.startswith(INCIDENT_TASK_PREFIXES):
        return True
    title = str(task.get("title") or "")
    if BENEFICIAL_TITLE.search(title):
        return True
    if str(task.get("coordination_relevance") or "") == "keep":
        return True
    return False


def _classify(task: dict, *, protect: frozenset[str]) -> tuple[str, str]:
    """Return (action, reason) where action is keep|fence|supersede."""
    tid = str(task.get("task_id") or "")
    title = str(task.get("title") or "")
    status = str(task.get("status") or "").lower()
    assignee = str(task.get("assignee") or task.get("assigned_to") or "").lower()

    if _is_protected(task, protect=protect):
        return "keep", "beneficial_or_protected"

    if assignee in PAID_IDE and status not in TERMINAL:
        if task.get("execution_stop") or task.get("do_not_auto_dispatch"):
            return "keep", "paid_already_fenced"
        if status in {"verification", "failed", "blocked"} or STALE_TITLE.search(title):
            return "supersede", "stale_paid_ide"
        age = _task_age_days(task)
        if age is not None and age > 7 and status in {"in_progress", "claimed", "running"}:
            return "supersede", "stale_paid_in_progress"

    if EMAIL_TITLE.search(title) and (
        status.startswith("awaiting_") or status in {"queued", "proposed", "awaiting_cursor_claim"}
    ):
        return "fence", "email_must_not_auto_ide"

    if assignee == "chatgpt" and status in {"blocked", "failed", "verification"}:
        return "supersede", "stale_chatgpt_lane"

    if tid.startswith("canary_") or (title and STALE_TITLE.search(title)):
        return "supersede", "stale_canary_or_smoke"

    if status == "failed" and assignee in {"dev_swarm", "dev-swarm"} and not BENEFICIAL_TITLE.search(title):
        age = _task_age_days(task)
        if age is None or age > 3:
            return "fence", "failed_dev_swarm_no_auto_retry"

    if assignee in INTERACTIVE and status in {"blocked", "failed", "verification"}:
        return "supersede", "stale_interactive_non_terminal"

    return "keep", "no_hygiene_rule"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplicar cambios (default dry-run)")
    parser.add_argument("--max-age-days", type=float, default=14.0, help="Edad para in_progress paid stale")
    args = parser.parse_args()
    dry_run = not args.apply

    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from inneros_core_runtime import interactive_provider_lanes as ipl
    from raphiia_openai import mongo_store

    protect = _protect_ids()
    db = mongo_store.get_db()
    col = db[OPS_TASKS_COL]
    filt = {"status": {"$nin": sorted(TERMINAL)}}
    rows = list(col.find(filt, {"_id": 0}))

    archived: list[dict] = []
    fenced: list[dict] = []
    kept: list[dict] = []

    for task in rows:
        tid = str(task.get("task_id") or "")
        action, reason = _classify(task, protect=protect)
        title = str(task.get("title") or "")[:80]
        status = str(task.get("status") or "")

        if action == "keep":
            kept.append({"task_id": tid, "status": status, "title": title, "reason": reason})
            continue

        if action == "fence":
            updates = {
                "$set": {
                    "do_not_auto_dispatch": True,
                    "updated_at": _now(),
                    "coordination_relevance": "keep",
                    "hygiene_fenced_at": _now(),
                    "hygiene_fenced_reason": reason,
                },
                "$unset": {
                    "claim_token": "",
                    "headless_execution_started_at": "",
                    "provider_execution_started_at": "",
                },
                "$inc": {"revision": 1},
            }
            if not dry_run:
                col.update_one({"task_id": tid}, updates)
            fenced.append({"task_id": tid, "prior_status": status, "title": title, "reason": reason})
            continue

        updates = {
            "$set": {
                "status": "superseded",
                "superseded_at": _now(),
                "superseded_by": "ops_queue_hygiene_zero_pending",
                "superseded_reason": reason,
                "last_progress": "Superseded — cola limpiada sin ejecutar créditos IDE",
                "updated_at": _now(),
                "do_not_auto_dispatch": True,
            },
            "$unset": {
                "claim_token": "",
                "claimed_at": "",
                "claim_host": "",
                "headless_execution_started_at": "",
                "headless_execution_finished_at": "",
                "headless_execution_pid": "",
                "headless_execution_host": "",
                "provider_execution_started_at": "",
                "provider_execution_host": "",
                "provider_execution_finished_at": "",
                "lease_until": "",
            },
            "$inc": {"revision": 1},
        }
        if not dry_run:
            col.update_one({"task_id": tid}, updates)
        archived.append({"task_id": tid, "prior_status": status, "title": title, "reason": reason})

    lane_reconcile = ipl.reconcile_stale_provider_lanes(dry_run=dry_run)

    backlog_hygiene: dict = {"skipped": "run via inneros_coordination_cycle"}
    if not dry_run:
        from inneros_core_runtime import dev_swarm_scheduler as dss

        backlog_hygiene = dss.reconcile_coordination_backlog_hygiene(limit=400, dry_run=False)

    remaining_paid = col.count_documents(
        {"assignee": {"$in": sorted(PAID_IDE)}, "status": {"$nin": sorted(TERMINAL)}}
    )
    out = {
        "ok": True,
        "dry_run": dry_run,
        "archived_count": len(archived),
        "fenced_count": len(fenced),
        "kept_count": len(kept),
        "protected_task_ids": sorted(protect),
        "remaining_paid_ide_non_terminal": remaining_paid,
        "archived_sample": archived[:40],
        "fenced_sample": fenced[:40],
        "kept_beneficial_sample": [k for k in kept if k["reason"] == "beneficial_or_protected"][:25],
        "lane_reconcile": lane_reconcile,
        "backlog_hygiene": {
            k: backlog_hygiene.get(k)
            for k in ("ok", "reviewed", "action_count", "counts", "dry_run")
        },
    }
    evidence = ROOT.parent / "var" / "evidence" / "ops_queue_hygiene_zero_pending.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
