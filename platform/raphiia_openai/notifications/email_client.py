"""Envío SMTP — credenciales de email_accounts (mismo stack que Swarm IMAP)."""

from __future__ import annotations

import os
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store


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


def send_email(
    *,
    to_addr: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
    attachment_name: str | None = None,
    from_account: str | None = None,
) -> dict[str, Any]:
    """Envía usando email_accounts (IMAP creds) — no requiere SMTP_* en .env."""
    acc = _pick_send_account(from_account)
    if not acc:
        return {"ok": False, "error": "Sin cuentas email_accounts habilitadas en Mongo"}

    address = (acc.get("address") or acc.get("imap_user") or "").strip()
    user = (acc.get("imap_user") or address).strip()
    password = (acc.get("imap_password") or acc.get("smtp_password") or "").strip()
    if not user or not password:
        return {"ok": False, "error": f"Credenciales incompletas para {address}"}

    smtp = smtp_settings_for_account(acc)
    smtp_host = (os.getenv("SMTP_HOST") or smtp.get("smtp_host") or "").strip()
    smtp_port = int(acc.get("smtp_port") or os.getenv("SMTP_PORT", "587") or 587)
    use_tls = os.getenv("SMTP_USE_TLS", "1") != "0"
    from_name = (acc.get("from_name") or acc.get("label") or "PC Doctor").strip()

    if not smtp_host:
        return {"ok": False, "error": f"No se pudo derivar SMTP host para {address}"}

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
        return {
            "ok": True,
            "to": to_addr,
            "subject": subject,
            "from": msg["From"],
            "from_account": address,
            "attachment": attachment_path,
            "smtp_host": smtp_host,
            "source": "email_accounts",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "from_account": address, "smtp_host": smtp_host}
