from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import durable_coordination_spine, tracking_envelope

AUDIT_FABRIC_VERSION = "inneros.audit_fabric.v1"
VALID_AUDIT_STAGES = frozenset({"start", "route", "approval", "action", "result", "quality"})
VALID_EVIDENCE_LEVELS = frozenset({0, 1, 2, 3})
AUDIT_EVENT_PREFIX = "audit."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else 0.0


def _clamp_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        return 50


def normalize_evidence_level(level: int | str | None) -> int:
    try:
        parsed = int(level if level is not None else 1)
    except (TypeError, ValueError):
        parsed = 1
    if parsed not in VALID_EVIDENCE_LEVELS:
        raise ValueError("invalid_evidence_level")
    return parsed


def htr_record_from_productivity(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    measurement_class = _clean(data.get("measurement_class") or data.get("measurement_mode") or "estimated").lower()
    verified = bool(data.get("verified", measurement_class == "measured"))
    source = _clean(data.get("measurement_source") or data.get("source"))
    mode = "MEASURED" if measurement_class == "measured" and verified and source else "ESTIMATED"
    baseline = _float_or_none(data.get("baseline_human_minutes") or data.get("human_baseline_minutes")) or 0.0
    assisted = _float_or_none(data.get("assisted_active_human_minutes") or data.get("assisted_minutes")) or 0.0
    rework = _float_or_none(data.get("rework_human_minutes") or data.get("rework_minutes")) or 0.0
    returned = baseline - assisted - rework
    estimate_reason = _clean(data.get("estimate_reason") or data.get("notes"))
    if mode == "ESTIMATED" and not estimate_reason:
        if measurement_class == "measured" and verified and not source:
            estimate_reason = "measured productivity claim missing measurement_source"
        elif measurement_class == "measured" and not verified:
            estimate_reason = "measured productivity claim not verified"
        else:
            estimate_reason = "not verified as measured"
    return {
        "schema_version": "inneros.htr_record.v1",
        "task_id": _clean(data.get("task_id") or data.get("task_key")),
        "measurement_mode": mode,
        "baseline_human_minutes": baseline,
        "assisted_active_human_minutes": assisted,
        "rework_human_minutes": rework,
        "returned_human_minutes": returned,
        "interventions": int(_float_or_none(data.get("interventions")) or 0),
        "handoffs": int(_float_or_none(data.get("handoffs")) or 0),
        "local_compute_seconds": _float_or_none(data.get("local_compute_seconds") or data.get("local_seconds")),
        "cloud_compute_seconds": _float_or_none(data.get("cloud_compute_seconds") or data.get("cloud_seconds")),
        "external_cost_usd": _float_or_none(data.get("external_cost_usd") or data.get("cost_usd")),
        "measurement_source": source or None,
        "estimate_reason": estimate_reason or None,
        "quality_gate": {
            "gate": "negative_return" if returned < 0 else ("measured" if mode == "MEASURED" else "estimated"),
            "confidence": "needs_review" if returned < 0 else ("high" if mode == "MEASURED" else "medium"),
            "measurement_mode": mode,
        },
    }


def routing_evidence_from_resource_decision(
    route_result: dict[str, Any] | None,
    *,
    latency_ms: float | None = None,
    policy: str = "resource_fabric_v1",
) -> dict[str, Any]:
    result = dict(route_result or {})
    selected = result.get("selected") or {}
    model = selected.get("model") or {}
    provider = selected.get("provider") or {}
    candidates = result.get("candidates") or []
    provider_id = _clean(model.get("provider_id") or provider.get("provider_id") or selected.get("provider_id"))
    selected_model = _clean(
        model.get("model_name")
        or model.get("model_provider")
        or model.get("model_ref")
        or selected.get("model_name")
        or provider.get("label")
        or provider_id
    )
    cost_policy = _clean(model.get("cost_policy") or provider.get("cost_policy"))
    provider_kind = _clean(provider.get("kind") or selected.get("provider_kind"))
    local_cloud = _clean(selected.get("local_cloud") or model.get("local_cloud") or provider.get("local_cloud"))
    if not local_cloud:
        local_cloud = "cloud" if cost_policy == "explicit_burst_only" or provider_kind in {"cloud", "cloud_provider"} else "local"
    reason_codes = (
        selected.get("reason_codes")
        or result.get("reason_codes")
        or model.get("reason_codes")
        or provider.get("reason_codes")
        or []
    )
    if isinstance(reason_codes, str):
        reason_codes = [reason_codes]
    reason_codes = [_clean(code) for code in reason_codes if _clean(code)]
    if not reason_codes:
        reason_codes = ["local_first"] if selected and local_cloud == "local" else (["explicit_cloud_burst"] if selected else ["no_candidate"])
    fallback = selected.get("fallback", result.get("fallback", model.get("fallback", provider.get("fallback"))))
    return {
        "schema_version": "inneros.routing_evidence.v1",
        "provider_id": provider_id,
        "provider_kind": provider_kind,
        "selected_model": selected_model,
        "selected_agent": _clean(provider.get("label") or selected.get("selected_agent") or provider_id),
        "local_cloud": local_cloud,
        "route_reason": _clean(result.get("route_reason") or selected.get("route_reason")) or ("resource_fabric_selected" if selected else "resource_fabric_no_candidate"),
        "reason_codes": reason_codes,
        "fallback": bool(fallback) if fallback is not None else False,
        "policy": _clean(result.get("policy") or model.get("policy") or provider.get("policy") or policy),
        "policy_version": _clean(result.get("policy_version") or model.get("policy_version") or provider.get("policy_version")) or None,
        "latency_ms": latency_ms,
        "cost_usd": _float_or_none(model.get("cost_usd") or provider.get("cost_usd")),
        "candidate_count": len(candidates),
        "task_class": _clean(result.get("task_class")),
        "project_id": _clean(result.get("project_id")),
    }


def build_audit_payload(
    *,
    stage: str,
    tenant_id: str = "",
    workflow_id: str = "",
    evidence_level: int | str | None = 1,
    routing_evidence: dict[str, Any] | None = None,
    htr_record: dict[str, Any] | None = None,
    decision_evidence: dict[str, Any] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    forensic_bundle_ref: str = "",
    approval: dict[str, Any] | None = None,
    action: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_n = _clean(stage).lower()
    if stage_n not in VALID_AUDIT_STAGES:
        raise ValueError("invalid_audit_stage")
    return {
        "audit_fabric_version": AUDIT_FABRIC_VERSION,
        "stage": stage_n,
        "tenant_id": _clean(tenant_id),
        "workflow_id": _clean(workflow_id),
        "evidence_level": normalize_evidence_level(evidence_level),
        "routing_evidence": dict(routing_evidence or {}),
        "htr_record": dict(htr_record or {}),
        "decision_evidence": dict(decision_evidence or {}),
        "evidence_refs": list(evidence_refs or []),
        "forensic_bundle_ref": _clean(forensic_bundle_ref),
        "approval": dict(approval or {}),
        "action": dict(action or {}),
        "result": dict(result or {}),
        "quality": dict(quality or {}),
        "metadata": dict(metadata or {}),
        "created_at": _now(),
    }


def emit_audit_hook(
    stage: str,
    *,
    actor: str,
    task_id: str = "",
    correlation_id: str = "",
    repo: str = "",
    tenant_id: str = "",
    workflow_id: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    evidence_level: int | str | None = 1,
    routing_evidence: dict[str, Any] | None = None,
    productivity: dict[str, Any] | None = None,
    htr_record: dict[str, Any] | None = None,
    decision_evidence: dict[str, Any] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    forensic_bundle_ref: str = "",
    approval: dict[str, Any] | None = None,
    action: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    traceparent: str = "",
    dry_run: bool = False,
    live_mode: str = "LIVE",
) -> dict[str, Any]:
    htr = dict(htr_record or {})
    if productivity and not htr:
        htr = htr_record_from_productivity(productivity)
    payload = build_audit_payload(
        stage=stage,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        evidence_level=evidence_level,
        routing_evidence=routing_evidence,
        htr_record=htr,
        decision_evidence=decision_evidence,
        evidence_refs=evidence_refs,
        forensic_bundle_ref=forensic_bundle_ref,
        approval=approval,
        action=action,
        result=result,
        quality=quality,
        metadata=metadata,
    )
    envelope = tracking_envelope.build_envelope(
        original_task_id=task_id,
        correlation_id=correlation_id,
        traceparent_header=traceparent,
        agent=actor,
        provider=provider,
        model=model,
        repo=repo or "Rafa-Innerchispa/innerops-agentic-platform",
        simulated=dry_run or live_mode == "NON-LIVE",
        extra={"tenant_id": _clean(tenant_id), "workflow_id": _clean(workflow_id)},
    )
    sink = durable_coordination_spine.MemoryEventSink([]) if dry_run else None
    event_type = f"{AUDIT_EVENT_PREFIX}{payload['stage']}"
    published = durable_coordination_spine.publish_event(
        event_type,
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id or envelope["correlation_id"],
        repo=repo,
        provider=provider,
        model=model,
        status=status,
        payload=payload,
        envelope=envelope,
        traceparent=traceparent,
        sink=sink,
        live_mode="NON-LIVE" if dry_run else live_mode,
    )
    return {
        "ok": bool(published.get("ok")),
        "dry_run": dry_run,
        "audit_fabric_version": AUDIT_FABRIC_VERSION,
        "stage": payload["stage"],
        "event_id": published.get("event_id"),
        "event": published.get("event"),
        "publish_result": {k: v for k, v in published.items() if k != "event"},
    }


def emit_route_decision(
    route_result: dict[str, Any],
    *,
    actor: str = "resource_fabric",
    task_id: str = "",
    correlation_id: str = "",
    tenant_id: str = "",
    workflow_id: str = "",
    repo: str = "Rafa-Innerchispa/innerops-agentic-platform",
    latency_ms: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    routing = routing_evidence_from_resource_decision(route_result, latency_ms=latency_ms)
    return emit_audit_hook(
        "route",
        actor=actor,
        task_id=task_id,
        correlation_id=correlation_id or _clean(route_result.get("correlation_id")),
        repo=repo,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        provider=routing.get("provider_id", ""),
        model=routing.get("selected_model", ""),
        status="selected" if route_result.get("ok") else "no_candidate",
        evidence_level=1,
        routing_evidence=routing,
        metadata={"source": "resource_fabric.route_resource_request"},
        dry_run=dry_run,
    )


def list_audit_events(
    *,
    correlation_id: str = "",
    tenant_id: str = "",
    workflow_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    from raphiia_openai import mongo_store

    query: dict[str, Any] = {"event_type": {"$regex": "^audit\\."}}
    if correlation_id:
        query["correlation_id"] = _clean(correlation_id)
    if tenant_id:
        query["payload.tenant_id"] = _clean(tenant_id)
    if workflow_id:
        query["payload.workflow_id"] = _clean(workflow_id)
    rows = list(
        mongo_store.get_db()[durable_coordination_spine.EVENTS_COL]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(_clamp_limit(limit))
    )
    return {
        "ok": True,
        "count": len(rows),
        "events": rows,
        "filters": {"correlation_id": correlation_id, "tenant_id": tenant_id, "workflow_id": workflow_id},
        "read_only": True,
    }


def audit_fabric_status() -> dict[str, Any]:
    return {
        "ok": True,
        "version": AUDIT_FABRIC_VERSION,
        "stages": sorted(VALID_AUDIT_STAGES),
        "evidence_levels": {
            "0": "operational log",
            "1": "Decision/Routing Evidence",
            "2": "Forensic Bundle reference",
            "3": "Full Replay or Counterfactual evidence",
        },
        "spine": durable_coordination_spine.status(),
        "query_surface": "read-only by correlation_id, tenant_id or workflow_id",
        "local_first": True,
        "production_enabled": False,
    }
