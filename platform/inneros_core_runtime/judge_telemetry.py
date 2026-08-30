"""Real Judge Console telemetry and KPI backend.

Events here are persisted from actual backend calls. Simulated/degraded events
are allowed for transparency, but they can never count as verified PASS.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

COL_EVENTS = "inneros_judge_trace_events"
COL_RUNS = "inneros_judge_trace_runs"

REDACT_RE = re.compile(
    r"(dop_v1_[A-Za-z0-9]+|cfut_[A-Za-z0-9]+|glpat-[A-Za-z0-9_.-]+|github_pat_[A-Za-z0-9_]+|gh[opsu]_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+|Bearer\s+[A-Za-z0-9._-]+)",
    re.I,
)

EVENT_FIELDS = [
    "correlation_id",
    "run_id",
    "ts_start_ms",
    "ts_end_ms",
    "source",
    "target",
    "protocol",
    "agent_id",
    "model",
    "provider",
    "runtime",
    "node",
    "tool",
    "action",
    "latency_ms",
    "status",
    "verified",
    "simulated",
    "degraded",
    "error",
    "evidence_ref",
    "artifact_id",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _db():
    from raphiia_openai import mongo_store

    return mongo_store.get_db()


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return REDACT_RE.sub("[REDACTED]", value)[:4000]
    if isinstance(value, dict):
        return {str(k)[:120]: _clean(v) for k, v in value.items() if str(k).lower() not in {"token", "api_key", "password", "secret"}}
    if isinstance(value, list):
        return [_clean(v) for v in value[:50]]
    return value


def _run_id(correlation_id: str) -> str:
    cid = (correlation_id or "").strip() or f"judge-{_now_ms()}"
    digest = hashlib.sha256(cid.encode("utf-8")).hexdigest()[:12]
    return f"judge-{digest}"


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    if not event.get("correlation_id"):
        return {"ok": False, "error": "correlation_id_required"}
    if event.get("verified") and (event.get("simulated") or event.get("degraded")):
        return {"ok": False, "error": "simulated_or_degraded_cannot_be_verified"}
    if str(event.get("status") or "").upper() == "PASS" and not event.get("verified"):
        return {"ok": False, "error": "pass_requires_verified_true"}
    return {"ok": True}


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    start = int(event.get("ts_start_ms") or _now_ms())
    end = int(event.get("ts_end_ms") or start)
    normalized = {field: event.get(field) for field in EVENT_FIELDS}
    normalized.update(
        {
            "correlation_id": str(event.get("correlation_id") or "").strip(),
            "run_id": str(event.get("run_id") or _run_id(str(event.get("correlation_id") or ""))).strip(),
            "ts_start_ms": start,
            "ts_end_ms": end,
            "latency_ms": max(0, int(event.get("latency_ms") if event.get("latency_ms") is not None else end - start)),
            "source": str(event.get("source") or "backend").strip(),
            "target": str(event.get("target") or "judge_console").strip(),
            "protocol": str(event.get("protocol") or "internal").strip(),
            "status": str(event.get("status") or "OK").strip().upper(),
            "verified": bool(event.get("verified", False)),
            "simulated": bool(event.get("simulated", False)),
            "degraded": bool(event.get("degraded", False)),
            "payload": _clean(event.get("payload") or {}),
            "created_at": _now(),
            "schema": "judge_trace_event_v1",
        }
    )
    return normalized


def record_trace_event(event: dict[str, Any]) -> dict[str, Any]:
    doc = normalize_event(event)
    valid = validate_event(doc)
    if not valid.get("ok"):
        return valid
    db = _db()
    db[COL_EVENTS].insert_one(dict(doc))
    db[COL_RUNS].update_one(
        {"run_id": doc["run_id"]},
        {
            "$set": {"run_id": doc["run_id"], "correlation_id": doc["correlation_id"], "updated_at": _now()},
            "$setOnInsert": {"created_at": _now()},
            "$inc": {"event_count": 1},
        },
        upsert=True,
    )
    return {"ok": True, "event": {k: doc.get(k) for k in EVENT_FIELDS + ["schema", "created_at"]}}


def mark_not_observed(correlation_id: str, source: str, target: str, reason: str) -> dict[str, Any]:
    return record_trace_event(
        {
            "correlation_id": correlation_id,
            "source": source,
            "target": target,
            "protocol": "not_observed",
            "status": "NOT_OBSERVED",
            "verified": False,
            "simulated": False,
            "degraded": True,
            "error": reason,
        }
    )


def list_trace_events(correlation_id: str = "", run_id: str = "", limit: int = 50) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if correlation_id:
        query["correlation_id"] = correlation_id
    if run_id:
        query["run_id"] = run_id
    rows = list(_db()[COL_EVENTS].find(query, {"_id": 0}).sort("ts_start_ms", -1).limit(max(1, min(int(limit), 200))))
    return {"ok": True, "count": len(rows), "events": rows}


def trace_detail(run_id: str) -> dict[str, Any]:
    rid = (run_id or "").strip()
    if not rid:
        return {"ok": False, "error": "run_id_required"}
    run = _db()[COL_RUNS].find_one({"run_id": rid}, {"_id": 0}) or {}
    events = list_trace_events(run_id=rid, limit=200)
    return {"ok": bool(run or events.get("events")), "run": run, "events": events.get("events", [])}


def current_trace(limit: int = 20) -> dict[str, Any]:
    return list_trace_events(limit=limit)


def kpis(correlation_id: str = "", limit: int = 500) -> dict[str, Any]:
    events = list_trace_events(correlation_id=correlation_id, limit=limit).get("events", [])
    total = len(events)
    verified = [e for e in events if e.get("verified")]
    local = [e for e in events if str(e.get("node") or "").lower() in {"amd", "intel", "local", "192.168.1.5", "192.168.1.4"} or str(e.get("runtime") or "").startswith("local")]
    cloud = [e for e in events if str(e.get("provider") or "").lower() in {"gcp", "google", "cloud_run", "digitalocean"} or str(e.get("runtime") or "").startswith("cloud")]
    failures = [e for e in events if str(e.get("status") or "").upper() in {"FAIL", "ERROR"}]
    artifacts = sorted({e.get("artifact_id") for e in events if e.get("artifact_id")})
    latencies = [int(e.get("latency_ms") or 0) for e in events if e.get("latency_ms") is not None]
    return {
        "ok": True,
        "total_events": total,
        "verified_events": len(verified),
        "simulated_events": sum(1 for e in events if e.get("simulated")),
        "degraded_events": sum(1 for e in events if e.get("degraded")),
        "local_events": len(local),
        "cloud_events": len(cloud),
        "local_first_ratio": round(len(local) / total, 3) if total else 0.0,
        "failures": len(failures),
        "artifacts": artifacts,
        "models": sorted({str(e.get("model")) for e in events if e.get("model")}),
        "agents": sorted({str(e.get("agent_id")) for e in events if e.get("agent_id")}),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "hhr": {"verified": len(verified), "estimated": max(0, total - len(verified)), "policy": "verified excludes simulated/degraded"},
    }


def resource_telemetry() -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "generated_at": _now()}
    try:
        from raphiia_openai import resource_fabric

        out["resource_fabric"] = resource_fabric.resource_fabric_status(limit=20)
    except Exception as exc:
        out["resource_fabric"] = {"ok": False, "error": str(exc)}
    try:
        from raphiia_openai import dual_deployment

        out["dual_deployment"] = dual_deployment.dual_deployment_status(probe_http=True, include_cloud=True)
    except Exception as exc:
        out["dual_deployment"] = {"ok": False, "error": str(exc)}
    try:
        from raphiia_openai.agents import ag42_service_guardian as guardian

        out["guardian"] = guardian.run_service_guardian(notify=False)
    except Exception as exc:
        out["guardian"] = {"ok": False, "error": str(exc)}
    return out


def safe_judge_trigger(action: str, prompt: str = "", correlation_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    action_n = (action or "").strip().lower()
    allowed = {"verify_system", "ask_aria", "emergency_plan", "agent_collaboration", "local_ai_task"}
    cid = correlation_id or f"judge-trigger-{hashlib.sha256((action_n + prompt).encode()).hexdigest()[:12]}"
    if action_n not in allowed:
        return {"ok": False, "error": "judge_action_not_allowlisted", "allowed": sorted(allowed)}
    event = record_trace_event(
        {
            "correlation_id": cid,
            "source": "judge_console",
            "target": action_n,
            "protocol": "safe_judge_trigger",
            "tool": "safe_judge_trigger",
            "action": action_n,
            "status": "OK" if dry_run else "QUEUED",
            "verified": False,
            "simulated": bool(dry_run),
            "degraded": False,
            "payload": {"prompt": prompt[:1000], "dry_run": dry_run},
        }
    )
    return {"ok": event.get("ok"), "dry_run": dry_run, "correlation_id": cid, "event": event.get("event"), "policy": "bounded allowlist; paid cloud requires explicit approval"}
