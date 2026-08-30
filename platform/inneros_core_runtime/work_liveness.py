"""Work-progress liveness guard for the persistent Dev Swarm scheduler."""
from __future__ import annotations

from collections import Counter
from typing import Any

from raphiia_openai import coordination_live, dev_swarm_watchdog, mongo_store

STATE_KEY = "dev_swarm_work_liveness"
STALL_THRESHOLD = 2
BENIGN_NO_WORK_REASONS = {
    "non_development_ops_filtered",
    "repo_not_inferred",
    "needs_repo_metadata",
    "email_ops_backlog",
    "closed_watchdog_noise",
    "cancelled_stale_duplicate_shadow",
}



def evaluate_tick(*, available: int, selected: list[dict[str, Any]], skipped: list[dict[str, Any]], filtered: list[dict[str, Any]], dry_run: bool = False, db: Any | None = None) -> dict[str, Any]:
    database = db if db is not None else mongo_store.get_db()
    proposed_count = database[coordination_live.OPS_TASKS_COL].count_documents({"status": "proposed"})
    reason_counts = Counter(str(item.get("reason") or "unknown") for item in [*skipped, *filtered])
    selected_count = len(selected)
    actionable_skipped = [
        item for item in skipped
        if str(item.get("reason") or "unknown") not in BENIGN_NO_WORK_REASONS
    ]
    actionable_candidate_count = selected_count + len(actionable_skipped)
    stalled = bool(available > 0 and actionable_candidate_count > 0 and selected_count == 0)

    current = mongo_store.get_coordination_state(STATE_KEY)
    state = dict(current.get("state") or {}) if current.get("ok") else {}
    previous_streak = int(state.get("stall_streak") or 0)
    streak = previous_streak + 1 if stalled else 0
    patch = {
        "stall_streak": streak,
        "stalled": stalled,
        "available": int(available),
        "proposed_count": int(proposed_count),
        "selected_count": selected_count,
        "skip_reasons": dict(reason_counts.most_common(12)),
        "actionable_candidate_count": actionable_candidate_count,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, **patch, "remediation_required": streak >= STALL_THRESHOLD}

    mongo_store.upsert_coordination_state(key=STATE_KEY, data=patch)
    anomaly = None
    if stalled and streak >= STALL_THRESHOLD:
        anomaly = dev_swarm_watchdog.record_anomaly({
            "type": "eligible_work_zero_workers",
            "component": "dev_swarm_scheduler",
            "severity": "p0",
            "repo_expected": "Rafa-Innerchispa/innerops-agentic-platform",
            "profile": "python-tests",
            "correlation_id": "devswarm-work-liveness",
            "evidence": {
                "stall_streak": streak,
                "available": available,
                "proposed_count": proposed_count,
                "selected_count": selected_count,
                "actionable_candidate_count": actionable_candidate_count,
                "skip_reasons": dict(reason_counts.most_common(12)),
                "remediation": "AG-25 must reconcile routing/policy and re-dispatch locally before external escalation",
            },
        }, actor="AG-25")
    return {
        "ok": True,
        **patch,
        "remediation_required": streak >= STALL_THRESHOLD,
        "anomaly": anomaly,
    }
