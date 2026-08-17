"""Módulo de almacenamiento y lógica para solicitudes de créditos/fondos (ops_3cc5e52351f7)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from raphiia_openai import mongo_store

COL_CREDIT_APPS = "credit_applications"
COL_EMAIL_MSGS = "email_messages"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_applications() -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    return list(db[COL_CREDIT_APPS].find({}, {"_id": 0}).sort("created_at", -1))


def get_application(app_id: str) -> dict[str, Any] | None:
    db = mongo_store.get_db()
    app = db[COL_CREDIT_APPS].find_one({"app_id": app_id}, {"_id": 0})
    if not app:
        return None
    # Enrich with linked emails details
    linked_ids = app.get("linked_email_ids", [])
    emails = []
    if linked_ids:
        emails = list(db[COL_EMAIL_MSGS].find({"mail_id": {"$in": linked_ids}}, {"_id": 0}).sort("received_at", 1))
    app["linked_emails"] = emails
    return app


def create_application(data: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    app_id = data.get("app_id") or f"app_{uuid.uuid4().hex[:12]}"
    
    doc = {
        "app_id": app_id,
        "program_name": data.get("program_name", "").strip(),
        "provider": data.get("provider", "").strip(),
        "type": data.get("type", "credits"),  # credits, monetary, contest
        "status": data.get("status", "applied"),  # draft, applied, pending_reply, approved, rejected
        "value_requested": data.get("value_requested", ""),
        "value_approved": data.get("value_approved", ""),
        "date_applied": data.get("date_applied") or _now().date().isoformat(),
        "max_reply_date": data.get("max_reply_date", ""),
        "contact_email": data.get("contact_email", "rlopez@innerchispa.us").strip(),
        "linked_domain": data.get("linked_domain", "innerchispa.us").strip(),
        "investor_deck_url": data.get("investor_deck_url", "").strip(),
        "pitch_url": data.get("pitch_url", "").strip(),
        "application_letter": data.get("application_letter", "").strip(),
        "pitch_speech": data.get("pitch_speech", "").strip(),
        "notes": data.get("notes", "").strip(),
        "linked_email_ids": data.get("linked_email_ids") or [],
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    db[COL_CREDIT_APPS].insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "application": doc}


def update_application(app_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    existing = db[COL_CREDIT_APPS].find_one({"app_id": app_id})
    if not existing:
        return {"ok": False, "error": f"Application {app_id} not found"}

    forbidden = {"app_id", "created_at"}
    filtered = {k: v for k, v in patch.items() if k not in forbidden}
    filtered["updated_at"] = _now().isoformat()

    db[COL_CREDIT_APPS].update_one({"app_id": app_id}, {"$set": filtered})
    updated = get_application(app_id)
    return {"ok": True, "application": updated}


def link_email_to_application(app_id: str, mail_id: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    app = db[COL_CREDIT_APPS].find_one({"app_id": app_id})
    if not app:
        return {"ok": False, "error": f"Application {app_id} not found"}

    db[COL_CREDIT_APPS].update_one(
        {"app_id": app_id},
        {
            "$addToSet": {"linked_email_ids": mail_id},
            "$set": {"updated_at": _now().isoformat()}
        }
    )
    return {"ok": True, "linked": mail_id}


def generate_ai_draft(program_name: str, notes: str, prompt: str) -> str:
    import requests
    payload = {
        "model": "qwen2.5:7b",
        "messages": [
            {
                "role": "system",
                "content": "Eres el copiloto de IA de InnerChispa. Redactas pitches de negocios y cartas de solicitud profesionales en inglés y español para convencer a programas de startups (Google Cloud, AWS, Microsoft, etc.) de otorgar fondos o créditos a InnerChispa LLC (plataforma RalphiIA)."
            },
            {
                "role": "user",
                "content": f"Programa: {program_name}\nContexto: {notes}\nInstrucciones del usuario: {prompt}"
            }
        ],
        "stream": False
    }
    try:
        r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")
    except Exception as e:
        return f"Error llamando a Ollama local: {e}"

