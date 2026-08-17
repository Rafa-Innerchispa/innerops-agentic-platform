"""Notificaciones cuando alguien solicita acceso a RalfIA voz."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from raphiia_openai.settings import MONGO_DB, MONGO_URI

log = logging.getLogger("ralfia.voice.notify")

COL_NOTIFICATIONS = "ralfia_voice_notifications"
NOTIFY_TO = os.getenv("VOICE_NOTIFY_EMAIL", "rafagye@gmail.com").strip()
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
VOICE_PUBLIC_URL = os.getenv("VOICE_PUBLIC_URL", "https://voz.pcdoctor.ai").rstrip("/")


def _db():
    from pymongo import MongoClient

    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)[MONGO_DB]


def _approval_link(username: str) -> str:
    from raphiia_openai import voice_auth

    token = voice_auth.create_approval_token(username)
    return f"{VOICE_PUBLIC_URL}/api/voice/approve?token={token}"


def _build_message(
    *,
    username: str,
    email: str | None,
    display_name: str | None,
    source: str,
    approve_url: str,
) -> tuple[str, str]:
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    who = display_name or username
    subject = f"[RalfIA Voz] Nueva solicitud: {who} ({username})"
    body = (
        f"Nueva solicitud de acceso a RalfIA voz\n\n"
        f"Usuario: {username}\n"
        f"Email: {email or '(no indicado)'}\n"
        f"Nombre: {display_name or username}\n"
        f"Origen: {source}\n"
        f"Fecha: {ts}\n\n"
        f"Aprobar con un clic (válido 7 días):\n{approve_url}\n"
    )
    return subject, body


def _whatsapp_message(
    *,
    username: str,
    email: str | None,
    display_name: str | None,
    source: str,
    approve_url: str,
) -> str:
    who = display_name or username
    return (
        f"🔔 *RalfIA Voz — nueva solicitud*\n\n"
        f"👤 {who}\n"
        f"📧 {email or username}\n"
        f"📍 Origen: {source}\n\n"
        f"✅ Aprobar acceso:\n{approve_url}"
    )


def _send_email(subject: str, body: str) -> dict[str, Any]:
    if not NOTIFY_TO:
        return {"ok": False, "error": "VOICE_NOTIFY_EMAIL vacío"}
    try:
        from raphiia_openai.notifications.email_client import send_email

        return send_email(to_addr=NOTIFY_TO, subject=subject, body=body)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _send_whatsapp(text: str) -> dict[str, Any]:
    try:
        from raphiia_openai.notifications.evolution_client import any_whatsapp_connected, send_alert_whatsapp

        if not any_whatsapp_connected():
            return {"ok": False, "skipped": True, "reason": "whatsapp_not_connected"}
        return send_alert_whatsapp(text)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _write_mongo(doc: dict[str, Any]) -> None:
    _db()[COL_NOTIFICATIONS].insert_one(doc)


def _send_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    if not NOTIFY_WEBHOOK_URL:
        return {"ok": False, "skipped": True}
    try:
        import httpx

        r = httpx.post(NOTIFY_WEBHOOK_URL, json=payload, timeout=15.0)
        return {"ok": r.status_code < 400, "status": r.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def notify_access_request(
    *,
    username: str,
    email: str | None = None,
    display_name: str | None = None,
    source: str = "register",
) -> dict[str, Any]:
    """Avisa a Rafael por WhatsApp, email, webhook y/o Mongo."""
    username = (username or "").strip()
    approve_url = _approval_link(username)
    subject, body = _build_message(
        username=username,
        email=email,
        display_name=display_name,
        source=source,
        approve_url=approve_url,
    )
    doc: dict[str, Any] = {
        "username": username,
        "email": email,
        "display_name": display_name,
        "source": source,
        "subject": subject,
        "body": body,
        "approve_url": approve_url,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "delivered_via": [],
    }

    wa_result = _send_whatsapp(
        _whatsapp_message(
            username=username,
            email=email,
            display_name=display_name,
            source=source,
            approve_url=approve_url,
        )
    )
    if wa_result.get("ok"):
        doc["delivered_via"].append("whatsapp")
        log.info("VOICE NOTIFY WhatsApp → Rafael usuario=%s source=%s", username, source)
    else:
        doc["whatsapp_error"] = wa_result.get("error") or wa_result.get("reason") or wa_result.get("message")
        log.warning("VOICE NOTIFY WhatsApp falló (%s) usuario=%s", doc["whatsapp_error"], username)

    email_result = _send_email(subject, body)
    if email_result.get("ok"):
        doc["delivered_via"].append("email")
        log.info("VOICE NOTIFY email → %s usuario=%s source=%s", NOTIFY_TO, username, source)
    else:
        doc["email_error"] = email_result.get("error")
        log.warning(
            "VOICE NOTIFY email falló (%s) — guardando Mongo usuario=%s",
            email_result.get("error"),
            username,
        )

    webhook_result = _send_webhook(
        {
            "event": "voice_access_request",
            "username": username,
            "email": email,
            "display_name": display_name,
            "source": source,
            "approve_url": approve_url,
            "public_url": VOICE_PUBLIC_URL,
        }
    )
    if webhook_result.get("ok"):
        doc["delivered_via"].append("webhook")

    if not doc["delivered_via"]:
        doc["delivered_via"].append("mongo")
        log.info(
            "VOICE NOTIFY Mongo ralfia_voice_notifications usuario=%s — Rafael revisa ahí o logs",
            username,
        )

    _write_mongo(doc)
    log.info(
        "VOICE NOTIFY solicitud %s (%s) vía %s",
        username,
        source,
        ",".join(doc["delivered_via"]),
    )
    return {"ok": True, "delivered_via": doc["delivered_via"], "username": username, "approve_url": approve_url}


def notify_access_approved(
    *,
    username: str,
    email: str | None = None,
    display_name: str | None = None,
    approved_by: str = "admin",
) -> dict[str, Any]:
    """Avisa al tester que ya puede entrar."""
    username = (username or "").strip()
    to_addr = (email or "").strip()
    if not to_addr or "@" not in to_addr:
        return {"ok": False, "skipped": True, "reason": "no_email"}
    who = display_name or username
    subject = f"[Ralphi IA] Acceso aprobado — {who}"
    body = (
        f"Hola {who},\n\n"
        f"Rafael ({approved_by}) aprobó tu acceso a Ralphi IA.\n\n"
        f"Entra en: {VOICE_PUBLIC_URL}\n"
        f"Usa «Continuar con Google» o tu usuario/contraseña del portal.\n\n"
        f"— Ralphi IA · PC Doctor AI\n"
    )
    result = _send_email_to(to_addr, subject, body)
    if result.get("ok"):
        log.info("VOICE APPROVED email → %s usuario=%s", to_addr, username)
    return result


def _send_email_to(to_addr: str, subject: str, body: str) -> dict[str, Any]:
    try:
        from raphiia_openai.notifications.email_client import send_email

        return send_email(to_addr=to_addr, subject=subject, body=body)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
