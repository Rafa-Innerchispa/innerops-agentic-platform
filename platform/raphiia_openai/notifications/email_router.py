"""Enrutamiento inteligente de correo → módulo/agente local + seguimiento ops.

Reglas locales primero; Ollama solo si categoría ambigua. Aprende patrones
confirmados en Mongo (ralfia_email_routing_learned).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

ACTIONS_COL = "ralfia_email_actions"
LEARNED_COL = "ralfia_email_routing_learned"

# category → agente, módulo, assignee ops, si crear tarea automática
CATEGORY_ROUTES: dict[str, dict[str, Any]] = {
    "factura": {
        "agent_id": "AG-17",
        "module": "contifico / facturación SRI",
        "assignee": "ralfia",
        "next_step": "Capturar clave SRI/PDF → validar en Contifico",
        "auto_task": True,
        "priority": "high",
    },
    "cotizacion": {
        "agent_id": "AG-38",
        "module": "quoteops / vero comercial",
        "assignee": "ralfia",
        "next_step": "Revisar cotización → QuoteOps o responder cliente",
        "auto_task": True,
        "priority": "high",
    },
    "pago": {
        "agent_id": "AG-18",
        "module": "cobranzas / CxC",
        "assignee": "ralfia",
        "next_step": "Registrar pago o conciliar cobranza",
        "auto_task": True,
        "priority": "high",
    },
    "transferencia": {
        "agent_id": "AG-08",
        "module": "finanzas / conciliación",
        "assignee": "ralfia",
        "next_step": "Conciliar transferencia con extracto",
        "auto_task": True,
        "priority": "normal",
    },
    "extracto": {
        "agent_id": "AG-08",
        "module": "finanzas / bancos",
        "assignee": "ralfia",
        "next_step": "Revisar extracto y conciliar movimientos",
        "auto_task": True,
        "priority": "normal",
    },
    "sri_fiscal": {
        "agent_id": "AG-17",
        "module": "contifico / SRI Ecuador",
        "assignee": "ralfia",
        "next_step": "Validar comprobante fiscal SRI",
        "auto_task": True,
        "priority": "high",
    },
    "fiscal_us": {
        "agent_id": "AG-08",
        "module": "finanzas / fiscal US",
        "assignee": "ralfia",
        "next_step": "Revisar aviso IRS — consultar contador si aplica",
        "auto_task": True,
        "priority": "normal",
    },
    "incidente": {
        "agent_id": "AG-31",
        "module": "ops / service guardian",
        "assignee": "ralfia",
        "next_step": "Confirmar incidente y asignar responsable",
        "auto_task": True,
        "priority": "high",
    },
    "contrato": {
        "agent_id": "AG-14",
        "module": "CRM / clientes",
        "assignee": "ralfia",
        "next_step": "Revisar contrato/licitación y vincular cliente",
        "auto_task": True,
        "priority": "normal",
    },
    "servicio_vencimiento": {
        "agent_id": "AG-36",
        "module": "ops / renovaciones",
        "assignee": "ralfia",
        "next_step": "Renovar servicio antes de suspensión",
        "auto_task": True,
        "priority": "normal",
    },
    "delivery_failure": {
        "agent_id": "AG-05",
        "module": "correo / deliverability",
        "assignee": "ralfia",
        "next_step": "Corregir dirección y reenviar",
        "auto_task": False,
        "priority": "low",
    },
}

FUNDING_KEYWORDS = (
    "grant", "funding", "crédito", "credit", "azure", "aws activate",
    "google cloud", "devpost", "hackathon", "startup program", "voucher",
)
CLIENT_DOC_KEYWORDS = (
    "adjunt", "documento", "enviar copia", "certificado", "RUC", "contrato firmado",
    "solicitud", "requerimiento", "pendiente de", "favor enviar",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain(from_addr: str) -> str:
    m = re.search(r"@([\w.\-]+)", from_addr or "")
    return (m.group(1) if m else "").lower()


def _lookup_learned(from_domain: str, category: str) -> dict[str, Any] | None:
    if not from_domain:
        return None
    row = mongo_store.get_db()[LEARNED_COL].find_one(
        {"from_domain": from_domain, "category": category, "active": True},
        {"_id": 0},
    )
    return row


def route_email(
    doc: dict[str, Any],
    analysis: dict[str, Any],
    *,
    use_local_model: bool = True,
) -> dict[str, Any]:
    """Decide agente/módulo y siguiente paso."""
    category = str(analysis.get("category") or "general")
    priority = str(analysis.get("priority") or "normal")
    subject = str(doc.get("subject") or "")
    body = str(doc.get("body_text") or doc.get("snippet") or "")
    from_addr = str(doc.get("from_addr") or "")
    blob = f"{subject} {body}".lower()
    from_domain = _domain(from_addr)

    learned = _lookup_learned(from_domain, category)
    if learned:
        return {
            "agent_id": learned.get("agent_id"),
            "module": learned.get("module"),
            "assignee": learned.get("assignee", "ralfia"),
            "next_step": learned.get("next_step"),
            "auto_task": learned.get("auto_task", True),
            "priority": learned.get("priority", priority),
            "routing_source": "learned",
            "confidence": 0.9,
        }

    route = dict(CATEGORY_ROUTES.get(category) or {})
    routing_source = "rules"

    if not route:
        if any(k in blob for k in FUNDING_KEYWORDS):
            route = {
                "agent_id": "AG-54",
                "module": "funding / créditos cloud",
                "assignee": "ralfia",
                "next_step": "Registrar oportunidad → save_funding_program",
                "auto_task": True,
                "priority": "normal",
            }
        elif any(k in blob for k in CLIENT_DOC_KEYWORDS):
            route = {
                "agent_id": "AG-38",
                "module": "comercial / documentos cliente",
                "assignee": "ralfia",
                "next_step": "Responder solicitud de documentos al cliente",
                "auto_task": True,
                "priority": "high",
            }
        elif "hackathon" in blob or "devpost" in blob:
            route = {
                "agent_id": "AG-53",
                "module": "hackathons / oportunidades",
                "assignee": "ralfia",
                "next_step": "Evaluar hackathon y preparar postulación",
                "auto_task": True,
                "priority": "normal",
            }

    confidence = 0.85 if route else 0.4

    if not route and use_local_model and priority in ("high", "normal"):
        local = _route_with_local_model(subject, body, from_addr)
        if local.get("agent_id"):
            route = local
            routing_source = "local_model"
            confidence = float(local.get("confidence") or 0.55)

    if not route:
        route = {
            "agent_id": "AG-05",
            "module": "correo / revisión manual",
            "assignee": "ralfia",
            "next_step": "Revisar correo — sin ruta clara; confirmar agente",
            "auto_task": False,
            "priority": priority,
            "needs_human_routing": True,
        }
        routing_source = "fallback"
        confidence = 0.3

    return {
        **route,
        "category": category,
        "from_domain": from_domain,
        "routing_source": routing_source,
        "confidence": confidence,
        "invoke_hint": f"invoke_agent('{route.get('agent_id')}')",
    }


def _route_with_local_model(subject: str, body: str, from_addr: str) -> dict[str, Any]:
    """Ollama local — solo routing, no ejecuta agente."""
    try:
        from raphiia_openai.local_model_router import run_local_model

        prompt = (
            "Clasifica este correo para RalfIA. Responde SOLO JSON válido:\n"
            '{"agent_id":"AG-XX","module":"...","next_step":"...","confidence":0.0-1.0}\n'
            "Agentes: AG-17 Contifico/facturas, AG-38 Vero/cotizaciones, AG-54 funding/credits, "
            "AG-53 hackathons, AG-18 cobranzas, AG-08 finanzas, AG-31 incidentes, AG-05 correo.\n\n"
            f"De: {from_addr}\nAsunto: {subject}\nCuerpo: {body[:1200]}"
        )
        result = run_local_model(task_type="routing", prompt=prompt, max_tokens=200, temperature=0.1)
        if not result.get("ok"):
            return {}
        text = str(result.get("content") or result.get("response") or "")
        m = re.search(r"\{[^{}]+\}", text, re.S)
        if not m:
            return {}
        parsed = json.loads(m.group(0))
        aid = str(parsed.get("agent_id") or "").upper()
        if not re.match(r"AG-\d+", aid):
            return {}
        return {
            "agent_id": aid,
            "module": parsed.get("module") or "general",
            "assignee": "ralfia",
            "next_step": parsed.get("next_step") or "Revisar y actuar",
            "auto_task": True,
            "priority": "normal",
            "confidence": float(parsed.get("confidence") or 0.55),
        }
    except Exception:
        return {}


def apply_routing(
    doc: dict[str, Any],
    analysis: dict[str, Any],
    routing: dict[str, Any],
    *,
    create_task: bool = True,
) -> dict[str, Any]:
    """Persiste acción + ops_task opcional para seguimiento."""
    mail_id = str(doc.get("mail_id") or "").strip()
    if not mail_id:
        return {"ok": False, "error": "mail_id_required"}

    security = analysis.get("security") or {}
    if security.get("verdict") == "block":
        return {"ok": True, "action_created": False, "reason": "email_blocked"}

    priority = routing.get("priority") or analysis.get("priority") or "normal"
    skip_task = (
        not routing.get("auto_task")
        or analysis.get("category") in ("marketing", "security_code")
        or priority == "low"
    )

    action = {
        "mail_id": mail_id,
        "subject": str(doc.get("subject") or "")[:240],
        "from_addr": str(doc.get("from_addr") or "")[:200],
        "category": analysis.get("category"),
        "priority": priority,
        "agent_id": routing.get("agent_id"),
        "module": routing.get("module"),
        "next_step": routing.get("next_step"),
        "routing_source": routing.get("routing_source"),
        "confidence": routing.get("confidence"),
        "status": "pending",
        "task_id": None,
        "needs_human_routing": routing.get("needs_human_routing", False),
        "updated_at": _now(),
    }

    db = mongo_store.get_db()
    existing = db[ACTIONS_COL].find_one({"mail_id": mail_id, "status": {"$nin": ["dismissed"]}})
    action_oid = None
    if existing:
        action["created_at"] = existing.get("created_at") or _now()
        action["task_id"] = existing.get("task_id")
        action_oid = existing["_id"]
        db[ACTIONS_COL].update_one({"_id": action_oid}, {"$set": action})
    else:
        action["created_at"] = _now()
        ins = db[ACTIONS_COL].insert_one(action)
        action_oid = ins.inserted_id

    task_result = None
    if create_task and not skip_task and not action.get("task_id"):
        try:
            from raphiia_openai import coordination_live

            title = f"[Correo/{routing.get('agent_id')}] {(doc.get('subject') or mail_id)[:100]}"
            checklist = [
                routing.get("next_step") or "Revisar correo",
                f"Agente sugerido: {routing.get('agent_id')} ({routing.get('module')})",
                f"mail_id: {mail_id}",
            ]
            task_result = coordination_live.create_ops_task(
                assignee=str(routing.get("assignee") or "ralfia"),
                title=title,
                checklist=checklist,
                priority=priority,
                from_agent=str(routing.get("agent_id") or "AG-05"),
                correlation_id=f"email:{mail_id}",
            )
            if task_result.get("ok") and task_result.get("task_id") and action_oid is not None:
                db[ACTIONS_COL].update_one(
                    {"_id": action_oid},
                    {"$set": {"task_id": task_result["task_id"], "updated_at": _now()}},
                )
        except Exception as exc:
            task_result = {"ok": False, "error": str(exc)[:180]}

    return {
        "ok": True,
        "action_id": str(action_oid) if action_oid else None,
        "mail_id": mail_id,
        "agent_id": routing.get("agent_id"),
        "module": routing.get("module"),
        "task": task_result,
    }


def confirm_routing(
    mail_id: str,
    agent_id: str,
    *,
    module: str = "",
    next_step: str = "",
    from_domain: str = "",
    category: str = "",
) -> dict[str, Any]:
    """Aprende ruta confirmada por Rafael."""
    domain = from_domain or ""
    if not domain:
        doc = mongo_store.get_db().email_messages.find_one({"mail_id": mail_id}) or {}
        domain = _domain(str(doc.get("from_addr") or ""))
    cat = category or "general"
    record = {
        "from_domain": domain,
        "category": cat,
        "agent_id": agent_id.upper(),
        "module": module,
        "next_step": next_step,
        "assignee": "ralfia",
        "auto_task": True,
        "active": True,
        "confirmed_at": _now(),
    }
    mongo_store.get_db()[LEARNED_COL].update_one(
        {"from_domain": domain, "category": cat},
        {"$set": record},
        upsert=True,
    )
    mongo_store.get_db()[ACTIONS_COL].update_one(
        {"mail_id": mail_id},
        {"$set": {"agent_id": agent_id.upper(), "status": "confirmed", "updated_at": _now()}},
    )
    return {"ok": True, "learned": record}


def list_email_actions(*, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if status:
        filt["status"] = status
    rows = list(db[ACTIONS_COL].find(filt, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "count": len(rows), "actions": rows}


def process_email_intelligence(
    doc: dict[str, Any],
    *,
    create_task: bool = True,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pipeline completo: seguridad → análisis → routing → captura documental."""
    from raphiia_openai.notifications import email_review

    if analysis is None:
        analysis = email_review.analyze_email(doc)
    security = None
    try:
        from raphiia_openai.notifications import email_security

        security = email_security.scan_email_message(doc)
        analysis["security"] = security
    except Exception as exc:
        analysis["security"] = {"ok": False, "error": str(exc)[:120]}

    routing = route_email(doc, analysis)
    analysis["routing"] = routing

    capture = None
    if security and security.get("verdict") != "block":
        try:
            from raphiia_openai.notifications import email_document_capture

            capture = email_document_capture.capture_from_email(doc, analysis=analysis, security=security)
        except Exception as exc:
            capture = {"ok": False, "error": str(exc)[:120]}

    routed = apply_routing(doc, analysis, routing, create_task=create_task)

    mail_id = str(doc.get("mail_id") or "")
    if mail_id:
        mongo_store.get_db().email_messages.update_one(
            {"mail_id": mail_id},
            {"$set": {"ralfia_review": analysis, "ralfia_intelligence_at": _now()}},
        )

    return {
        "ok": True,
        "mail_id": mail_id,
        "analysis": analysis,
        "security_verdict": (security or {}).get("verdict"),
        "routing": routing,
        "capture": capture,
        "action": routed,
    }
