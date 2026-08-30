"""Persistent content/evidence source for the InnerOS Judge Console."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import digitalocean_amd_provider, judge_telemetry, local_model_router, mongo_store, resource_fabric

COLLECTION = "judge_console_content"
VERSION = "judge-console-content-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _freshness(source: str, evidence_ref: str | None = None) -> dict[str, Any]:
    return {"source": source, "evidence_ref": evidence_ref, "generated_at": _now(), "version": VERSION}


def _runtime_snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {"generated_at": _now()}
    for key, fn in (
        ("resource_fabric", lambda: resource_fabric.resource_fabric_status(limit=20)),
        ("local_models", local_model_router.local_model_health),
        ("judge_kpis", lambda: judge_telemetry.kpis(limit=200)),
        ("digitalocean", digitalocean_amd_provider.status),
    ):
        try:
            out[key] = fn()
        except Exception as exc:
            out[key] = {"ok": False, "error": str(exc)[:300]}
    return out


def model_routing_policy(task_class: str = "", project_id: str = "") -> dict[str, Any]:
    policy = {
        "policy_version": "inneros-model-routing-v1",
        "local_first": True,
        "audit_fields": ["selected_model", "provider_id", "runtime", "reason", "fallback_reason", "cost_policy", "approval_required"],
        "routes": [
            {"task_class": "google_reasoning_or_orchestration", "selected_model": "gemini-3.5-or-current-google-best", "provider_id": "google", "runtime": "external_google", "reason": "Use Google model/runtime only for Google-specific reasoning, ADK/Vertex/Cloud orchestration, or owner-approved external reasoning.", "cost_policy": "budget_governed"},
            {"task_class": "bounded_function_intent", "selected_model": "functiongemma-or-local-classifier", "provider_id": "local-intel-4", "runtime": "local_classifier", "reason": "Small bounded routing/classification should avoid expensive models.", "cost_policy": "local_first"},
            {"task_class": "coding", "selected_model": "qwen3-coder-r9700-or-configured-vllm-default", "provider_id": "local-amd-5", "runtime": "local_vllm", "reason": "Heavy local coding and agent work should use AMD/vLLM before cloud burst.", "cost_policy": "local_first"},
            {"task_class": "light_ops", "selected_model": "configured-intel-ollama-light-model", "provider_id": "local-intel-4", "runtime": "local_model", "reason": "Light summaries, extraction and ops should stay on Intel.", "cost_policy": "local_first"},
            {"task_class": "stt_tts", "selected_model": "lemonade-when-live", "provider_id": "lemonade", "runtime": "local_voice", "reason": "Speech endpoints are used only after health/model probes show LIVE.", "cost_policy": "local_first"},
            {"task_class": "cloud_burst_gpu", "selected_model": "mi325x-vllm-explicit-burst", "provider_id": "digitalocean-amd-cloud", "runtime": "ephemeral_cloud_gpu", "reason": "Only for explicit large workloads/demos that exceed local GPU capacity.", "cost_policy": "explicit_approval_required"},
        ],
        "requested_task_class": task_class or None,
        "project_id": project_id or None,
        "generated_at": _now(),
    }
    if task_class:
        policy["matching_routes"] = [row for row in policy["routes"] if row["task_class"] == task_class]
    return policy


def _seed_sections(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    kpis = snapshot.get("judge_kpis") or {}
    rf = snapshot.get("resource_fabric") or {}
    lm = snapshot.get("local_models") or {}
    do = snapshot.get("digitalocean") or {}
    return [
        {"section_id": "architecture", "title": "InnerOS Architecture", "kind": "narrative", "content": {"summary": "InnerOS exposes one MCP ecosystem backed by two local servers, durable coordination, Resource Fabric routing, A2A task projection, ModuleAction contracts and Judge trace evidence.", "runtime_boundary": "Local work runs through allowlisted MCP tools, RACB ops tasks, isolated worktrees and approval gates. Public/demo surfaces remain separate from privileged execution."}, "freshness": _freshness("seeded_runtime_contract", "resource_fabric_status")},
        {"section_id": "live_pass_evidence", "title": "Live PASS Evidence", "kind": "evidence", "content": {"trace_events": kpis.get("total_events"), "verified_events": kpis.get("verified_events"), "simulated_events": kpis.get("simulated_events"), "degraded_events": kpis.get("degraded_events"), "latest_artifacts": kpis.get("artifacts") or [], "truth_boundary": "PASS requires persisted verified trace events. Simulated or degraded events cannot be marked verified."}, "freshness": _freshness("inneros_judge_trace_events", "judge_trace_kpis")},
        {"section_id": "resource_fabric", "title": "Resource Fabric", "kind": "evidence", "content": {"providers": rf.get("providers") or [], "models": rf.get("models") or [], "routing_policy": rf.get("routing_policy")}, "freshness": _freshness("inneros_resource_providers", "resource_fabric_status")},
        {"section_id": "model_routing_policy", "title": "Model Routing Policy", "kind": "policy", "content": model_routing_policy(), "freshness": _freshness("local_model_router", "judge_model_routing_policy")},
        {"section_id": "rocm10_r9700", "title": "ROCm/vLLM R9700", "kind": "runtime", "content": {"local_model_health": lm, "boundary": "AMD is preferred for vLLM/heavy coding. Intel is preferred for Ollama/light ops. Report actual runtime health instead of inferring from install logs."}, "freshness": _freshness("local_model_health", "local_model_health")},
        {"section_id": "mi325x_cloud_burst", "title": "DigitalOcean/Hyperloom MI325X", "kind": "approval_gated_capability", "content": {"digitalocean_status": do, "policy": "MI325X cloud burst is never automatic for judge demos. It requires preflight, estimate, explicit owner approval, apply window, trace evidence and teardown evidence."}, "freshness": _freshness("digitalocean_amd_provider", "digitalocean_status")},
    ]


def get_content(section_id: str = "", refresh: bool = True) -> dict[str, Any]:
    db = _db()
    if refresh:
        for section in _seed_sections(_runtime_snapshot()):
            db[COLLECTION].update_one({"section_id": section["section_id"]}, {"$set": section, "$setOnInsert": {"created_at": _now()}}, upsert=True)
    query = {"section_id": section_id.strip()} if section_id.strip() else {}
    rows = list(db[COLLECTION].find(query, {"_id": 0}).sort("section_id", 1))
    return {"ok": True, "collection": COLLECTION, "count": len(rows), "sections": rows, "generated_at": _now()}
