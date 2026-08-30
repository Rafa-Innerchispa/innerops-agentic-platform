"""Conversational workflow state machine for Judge Console actions."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import judge_telemetry

COL_WORKFLOWS = "inneros_judge_workflows"


WORKFLOW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "emergency_plan": {
        "label": "Panihati/ISKCON emergency plan",
        "required": ["scenario", "location", "event_date", "responsible_contact"],
        "optional": ["attendance_estimate", "special_risks", "language"],
        "reuses": ["module_action:iskcon_ops", "notion/memory read-only", "panihati/iskcon context"],
        "artifact": "pdf",
    },
    "quote": {
        "label": "Quote workflow",
        "required": ["client_id_or_name", "contact", "line_items", "currency"],
        "optional": ["site", "tax_rate", "valid_until"],
        "reuses": ["existing clients", "document_engine"],
        "artifact": "quote_draft",
    },
    "agent_collaboration": {
        "label": "Agent collaboration",
        "required": ["prompt"],
        "optional": ["agents", "guardian_required"],
        "reuses": ["A2A delegation", "Service Guardian"],
        "artifact": "trace",
    },
    "local_ai_task": {
        "label": "Local AI task",
        "required": ["prompt"],
        "optional": ["task_class", "preferred_node"],
        "reuses": ["Resource Fabric", "local AMD/Intel routing"],
        "artifact": "trace",
    },
    "ask_aria": {
        "label": "Ask ARIA",
        "required": ["prompt"],
        "optional": ["module_id", "tenant_id"],
        "reuses": ["ARIA/module contracts"],
        "artifact": "answer",
    },
    "verify_system": {
        "label": "Verify system",
        "required": [],
        "optional": ["scope"],
        "reuses": ["dual_deployment", "resource_fabric", "guardian"],
        "artifact": "health_snapshot",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    from raphiia_openai import mongo_store

    return mongo_store.get_db()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _workflow_id(correlation_id: str, intent: str) -> str:
    seed = f"{correlation_id}:{intent}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def classify_intent(message: str, explicit_intent: str = "") -> str:
    raw = _norm(explicit_intent).lower()
    if raw and raw not in {"auto", "intent", "message"}:
        return raw
    text = _norm(message).lower()
    if any(k in text for k in ("emergencia", "emergency", "panihati", "evacuacion", "evacuación")):
        return "emergency_plan"
    if any(k in text for k in ("cotiz", "quote", "presupuesto cliente")):
        return "quote"
    if any(k in text for k in ("colabora", "collaboration", "varios agentes", "guardian")):
        return "agent_collaboration"
    if any(k in text for k in ("local ai", "modelo local", "amd", "intel", "vllm")):
        return "local_ai_task"
    if any(k in text for k in ("verifica", "verify", "health", "sistema")):
        return "verify_system"
    return "ask_aria"


def _extract_fields(message: str, supplied: dict[str, Any]) -> dict[str, Any]:
    fields = {k: v for k, v in (supplied or {}).items() if v not in (None, "")}
    text = _norm(message)
    if text and "prompt" not in fields:
        fields["prompt"] = text
    if text and "scenario" not in fields:
        fields["scenario"] = text
    if "ISKCON" in text.upper() and "location" not in fields:
        fields["location"] = "ISKCON Guayaquil"
    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2}|domingo|sábado|sabado|hoy|mañana|manana)\b", text, re.I)
    if date_match and "event_date" not in fields:
        fields["event_date"] = date_match.group(1)
    if any(k in text.lower() for k in ("rafael", "coordinador", "responsable")) and "responsible_contact" not in fields:
        fields["responsible_contact"] = "coordinador local"
    if "currency" not in fields and ("$" in text or "usd" in text.lower()):
        fields["currency"] = "USD"
    return fields


def _missing(intent: str, fields: dict[str, Any]) -> list[str]:
    required = WORKFLOW_DEFINITIONS[intent]["required"]
    return [name for name in required if not _norm(fields.get(name))]


def _questions_for(intent: str, missing: list[str]) -> list[dict[str, str]]:
    prompts = {
        "scenario": "Describe el escenario exacto que el juez debe probar.",
        "location": "Confirma lugar/sede.",
        "event_date": "Confirma fecha o periodo del evento.",
        "responsible_contact": "Indica responsable o contacto operativo.",
        "client_id_or_name": "Selecciona cliente existente o escribe nombre legal.",
        "contact": "Indica contacto real del cliente.",
        "line_items": "Incluye items, cantidades y precios.",
        "currency": "Confirma moneda.",
        "prompt": "Escribe la instruccion libre para ARIA/agentes/modelo local.",
    }
    return [{"field": name, "question": prompts.get(name, f"Completa {name}.")} for name in missing]


def start_workflow(
    message: str,
    intent: str = "auto",
    fields: dict[str, Any] | None = None,
    correlation_id: str = "",
    actor: str = "judge",
) -> dict[str, Any]:
    selected = classify_intent(message, intent)
    if selected not in WORKFLOW_DEFINITIONS:
        return {"ok": False, "error": "workflow_intent_not_supported", "allowed": sorted(WORKFLOW_DEFINITIONS)}
    cid = correlation_id or f"judge-workflow-{hashlib.sha256((selected + message).encode()).hexdigest()[:12]}"
    wid = _workflow_id(cid, selected)
    values = _extract_fields(message, fields or {})
    missing = _missing(selected, values)
    status = "awaiting_input" if missing else "ready"
    doc = {
        "workflow_id": wid,
        "correlation_id": cid,
        "intent": selected,
        "actor": actor,
        "status": status,
        "fields": values,
        "missing_fields": missing,
        "questions": _questions_for(selected, missing),
        "definition": WORKFLOW_DEFINITIONS[selected],
        "updated_at": _now(),
    }
    _db()[COL_WORKFLOWS].update_one(
        {"workflow_id": wid},
        {"$set": doc, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    judge_telemetry.record_trace_event(
        {
            "correlation_id": cid,
            "run_id": wid,
            "source": "judge_console",
            "target": "workflow_state_machine",
            "protocol": "workflow_v1",
            "agent_id": "judge_workflows",
            "tool": "judge_workflow_start",
            "action": selected,
            "status": "AWAITING_INPUT" if missing else "READY",
            "verified": False,
            "payload": {"missing_fields": missing},
        }
    )
    return {"ok": True, **doc}


def continue_workflow(
    workflow_id: str,
    fields: dict[str, Any] | None = None,
    message: str = "",
    execute: bool = False,
    actor: str = "judge",
) -> dict[str, Any]:
    wid = _norm(workflow_id)
    doc = _db()[COL_WORKFLOWS].find_one({"workflow_id": wid}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "workflow_not_found", "workflow_id": wid}
    merged = dict(doc.get("fields") or {})
    merged.update(_extract_fields(message, fields or {}))
    missing = _missing(doc["intent"], merged)
    status = "awaiting_input" if missing else ("executing" if execute else "ready")
    update = {"fields": merged, "missing_fields": missing, "questions": _questions_for(doc["intent"], missing), "status": status, "updated_at": _now(), "actor": actor}
    _db()[COL_WORKFLOWS].update_one({"workflow_id": wid}, {"$set": update})
    judge_telemetry.record_trace_event(
        {
            "correlation_id": doc["correlation_id"],
            "run_id": wid,
            "source": "judge_console",
            "target": "workflow_state_machine",
            "protocol": "workflow_v1",
            "agent_id": "judge_workflows",
            "tool": "judge_workflow_continue",
            "action": doc["intent"],
            "status": "AWAITING_INPUT" if missing else "READY",
            "verified": False,
            "payload": {"missing_fields": missing},
        }
    )
    if missing or not execute:
        return {"ok": True, **{**doc, **update}}
    execution = execute_workflow(wid, actor=actor)
    return {"ok": execution.get("ok"), **{**doc, **update}, "execution": execution}


def execute_workflow(workflow_id: str, actor: str = "judge") -> dict[str, Any]:
    wid = _norm(workflow_id)
    doc = _db()[COL_WORKFLOWS].find_one({"workflow_id": wid}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "workflow_not_found", "workflow_id": wid}
    missing = _missing(doc["intent"], doc.get("fields") or {})
    if missing:
        return {"ok": False, "error": "workflow_requirements_incomplete", "missing_fields": missing, "questions": _questions_for(doc["intent"], missing)}
    intent = doc["intent"]
    fields = dict(doc.get("fields") or {})
    artifact_id = None
    status = "PASS"
    verified = True
    result: dict[str, Any]
    start = int(datetime.now(timezone.utc).timestamp() * 1000)
    if intent == "emergency_plan":
        from raphiia_openai import module_contract

        result = module_contract.route_module_action(
            tenant_id="ent_iskcon",
            module_id="iskcon_ops",
            intent="emergency_plan",
            inputs=fields,
            actor=actor,
            dry_run=False,
        )
        artifact_id = (result.get("artifact") or {}).get("artifact_id")
        verified = bool(result.get("ok") and artifact_id)
        status = "PASS" if verified else "FAIL"
    elif intent == "verify_system":
        result = judge_telemetry.resource_telemetry()
        verified = bool(result.get("ok"))
        status = "PASS" if verified else "DEGRADED"
    elif intent in {"agent_collaboration", "local_ai_task", "ask_aria"}:
        result = judge_telemetry.safe_judge_trigger(intent, fields.get("prompt") or "", correlation_id=doc["correlation_id"], dry_run=False)
        status = "QUEUED" if result.get("ok") else "FAIL"
        verified = False
    else:
        return {"ok": False, "error": "workflow_execution_not_implemented", "intent": intent}
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    judge_telemetry.record_trace_event(
        {
            "correlation_id": doc["correlation_id"],
            "run_id": wid,
            "ts_start_ms": start,
            "ts_end_ms": end,
            "source": "workflow_state_machine",
            "target": intent,
            "protocol": "workflow_v1",
            "agent_id": "judge_workflows",
            "tool": "judge_workflow_execute",
            "action": intent,
            "latency_ms": end - start,
            "status": status,
            "verified": verified,
            "simulated": False,
            "degraded": status == "DEGRADED",
            "artifact_id": artifact_id,
            "payload": {"result_ok": result.get("ok")},
        }
    )
    final_status = "completed" if status == "PASS" else "queued" if status == "QUEUED" else "degraded"
    _db()[COL_WORKFLOWS].update_one(
        {"workflow_id": wid},
        {"$set": {"status": final_status, "result": result, "artifact_id": artifact_id, "completed_at": _now(), "updated_at": _now()}},
    )
    return {"ok": bool(result.get("ok")), "workflow_id": wid, "intent": intent, "status": final_status, "artifact_id": artifact_id, "result": result}


def get_workflow(workflow_id: str) -> dict[str, Any]:
    doc = _db()[COL_WORKFLOWS].find_one({"workflow_id": _norm(workflow_id)}, {"_id": 0})
    return {"ok": bool(doc), "workflow": doc}


def list_workflows(correlation_id: str = "", limit: int = 50) -> dict[str, Any]:
    query = {"correlation_id": correlation_id} if correlation_id else {}
    rows = list(_db()[COL_WORKFLOWS].find(query, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(int(limit), 200))))
    return {"ok": True, "count": len(rows), "workflows": rows}
