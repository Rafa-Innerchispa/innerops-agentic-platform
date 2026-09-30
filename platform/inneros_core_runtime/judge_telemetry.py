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
    "event_type",
    "ts_start_ms",
    "ts_end_ms",
    "source_collection",
    "source_kind",
    "source",
    "target",
    "protocol",
    "agent_id",
    "message_id",
    "task_id",
    "a2a_task_id",
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
    source_collection = str(event.get("source_collection") or COL_EVENTS).strip()
    source_kind = str(event.get("source_kind") or "live_event").strip()
    normalized = {field: event.get(field) for field in EVENT_FIELDS}
    normalized.update(
        {
            "correlation_id": str(event.get("correlation_id") or "").strip(),
            "run_id": str(event.get("run_id") or _run_id(str(event.get("correlation_id") or ""))).strip(),
            "event_type": str(event.get("event_type") or event.get("action") or "trace_event").strip(),
            "ts_start_ms": start,
            "ts_end_ms": end,
            "latency_ms": max(0, int(event.get("latency_ms") if event.get("latency_ms") is not None else end - start)),
            "source_collection": source_collection,
            "source_kind": source_kind,
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
            "live_truth": {
                "source_collection": source_collection,
                "source_kind": source_kind,
                "persisted": True,
                "display_as_live": source_kind == "live_event",
                "historical": source_kind.startswith("historical"),
            },
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
    return {"ok": True, "event": {k: doc.get(k) for k in EVENT_FIELDS + ["schema", "created_at", "live_truth"]}}


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


JUDGE_ARIA_CONTEXT = """You are ARIA running inside InnerOS Judge Mode.

Context the judge can ask about:
- The page demonstrates InnerOS as one MCP/A2A ecosystem across local AMD and Intel servers plus governed cloud routes.
- Global Live Trace must show real persisted events only: correlation_id/run_id, source, target, protocol, agent, provider, model, runtime/node, tool/action, latency, status, and evidence/artifact.
- The seven guided checks cover A2A handshake, local AMD/vLLM inference, Intel/Ollama fallback, governed Google/Gemini or real Gemma route when deployed, ISKCON/module artifact flow, Resource Fabric/Guardian telemetry, and bounded cloud burst evidence.
- PASS requires real verified evidence. Simulated, degraded, queued, or unavailable routes must be named PARTIAL/NOT_READY.

Answer as a concise judge guide. If the user asks to run something, explain the backend action and preserve the correlation id. Do not use generic fallback text.
"""


def _prompt_requests_guided_run(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(
        token in text
        for token in (
            "run all seven",
            "run the seven",
            "run seven",
            "run test",
            "execute test",
            "ejecuta prueba",
            "corre prueba",
            "siete pruebas",
        )
    )


def _safe_node(provider_id: str | None, selected_node: str | None) -> str:
    if selected_node:
        return selected_node
    if provider_id == "local-amd-5":
        return "amd"
    if provider_id == "local-intel-4":
        return "intel"
    return "local"


def run_judge_aria(action: str, prompt: str, correlation_id: str) -> dict[str, Any]:
    """Execute the Judge ARIA backend path with local-first routing and trace."""

    cid = correlation_id or f"judge-aria-{hashlib.sha256((action + prompt).encode()).hexdigest()[:12]}"
    started = _now_ms()
    guided_result: dict[str, Any] | None = None
    if _prompt_requests_guided_run(prompt):
        try:
            from raphiia_openai import judge_multimodel_e2e

            guided_result = judge_multimodel_e2e.run_e2e(
                correlation_id=cid,
                allow_live_google=False,
                allow_writes=False,
                dispatch_a2a=True,
            )
        except Exception as exc:
            guided_result = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:600]}

    try:
        from raphiia_openai import local_model_router

        model_prompt = (
            f"{JUDGE_ARIA_CONTEXT}\n\n"
            f"Current action: {action}\n"
            f"Correlation ID: {cid}\n"
            f"Guided action result: {json.dumps(guided_result or {}, ensure_ascii=False, default=str)[:2500]}\n\n"
            f"Judge/user prompt: {prompt}\n"
        )
        model_result = local_model_router.run_local_model(
            task_type="routing" if action == "ask_aria" else "operational",
            prompt=model_prompt,
            max_tokens=450,
            temperature=0.2,
        )
    except Exception as exc:
        model_result = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:600]}

    ended = _now_ms()
    ok = bool(model_result.get("ok"))
    guided_status = str((guided_result or {}).get("overall_status") or "").upper()
    status = "PASS" if ok and guided_status not in {"PARTIAL", "NOT_READY", "FAIL"} else ("PARTIAL" if ok else "FAIL")
    provider_id = str(model_result.get("provider_id") or "local")
    event = record_trace_event(
        {
            "correlation_id": cid,
            "ts_start_ms": started,
            "ts_end_ms": ended,
            "source_collection": COL_EVENTS,
            "source_kind": "live_event",
            "source": "judge_console",
            "target": "local_model_router",
            "event_type": "judge_aria_inference",
            "protocol": "mcp.local_first.aria_v1",
            "agent_id": "aria_judge_backend",
            "model": model_result.get("selected_model") or model_result.get("model") or model_result.get("recommended_model"),
            "provider": provider_id,
            "runtime": model_result.get("runtime") or "local_model_router",
            "node": _safe_node(provider_id, model_result.get("selected_node")),
            "tool": "local_model_router.run_local_model",
            "action": action,
            "latency_ms": ended - started,
            "status": status,
            "verified": ok and status == "PASS",
            "simulated": False,
            "degraded": status != "PASS",
            "evidence_ref": f"mongo:{COL_EVENTS}:{cid}",
            "artifact_id": (guided_result or {}).get("evidence_path"),
            "payload": {
                "prompt": prompt[:1000],
                "answer": str(model_result.get("response") or "")[:2000],
                "guided_result": guided_result,
                "model_ok": ok,
            },
        }
    )
    return {
        "ok": ok,
        "correlation_id": cid,
        "status": status,
        "answer": model_result.get("response") or "",
        "model_result": model_result,
        "guided_result": guided_result,
        "event": event.get("event"),
        "policy": "local-first Judge ARIA; no canned fallback; no cloud spend without explicit gate",
    }


def safe_judge_trigger(action: str, prompt: str = "", correlation_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    action_n = (action or "").strip().lower()
    allowed = {"verify_system", "ask_aria", "emergency_plan", "agent_collaboration", "local_ai_task"}
    cid = correlation_id or f"judge-trigger-{hashlib.sha256((action_n + prompt).encode()).hexdigest()[:12]}"
    if action_n not in allowed:
        return {"ok": False, "error": "judge_action_not_allowlisted", "allowed": sorted(allowed)}
    if not dry_run and action_n in {"ask_aria", "local_ai_task", "agent_collaboration"}:
        return run_judge_aria(action_n, prompt, cid)
    event = record_trace_event(
        {
            "correlation_id": cid,
            "source_collection": COL_EVENTS,
            "source_kind": "live_event" if dry_run else "queued_event",
            "source": "judge_console",
            "target": action_n,
            "event_type": "judge_safe_trigger",
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
