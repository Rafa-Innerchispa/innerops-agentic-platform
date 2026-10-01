"""Envío SMTP — credenciales de email_accounts (mismo stack que Swarm IMAP)."""

from __future__ import annotations

import hashlib
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from raphiia_openai import mongo_store


DEFAULT_DEDUPE_WINDOW_SECONDS = 60 * 60
OUTBOUND_LEDGER_COLLECTION = "email_outbound_ledger"


def smtp_settings_for_account(acc: dict[str, Any]) -> dict[str, Any]:
    """Misma lógica que Swarm tools/email_smtp.py — host derivado de imap_host."""
    address = (acc.get("address") or acc.get("imap_user") or "").strip()
    imap_host = (acc.get("imap_host") or "").strip()
    if imap_host:
        if imap_host.startswith("imap."):
            smtp_host = imap_host.replace("imap.", "smtp.", 1)
        else:
            smtp_host = imap_host
        return {"smtp_host": smtp_host, "smtp_port": 587, "use_tls": True}
    domain = address.lower().split("@")[-1] if "@" in address else ""
    return {"smtp_host": f"smtp.{domain}" if domain else "", "smtp_port": 587, "use_tls": True}


def _pick_send_account(prefer_address: str | None = None) -> dict[str, Any] | None:
    db = mongo_store.get_db()
    if prefer_address:
        acc = db.email_accounts.find_one({"enabled": True, "address": prefer_address.strip().lower()})
        if acc:
            return acc
        acc = db.email_accounts.find_one(
            {"enabled": True, "address": {"$regex": re.escape(prefer_address.strip()), "$options": "i"}}
        )
        if acc:
            return acc
    for query in (
        {"enabled": True, "send_enabled": {"$ne": False}},
        {"enabled": True, "label": {"$regex": "ventas", "$options": "i"}},
        {"enabled": True},
    ):
        acc = db.email_accounts.find_one(query, sort=[("updated_at", -1)])
        if acc:
            return acc
    return None


def _normalise_recipient(value: str) -> str:
    return value.strip().lower()


def _normalise_text(value: str) -> str:
    return " ".join((value or "").split())


def _fallback_idempotency_key(*, from_address: str, to_addr: str, subject: str, body: str) -> str:
    canonical = "\n".join(
        [
            _normalise_recipient(from_address),
            _normalise_recipient(to_addr),
            _normalise_text(subject)[:500],
            _normalise_text(body)[:4000],
        ]
    )
    return "email:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reserve_delivery(
    *,
    key: str,
    from_address: str,
    to_addr: str,
    subject: str,
    window_seconds: int,
) -> tuple[bool, dict[str, Any]]:
    db = mongo_store.get_db()
    collection = db[OUTBOUND_LEDGER_COLLECTION]
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(1, window_seconds))

    existing = collection.find_one({"_id": key})
    if existing:
        status = existing.get("status")
        expiry = existing.get("expires_at")
        if status in {"reserved", "sent"} and expiry and expiry > now:
            return False, existing

    query = {
        "_id": key,
        "$or": [
            {"status": "failed"},
            {"expires_at": {"$lte": now}},
            {"expires_at": {"$exists": False}},
        ],
    }
    update = {
        "$set": {
            "status": "reserved",
            "from_address": from_address,
            "to_addr": _normalise_recipient(to_addr),
            "subject": subject[:200],
            "reserved_at": now,
            "expires_at": expires_at,
            "updated_at": now,
        },
        "$inc": {"attempts": 1},
        "$setOnInsert": {"created_at": now},
    }

    try:
        doc = collection.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        current = collection.find_one({"_id": key}) or {"_id": key, "status": "reserved"}
        return False, current

    if doc is None:
        current = collection.find_one({"_id": key}) or {"_id": key, "status": "reserved"}
        return False, current
    return True, doc


def _mark_delivery(key: str, *, status: str, error: str = "") -> None:
    db = mongo_store.get_db()
    now = datetime.now(timezone.utc)
    set_payload: dict[str, Any] = {"status": status, "updated_at": now}
    update: dict[str, Any] = {"$set": set_payload}
    if status == "sent":
        set_payload["sent_at"] = now
        update["$unset"] = {"last_error": ""}
    if error:
        set_payload["last_error"] = error[:2000]
    db[OUTBOUND_LEDGER_COLLECTION].update_one({"_id": key}, update)


def send_email(
    *,
    to_addr: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
    attachment_name: str | None = None,
    from_account: str | None = None,
    idempotency_key: str | None = None,
    dedupe_window_seconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Envía usando email_accounts con idempotencia durable en Mongo.

    Un envío exitoso o una reserva activa bloquean reintentos equivalentes dentro
    de la ventana. Los intentos fallidos quedan reintentables. Si el caller no
    entrega una clave, se deriva una huella estable de remitente/destino/asunto/cuerpo.
    """
    acc = _pick_send_account(from_account)
    if not acc:
        return {"ok": False, "error": "Sin cuentas email_accounts habilitadas en Mongo"}

    address = (acc.get("address") or acc.get("imap_user") or "").strip()
    user = (acc.get("imap_user") or address).strip()
    password = (acc.get("imap_password") or acc.get("smtp_password") or "").strip()
    if not user or not password:
        return {"ok": False, "error": f"Credenciales incompletas para {address}"}

    key = (idempotency_key or "").strip() or _fallback_idempotency_key(
        from_address=address,
        to_addr=to_addr,
        subject=subject,
        body=body,
    )
    reserved, ledger = _reserve_delivery(
        key=key,
        from_address=address,
        to_addr=to_addr,
        subject=subject,
        window_seconds=dedupe_window_seconds,
    )
    if not reserved:
        return {
            "ok": True,
            "deduplicated": True,
            "delivery_status": ledger.get("status"),
            "idempotency_key": key,
            "to": to_addr,
            "subject": subject,
            "from_account": address,
        }

    smtp = smtp_settings_for_account(acc)
    smtp_host = (os.getenv("SMTP_HOST") or smtp.get("smtp_host") or "").strip()
    smtp_port = int(acc.get("smtp_port") or os.getenv("SMTP_PORT", "587") or 587)
    use_tls = os.getenv("SMTP_USE_TLS", "1") != "0"
    from_name = (acc.get("from_name") or acc.get("label") or "PC Doctor").strip()

    if not smtp_host:
        error = f"No se pudo derivar SMTP host para {address}"
        _mark_delivery(key, status="failed", error=error)
        return {"ok": False, "error": error, "idempotency_key": key}

    msg = MIMEMultipart()
    msg["Subject"] = subject[:200]
    msg["From"] = formataddr((from_name, address))
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_path:
        path = Path(attachment_path)
        if path.is_file():
            part = MIMEApplication(path.read_bytes(), Name=attachment_name or path.name)
            part["Content-Disposition"] = f'attachment; filename="{attachment_name or path.name}"'
            msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=45) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.sendmail(address, [to_addr], msg.as_string())
        _mark_delivery(key, status="sent")
        return {
            "ok": True,
            "deduplicated": False,
            "idempotency_key": key,
            "to": to_addr,
            "subject": subject,
            "from": msg["From"],
            "from_account": address,
            "attachment": attachment_path,
            "smtp_host": smtp_host,
            "source": "email_accounts",
        }
    except Exception as exc:
        _mark_delivery(key, status="failed", error=str(exc))
        return {
            "ok": False,
            "error": str(exc),
            "from_account": address,
            "smtp_host": smtp_host,
            "idempotency_key": key,
        }
