"""Persistent anomaly loop for the Dev Swarm control plane."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import coordination_live, mongo_store

ANOMALIES_COL = "ralfia_dev_swarm_anomalies"
OPS_TASKS_COL = coordination_live.OPS_TASKS_COL
OPEN_STATUSES = {"open", "regression_reopened"}
TERMINAL_TASK_STATUSES = {"completed", "cancelled", "failed", "superseded"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db(db: Any | None = None) -> Any:
    return db if db is not None else mongo_store.get_db()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: Any, limit: int = 4000) -> Any:
    try:
        text = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return value
    return {"truncated": True, "text": text[:limit]}


def normalize_anomaly(anomaly: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in ("type", "component") if not _clean(anomaly.get(field))]
    if missing:
        raise ValueError(f"missing_required_fields:{','.join(missing)}")
    normalized = {
        "type": _clean(anomaly.get("type")),
        "component": _clean(anomaly.get("component")),
        "severity": _clean(anomaly.get("severity")) or "high",
        "task_id": _clean(anomaly.get("task_id")),
        "run_id": _clean(anomaly.get("run_id")),
        "repo_expected": _clean(anomaly.get("repo_expected")),
        "repo_actual": _clean(anomaly.get("repo_actual")),
        "base_ref_expected": _clean(anomaly.get("base_ref_expected")),
        "base_ref_actual": _clean(anomaly.get("base_ref_actual")),
        "package_root": _clean(anomaly.get("package_root") or anomaly.get("product_root")),
        "worker": _clean(anomaly.get("worker")),
        "node": _clean(anomaly.get("node")),
        "model": _clean(anomaly.get("model")),
        "profile": _clean(anomaly.get("profile") or anomaly.get("execution_profile")),
        "evidence": _clip(anomaly.get("evidence") or {}),
        "source": _clean(anomaly.get("source")) or "dev_swarm_watchdog",
    }
    if _clean(anomaly.get("correlation_id")):
        normalized["correlation_id"] = _clean(anomaly.get("correlation_id"))
    return normalized


def fingerprint_anomaly(anomaly: dict[str, Any]) -> str:
    normalized = normalize_anomaly(anomaly)
    material = {
        key: normalized.get(key)
        for key in (
            "type",
            "component",
            "task_id",
            "repo_expected",
            "repo_actual",
            "base_ref_expected",
            "base_ref_actual",
            "package_root",
            "profile",
        )
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _title_for(anomaly: dict[str, Any]) -> str:
    suffix = anomaly.get("task_id") or anomaly.get("repo_actual") or anomaly.get("repo_expected") or "control-plane"
    return f"[Watchdog] {anomaly['component']} {anomaly['type']} ({suffix})"


def _ensure_repair_task(anomaly: dict[str, Any], *, fingerprint: str, repair_task_id: str = "", actor: str = "dev_swarm_watchdog", db: Any | None = None) -> dict[str, Any]:
    database = _db(db)
    now = _now()
    correlation_id = anomaly.get("correlation_id") or f"devswarm-anomaly-{fingerprint[:16]}"
    existing = database[OPS_TASKS_COL].find_one({"task_id": repair_task_id}, {"_id": 0}) if repair_task_id else None
    if not existing:
        existing = database[OPS_TASKS_COL].find_one(
            {"correlation_id": correlation_id, "assignee": "ralfia", "status": {"$nin": list(TERMINAL_TASK_STATUSES)}},
            {"_id": 0},
        )
    if existing:
        task_id = str(existing.get("task_id") or repair_task_id)
        database[OPS_TASKS_COL].update_one(
            {"task_id": task_id},
            {"$set": {"watchdog_fingerprint": fingerprint, "watchdog_last_seen": now, "watchdog_anomaly_type": anomaly["type"], "watchdog_component": anomaly["component"], "updated_at": now}},
        )
        return {"ok": True, "created": False, "task_id": task_id, "task": database[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0}) or existing, "correlation_id": correlation_id}
    if db is not None:
        task_id = f"ops_watchdog_{fingerprint[:12]}"
        doc = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "assignee": "ralfia",
            "from_agent": actor.upper(),
            "title": _title_for(anomaly),
            "priority": anomaly.get("severity") or "high",
            "status": "proposed",
            "created_at": now,
            "updated_at": now,
            "watchdog_fingerprint": fingerprint,
            "watchdog_last_seen": now,
            "watchdog_anomaly_type": anomaly["type"],
            "watchdog_component": anomaly["component"],
        }
        database[OPS_TASKS_COL].insert_one(doc)
        return {"ok": True, "created": True, "task_id": task_id, "task": doc, "correlation_id": correlation_id}
    created = coordination_live.create_ops_task(
        assignee="ralfia",
        title=_title_for(anomaly),
        checklist=[
            "Inspect the watchdog anomaly and identify the root cause.",
            "Apply a bounded local-first repair in the canonical runtime.",
            "Attach commit/branch, tests, verifier output and Integration Guardian result.",
            "Close the anomaly only after verification, and reopen as regression if it returns.",
        ],
        evidence_required=["status OK/PARTIAL/FAIL", "watchdog fingerprint and anomaly fields", "files/commit/branch changed", "test and verifier output", "rollback path"],
        priority=anomaly.get("severity") or "high",
        from_agent=actor,
        correlation_id=correlation_id,
    )
    if created.get("ok"):
        task_id = str(created.get("task_id") or (created.get("task") or {}).get("task_id"))
        if task_id:
            database[OPS_TASKS_COL].update_one(
                {"task_id": task_id},
                {"$set": {"watchdog_fingerprint": fingerprint, "watchdog_last_seen": now, "watchdog_anomaly_type": anomaly["type"], "watchdog_component": anomaly["component"]}},
            )
    return created


def record_anomaly(anomaly: dict[str, Any], *, repair_task_id: str = "", actor: str = "dev_swarm_watchdog", dry_run: bool = False, db: Any | None = None) -> dict[str, Any]:
    normalized = normalize_anomaly(anomaly)
    fingerprint = fingerprint_anomaly(normalized)
    now = _now()
    correlation_id = normalized.get("correlation_id") or f"devswarm-anomaly-{fingerprint[:16]}"
    normalized["correlation_id"] = correlation_id
    if dry_run:
        return {"ok": True, "dry_run": True, "fingerprint": fingerprint, "correlation_id": correlation_id, "anomaly": normalized}
    database = _db(db)
    existing = database[ANOMALIES_COL].find_one({"fingerprint": fingerprint}, {"_id": 0})
    status = "regression_reopened" if str((existing or {}).get("status") or "") in {"resolved", "closed"} else "open"
    database[ANOMALIES_COL].update_one(
        {"fingerprint": fingerprint},
        {
            "$setOnInsert": {"fingerprint": fingerprint, "first_seen": now, "created_at": now},
            "$set": {**normalized, "status": status, "last_seen": now, "updated_at": now},
            "$inc": {"recurrence_count": 1, "reopen_count": 1 if status == "regression_reopened" else 0},
            "$push": {"events": {"$each": [{"at": now, "actor": actor, "status": status, "evidence": normalized.get("evidence")}], "$slice": -20}},
        },
        upsert=True,
    )
    task = _ensure_repair_task(normalized, fingerprint=fingerprint, repair_task_id=repair_task_id, actor=actor, db=database)
    task_id = str(task.get("task_id") or "")
    if task_id:
        database[ANOMALIES_COL].update_one({"fingerprint": fingerprint}, {"$set": {"repair_task_id": task_id, "repair_correlation_id": task.get("correlation_id"), "updated_at": now}})
    doc = database[ANOMALIES_COL].find_one({"fingerprint": fingerprint}, {"_id": 0}) or {}
    return {"ok": True, "fingerprint": fingerprint, "status": doc.get("status"), "repair_task": task, "anomaly": doc}


def close_anomaly(fingerprint: str, *, repair_task_id: str = "", evidence: dict[str, Any] | None = None, actor: str = "dev_swarm_watchdog", dry_run: bool = False, db: Any | None = None) -> dict[str, Any]:
    fp = _clean(fingerprint)
    if not fp:
        return {"ok": False, "error": "fingerprint_required"}
    now = _now()
    if dry_run:
        return {"ok": True, "dry_run": True, "fingerprint": fp}
    database = _db(db)
    doc = database[ANOMALIES_COL].find_one({"fingerprint": fp}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "anomaly_not_found", "fingerprint": fp}
    task_id = repair_task_id or str(doc.get("repair_task_id") or "")
    repair_evidence = _clip(evidence or {})
    database[ANOMALIES_COL].update_one(
        {"fingerprint": fp},
        {"$set": {"status": "resolved", "resolved_at": now, "resolved_by": actor, "repair_task_id": task_id, "repair_evidence": repair_evidence, "updated_at": now}, "$push": {"events": {"$each": [{"at": now, "actor": actor, "status": "resolved", "evidence": repair_evidence}], "$slice": -20}}},
    )
    if task_id:
        database[OPS_TASKS_COL].update_one({"task_id": task_id}, {"$set": {"watchdog_last_resolution": repair_evidence, "watchdog_resolved_at": now, "updated_at": now}})
    return {"ok": True, "fingerprint": fp, "task_id": task_id, "status": "resolved"}


def canonicalize_duplicate_ops(*, correlation_id: str, canonical_task_id: str = "", duplicate_task_ids: list[str] | None = None, actor: str = "dev_swarm_watchdog", dry_run: bool = False, db: Any | None = None) -> dict[str, Any]:
    cid = _clean(correlation_id)
    if not cid:
        return {"ok": False, "error": "correlation_id_required"}
    database = _db(db)
    tasks = list(database[OPS_TASKS_COL].find({"correlation_id": cid}, {"_id": 0}))
    canonical = next((task for task in tasks if task.get("task_id") == canonical_task_id), None) if canonical_task_id else None
    canonical = canonical or (sorted(tasks, key=lambda task: str(task.get("created_at") or ""))[0] if tasks else None)
    if not canonical:
        return {"ok": False, "error": "canonical_task_not_found", "correlation_id": cid}
    canonical_id = str(canonical.get("task_id"))
    duplicate_ids = duplicate_task_ids or [str(task.get("task_id")) for task in tasks if task.get("task_id") != canonical_id]
    duplicate_ids = [task_id for task_id in duplicate_ids if task_id and task_id != canonical_id]
    if dry_run:
        return {"ok": True, "dry_run": True, "canonical_task_id": canonical_id, "duplicate_task_ids": duplicate_ids}
    now = _now()
    for task_id in duplicate_ids:
        database[OPS_TASKS_COL].update_one({"task_id": task_id}, {"$set": {"status": "superseded", "superseded_by": canonical_id, "superseded_at": now, "superseded_by_actor": actor, "updated_at": now}})
    database[OPS_TASKS_COL].update_one({"task_id": canonical_id}, {"$set": {"duplicate_task_ids": duplicate_ids, "dedupe_checked_at": now, "updated_at": now}})
    return {"ok": True, "canonical_task_id": canonical_id, "duplicate_task_ids": duplicate_ids, "count": len(duplicate_ids)}


def summary(limit: int = 20, *, db: Any | None = None) -> dict[str, Any]:
    database = _db(db)
    lim = max(1, min(int(limit or 20), 50))
    anomalies = list(database[ANOMALIES_COL].find({"status": {"$in": list(OPEN_STATUSES)}}, {"_id": 0}).sort("last_seen", -1).limit(lim))
    regressions = [row for row in anomalies if row.get("status") == "regression_reopened"]
    p0 = list(database[OPS_TASKS_COL].find({"priority": {"$in": ["p0", "critical", "high"]}, "status": {"$in": ["proposed", "accepted", "in_progress"]}}, {"_id": 0}).sort("updated_at", 1).limit(lim))
    return {"ok": True, "open_anomalies": anomalies, "open_anomaly_count": len(anomalies), "regression_count": len(regressions), "p0_without_terminal_state": p0, "next_action": "repair highest-severity open anomaly and close it with verifier evidence" if anomalies else "watchdog clear"}


def demo_closed_loop(*, dry_run: bool = True, db: Any | None = None) -> dict[str, Any]:
    anomaly = {"type": "synthetic_repo_routing_regression", "component": "dev_swarm_scheduler", "task_id": "synthetic_watchdog_e2e", "repo_expected": "Rafa-Innerchispa/innerops-agentic-platform", "repo_actual": "missing-project", "base_ref_expected": "canonical-main", "base_ref_actual": "main", "package_root": "platform", "worker": "synthetic-worker", "node": "amd", "model": "local-test", "profile": "inneros_platform", "severity": "high", "correlation_id": "devswarm-watchdog-synthetic-e2e", "evidence": {"reason": "synthetic closed-loop"}}
    first = record_anomaly(anomaly, actor="dev_swarm_watchdog_demo", dry_run=dry_run, db=db)
    if dry_run:
        return {"ok": True, "dry_run": True, "first": first}
    fp = str(first.get("fingerprint"))
    close = close_anomaly(fp, repair_task_id=str((first.get("repair_task") or {}).get("task_id") or ""), evidence={"verifier": "synthetic_pass", "tests": ["unit fake closed-loop"], "result": "closed"}, actor="dev_swarm_watchdog_demo", db=db)
    second = record_anomaly({**anomaly, "evidence": {"reason": "synthetic regression reinjected"}}, actor="dev_swarm_watchdog_demo", db=db)
    return {"ok": bool(first.get("ok") and close.get("ok") and second.get("ok")), "fingerprint": fp, "first_status": (first.get("anomaly") or {}).get("status"), "close_status": close.get("status"), "second_status": (second.get("anomaly") or {}).get("status"), "repair_task_id": (second.get("repair_task") or {}).get("task_id"), "deduplicated": (first.get("repair_task") or {}).get("task_id") == (second.get("repair_task") or {}).get("task_id")}
