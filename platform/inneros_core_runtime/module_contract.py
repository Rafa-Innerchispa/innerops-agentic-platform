"""Reusable InnerOS module action contract.

This layer gives every module the same backend shape for ARIA actions:
tenant, module_id, intent, inputs, approvals, artifacts, audit and evidence.
It is intentionally narrow: no arbitrary shell and no fake success for work
that is not wired to a real backend yet.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.operational import document_engine

COL_ACTIONS = "inneros_module_actions"
COL_ARTIFACTS = "inneros_module_artifacts"
ARTIFACT_ROOT = Path("/home/rlopez/data/inneros/module_artifacts")

LIVE = "LIVE"
PARTIAL = "PARTIAL"
NOT_READY = "NOT_READY"

SAFE_PUBLIC_URL_RE = re.compile(r"^https://", re.I)
LAN_URL_RE = re.compile(r"(?:https?://)?(?:127\.0\.0\.1|localhost|192\.168\.|10\.|172\.(?:1[6-9]|2\d|3[0-1])\.)", re.I)


ISKCON_ACTIONS: dict[str, dict[str, Any]] = {
    "emergency_plan": {
        "label": "Plan de emergencia",
        "status": LIVE,
        "requires_approval": False,
        "artifact": "pdf",
        "inputs": ["scenario", "location", "date", "contacts"],
        "sources": ["notion:iskcon-about", "notion:iskcon-calendar", "website:iskconguayaquil.org"],
    },
    "letter": {
        "label": "Carta institucional",
        "status": LIVE,
        "requires_approval": True,
        "artifact": "pdf",
        "inputs": ["recipient", "purpose", "tone"],
        "sources": ["notion:iskcon-about", "memory:ent_iskcon"],
    },
    "dossier": {
        "label": "Brief para dossier/presentacion",
        "status": LIVE,
        "requires_approval": True,
        "artifact": "pdf",
        "inputs": ["audience", "goal", "festival"],
        "sources": ["notion:panihati", "memory:ent_iskcon"],
    },
    "sponsor_pipeline": {
        "label": "Pipeline de auspiciantes",
        "status": PARTIAL,
        "requires_approval": True,
        "artifact": "structured_plan",
        "inputs": ["festival", "target_segments"],
        "sources": ["mongo:panihati_sponsors", "funding_registry"],
    },
    "festival_budget": {
        "label": "Presupuesto y tareas de festival",
        "status": PARTIAL,
        "requires_approval": True,
        "artifact": "structured_plan",
        "inputs": ["festival", "expected_attendance"],
        "sources": ["mongo:panihati_expenses", "mongo:panihati_tasks"],
    },
    "food_for_life_report": {
        "label": "Food for Life log/reporte",
        "status": LIVE,
        "requires_approval": False,
        "artifact": "pdf",
        "inputs": ["period", "plates", "location"],
        "sources": ["memory:ffl", "mongo:ralfia_memory_items"],
    },
    "whatsapp_draft": {
        "label": "Borrador WhatsApp",
        "status": LIVE,
        "requires_approval": True,
        "artifact": "draft",
        "inputs": ["audience", "message", "schedule"],
        "sources": ["notion:iskcon-calendar", "memory:ent_iskcon"],
        "send_policy": "draft_only_requires_owner_approval",
    },
    "contacts": {
        "label": "Contactos comunitarios",
        "status": LIVE,
        "requires_approval": False,
        "artifact": "summary",
        "inputs": ["query", "role"],
        "sources": ["contacts:ent_iskcon", "ops_contacts:ent_iskcon"],
    },
    "documents": {
        "label": "Documentos y fuentes",
        "status": LIVE,
        "requires_approval": False,
        "artifact": "source_index",
        "inputs": ["query"],
        "sources": ["docvault:read_only", "notion:read_only", "memory:read_only"],
    },
    "temple_checklist": {
        "label": "Checklist operativo del templo",
        "status": NOT_READY,
        "requires_approval": True,
        "artifact": "structured_plan",
        "inputs": ["area", "date", "responsible"],
        "sources": ["memory:planned"],
    },
}

MODULE_MANIFESTS: dict[str, dict[str, Any]] = {
    "iskcon_ops": {
        "module_id": "iskcon_ops",
        "tenant_id": "ent_iskcon",
        "label": "ISKCON Operations",
        "status": LIVE,
        "entrypoints": {
            "public": ["https://iskcon.creatorcore.ai", "https://inneros.iskconguayaquil.org/app/desk"],
            "mcp_profile": "iskcon_ops",
            "agent": "AG-52",
        },
        "menus": [
            {"id": "emergency", "label": "Emergencias", "actions": ["emergency_plan"]},
            {"id": "festival", "label": "Festivales", "actions": ["dossier", "sponsor_pipeline", "festival_budget"]},
            {"id": "community", "label": "Comunidad", "actions": ["whatsapp_draft", "contacts"]},
            {"id": "service", "label": "Food for Life", "actions": ["food_for_life_report"]},
            {"id": "sources", "label": "Documentos", "actions": ["documents"]},
            {"id": "temple", "label": "Templo", "actions": ["temple_checklist"]},
        ],
        "aria": {
            "capabilities": ISKCON_ACTIONS,
            "default_intent": "emergency_plan",
            "audit_required": True,
            "artifact_downloads": "tenant_scoped",
        },
        "routing": {
            "resource_fabric": True,
            "local_first": ["documents", "food_for_life_report", "contacts", "whatsapp_draft"],
            "cloud_allowed": ["emergency_plan", "letter", "dossier"],
        },
    }
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    from raphiia_openai import mongo_store

    return mongo_store.get_db()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return clean[:80] or "artifact"


def _tenant_module(tenant_id: str, module_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    module = MODULE_MANIFESTS.get(_norm(module_id))
    if not module:
        return None, {"ok": False, "error": "module_not_found", "module_id": module_id, "allowed": sorted(MODULE_MANIFESTS)}
    if module["tenant_id"] != _norm(tenant_id):
        return None, {
            "ok": False,
            "error": "tenant_module_mismatch",
            "status_code": 403,
            "tenant_id": tenant_id,
            "module_id": module_id,
        }
    return module, None


def _safe_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    blob = json.dumps(manifest, ensure_ascii=False)
    if LAN_URL_RE.search(blob):
        raise ValueError("manifest_contains_lan_url")
    return json.loads(blob)


def list_module_manifests(tenant_id: str | None = None) -> dict[str, Any]:
    manifests = []
    for manifest in MODULE_MANIFESTS.values():
        if tenant_id and manifest["tenant_id"] != tenant_id:
            continue
        manifests.append(_safe_manifest(manifest))
    return {"ok": True, "count": len(manifests), "manifests": manifests}


def get_module_manifest(tenant_id: str, module_id: str) -> dict[str, Any]:
    module, error = _tenant_module(tenant_id, module_id)
    if error:
        return error
    return {"ok": True, "manifest": _safe_manifest(module)}


def classify_module_intent(message: str, explicit_intent: str = "") -> str:
    raw = _norm(explicit_intent).lower()
    if raw and raw not in {"auto", "intent", "message", "route"}:
        return raw
    text = _norm(message).lower()
    if not text:
        return "status"
    checks = [
        ("emergency_plan", ("emergencia", "emergency", "evacuacion", "evacuación", "riesgo", "seguridad")),
        ("letter", ("carta", "letter", "oficio", "solicitud formal")),
        ("dossier", ("dossier", "presentacion", "presentación", "brief", "deck")),
        ("sponsor_pipeline", ("sponsor", "auspiciante", "patrocinador", "donante", "pipeline")),
        ("festival_budget", ("presupuesto", "budget", "tareas festival", "panihati", "ratha yatra")),
        ("food_for_life_report", ("food for life", "ffl", "raciones", "prasadam", "platos")),
        ("whatsapp_draft", ("whatsapp", "canal", "broadcast", "mensaje diario", "yoga")),
        ("contacts", ("contacto", "contactos", "voluntario", "voluntarios")),
        ("documents", ("documento", "documentos", "fuente", "fuentes", "notion", "memoria")),
    ]
    for intent, needles in checks:
        if any(n in text for n in needles):
            return intent
    return "documents"


def _context_snapshot(tenant_id: str, action: str, limit: int = 5) -> dict[str, Any]:
    from raphiia_openai.agents import ag52_iskcon_ops_agent as ag52

    out = {
        "sources": ag52.ISKCON_SOURCE_REFS,
        "domain_status": {},
        "read_only": True,
    }
    try:
        out["status"] = ag52.agent_iskcon_status()
    except Exception as exc:
        out["status"] = {"ok": False, "error": str(exc)}
    if action in {"documents", "emergency_plan", "letter", "dossier"}:
        try:
            from raphiia_openai import hybrid_context

            ctx = hybrid_context.build_hybrid_context("ISKCON Guayaquil " + action, limit=limit)
            out["hybrid_context"] = {
                "ok": ctx.get("ok", True),
                "counts": ctx.get("counts") or {},
                "items": (ctx.get("items") or [])[:limit],
            }
        except Exception as exc:
            out["hybrid_context"] = {"ok": False, "error": str(exc)}
    return out


def _document_spec(tenant_id: str, module_id: str, action: str, inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    title_by_action = {
        "emergency_plan": "Plan de emergencia ISKCON Guayaquil",
        "letter": "Carta institucional ISKCON Guayaquil",
        "dossier": "Dossier operativo ISKCON Guayaquil",
        "food_for_life_report": "Reporte Food for Life",
    }
    scenario = _norm(inputs.get("scenario") or inputs.get("message") or "Programa comunitario en templo")
    location = _norm(inputs.get("location") or "ISKCON Guayaquil")
    contacts = inputs.get("contacts") or ["Coordinador del templo", "Seguridad/brigada", "Voluntarios responsables"]
    if isinstance(contacts, str):
        contacts = [contacts]
    return {
        "entity_id": tenant_id,
        "document_type": "report",
        "title": title_by_action.get(action, action.replace("_", " ").title()),
        "status": "draft",
        "client": {"display_name": "ISKCON Guayaquil", "contact_name": "Coordinacion local"},
        "site": {"name": location},
        "summary_md": (
            f"Documento generado por el contrato ModuleAction/ARIA para `{module_id}`.\n\n"
            f"Intent: `{action}`.\n\n"
            f"Escenario/base: {scenario}."
        ),
        "sections": [
            {
                "title": "Acciones inmediatas",
                "bullets": [
                    "Confirmar responsable de turno y punto de encuentro.",
                    "Revisar asistencia, visitantes y personas que requieren ayuda.",
                    "Registrar decision, hora y evidencia en InnerOS antes de cerrar el caso.",
                ],
            },
            {
                "title": "Comunicacion",
                "bullets": [
                    "Usar mensajes breves, aprobados y sin datos personales innecesarios.",
                    "Para WhatsApp, preparar borrador y esperar aprobacion humana antes de enviar.",
                    "Publicar cambios solo si el calendario/fuente oficial lo confirma.",
                ],
            },
            {
                "title": "Fuentes usadas",
                "bullets": [f"{src.get('source')}: {src.get('title')}" for src in context.get("sources", [])[:8]],
                "note": "Fuentes read-only; no se duplica DB ni se declara disponibilidad no verificada.",
            },
        ],
        "meta_extra": [
            {"label": "Tenant", "value": tenant_id},
            {"label": "Modulo", "value": module_id},
        ],
    }


def _artifact_id(tenant_id: str, module_id: str, action: str, inputs: dict[str, Any]) -> str:
    seed = json.dumps({"tenant": tenant_id, "module": module_id, "action": action, "inputs": inputs}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _save_artifact_record(record: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "record": record}
    db = _db()
    db[COL_ARTIFACTS].update_one({"artifact_id": record["artifact_id"]}, {"$set": record}, upsert=True)
    return {"ok": True, "dry_run": False, "artifact_id": record["artifact_id"]}


def _generate_pdf_artifact(tenant_id: str, module_id: str, action: str, inputs: dict[str, Any], context: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    aid = _artifact_id(tenant_id, module_id, action, inputs)
    filename = f"{_slug(module_id)}-{_slug(action)}-{aid}.pdf"
    path = ARTIFACT_ROOT / tenant_id / module_id / filename
    record = {
        "artifact_id": aid,
        "tenant_id": tenant_id,
        "module_id": module_id,
        "action": action,
        "kind": "pdf",
        "path": str(path),
        "created_at": _now(),
        "download_policy": "tenant_scoped",
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "artifact": record}
    spec = _document_spec(tenant_id, module_id, action, inputs, context)
    rendered = document_engine.render_pdf_document(spec, path)
    record.update({"render": rendered, "filename": rendered.get("pdf_filename")})
    _save_artifact_record(record, dry_run=False)
    return {"ok": True, "dry_run": False, "artifact": record}


def _structured_artifact(tenant_id: str, module_id: str, action: str, inputs: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    aid = _artifact_id(tenant_id, module_id, action, inputs)
    plan = {
        "artifact_id": aid,
        "tenant_id": tenant_id,
        "module_id": module_id,
        "action": action,
        "kind": "structured_plan",
        "status": "draft",
        "sections": [
            {"title": "Siguiente accion", "items": ["Validar fuente oficial", "Asignar responsable", "Registrar evidencia"]},
            {"title": "Aprobaciones", "items": ["Owner approval requerido antes de publicar o enviar"]},
        ],
    }
    _save_artifact_record(plan, dry_run=dry_run)
    return {"ok": True, "dry_run": dry_run, "artifact": plan}


def _draft_artifact(tenant_id: str, module_id: str, action: str, inputs: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    aid = _artifact_id(tenant_id, module_id, action, inputs)
    draft = {
        "artifact_id": aid,
        "tenant_id": tenant_id,
        "module_id": module_id,
        "action": action,
        "kind": "draft",
        "status": "draft_requires_owner_approval",
        "message": _norm(inputs.get("message") or "Hare Krishna. Compartimos una novedad para la comunidad: [completar y aprobar]."),
        "channel": _norm(inputs.get("channel") or "whatsapp_yoga"),
        "send_ready": False,
    }
    _save_artifact_record(draft, dry_run=dry_run)
    return {"ok": True, "dry_run": dry_run, "artifact": draft}


def route_module_action(
    tenant_id: str,
    module_id: str,
    intent: str = "auto",
    inputs: dict[str, Any] | None = None,
    *,
    actor: str = "aria",
    dry_run: bool = True,
) -> dict[str, Any]:
    inputs = dict(inputs or {})
    module, error = _tenant_module(tenant_id, module_id)
    if error:
        return error
    action = classify_module_intent(_norm(inputs.get("message") or inputs.get("prompt")), intent)
    actions = module["aria"]["capabilities"]
    spec = actions.get(action)
    if not spec:
        return {"ok": False, "error": "intent_not_supported", "intent": action, "allowed": sorted(actions)}
    if spec["status"] == NOT_READY:
        return {"ok": False, "error": "action_not_ready", "status": NOT_READY, "intent": action}

    approval = {
        "required": bool(spec.get("requires_approval")),
        "status": "required" if spec.get("requires_approval") else "not_required",
        "policy": spec.get("send_policy") or "artifact_review_before_external_send",
    }
    context = _context_snapshot(tenant_id, action)
    artifact_kind = spec.get("artifact")
    if artifact_kind == "pdf":
        artifact = _generate_pdf_artifact(tenant_id, module_id, action, inputs, context, dry_run=dry_run)
    elif artifact_kind == "draft":
        artifact = _draft_artifact(tenant_id, module_id, action, inputs, dry_run=dry_run)
    elif artifact_kind in {"structured_plan", "summary", "source_index"}:
        artifact = _structured_artifact(tenant_id, module_id, action, inputs, dry_run=dry_run)
    else:
        return {"ok": False, "error": "artifact_kind_not_supported", "artifact": artifact_kind}

    action_record = {
        "tenant_id": tenant_id,
        "module_id": module_id,
        "intent": action,
        "actor": actor,
        "inputs": inputs,
        "approval": approval,
        "artifact": artifact.get("artifact"),
        "status": spec["status"],
        "created_at": _now(),
        "evidence": {
            "contract": "module_action_v1",
            "sources_read_only": True,
            "fake_success_prevented": True,
        },
    }
    if not dry_run:
        _db()[COL_ACTIONS].insert_one(dict(action_record))

    return {
        "ok": True,
        "contract": "module_action_v1",
        "tenant_id": tenant_id,
        "module_id": module_id,
        "intent": action,
        "status": spec["status"],
        "approval": approval,
        "artifact": artifact.get("artifact"),
        "context": context,
        "dry_run": dry_run,
        "audit": {"written": not dry_run, "collection": COL_ACTIONS},
    }


def download_module_artifact(tenant_id: str, artifact_id: str) -> dict[str, Any]:
    aid = _norm(artifact_id)
    if not aid:
        return {"ok": False, "error": "artifact_id_required"}
    record = _db()[COL_ARTIFACTS].find_one({"artifact_id": aid}, {"_id": 0})
    if not record:
        return {"ok": False, "error": "artifact_not_found", "artifact_id": aid}
    if record.get("tenant_id") != _norm(tenant_id):
        return {"ok": False, "error": "cross_tenant_forbidden", "status_code": 403}
    path = Path(record.get("path") or "")
    if record.get("kind") == "pdf" and not path.is_file():
        return {"ok": False, "error": "artifact_file_missing", "artifact_id": aid}
    return {
        "ok": True,
        "artifact_id": aid,
        "tenant_id": tenant_id,
        "kind": record.get("kind"),
        "path": str(path) if path else None,
        "download_policy": record.get("download_policy") or "tenant_scoped",
        "record": record,
    }
