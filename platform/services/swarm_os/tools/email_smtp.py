"""Envío SMTP reutilizando credenciales de cuentas IMAP monitorizadas."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

from tools.email_providers import detect_provider


def smtp_settings_for_account(acc: dict[str, Any]) -> dict[str, Any]:
    """SMTP a partir de la fila email_accounts (prioriza imap_host del hosting)."""
    address = (acc.get("address") or acc.get("imap_user") or "").strip()
    imap_host = (acc.get("imap_host") or "").strip()
    if imap_host:
        if imap_host.startswith("imap."):
            smtp_host = imap_host.replace("imap.", "smtp.", 1)
        else:
            # cPanel / correo corporativo: mismo servidor que IMAP (mail.dominio)
            smtp_host = imap_host
        return {"smtp_host": smtp_host, "smtp_port": 587, "use_tls": True}
    return smtp_settings_for_address(address)


def smtp_settings_for_address(address: str) -> dict[str, Any]:
    """Deriva host/puerto SMTP a partir del dominio del buzón."""
    domain = address.strip().lower().split("@")[-1] if "@" in address else ""
    presets: dict[str, dict[str, Any]] = {
        "gmail.com": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "use_tls": True},
        "googlemail.com": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "use_tls": True},
        "hotmail.com": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "use_tls": True},
        "outlook.com": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "use_tls": True},
        "live.com": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "use_tls": True},
        "msn.com": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "use_tls": True},
        "yahoo.com": {"smtp_host": "smtp.mail.yahoo.com", "smtp_port": 587, "use_tls": True},
        "icloud.com": {"smtp_host": "smtp.mail.me.com", "smtp_port": 587, "use_tls": True},
        "me.com": {"smtp_host": "smtp.mail.me.com", "smtp_port": 587, "use_tls": True},
    }
    if domain in presets:
        return presets[domain]
    imap = detect_provider(address)
    host = imap.get("imap_host", "")
    smtp_host = host.replace("imap.", "smtp.", 1) if host.startswith("imap.") else f"smtp.{domain}"
    return {"smtp_host": smtp_host, "smtp_port": 587, "use_tls": True}


def send_smtp_email(
    *,
    smtp_host: str,
    smtp_port: int,
    user: str,
    password: str,
    to_addr: str,
    subject: str,
    body: str,
    from_name: str = "",
    from_addr: str | None = None,
    use_tls: bool = True,
) -> dict[str, Any]:
    """Envía un correo de texto plano vía SMTP."""
    if not smtp_host or not user or not password or not to_addr:
        return {"ok": False, "error": "Faltan credenciales SMTP o destinatario"}

    sender = from_addr or user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, sender)) if from_name else sender
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.sendmail(sender, [to_addr], msg.as_string())
        return {"ok": True, "to": to_addr, "subject": subject, "from": msg["From"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_via_account(acc: dict, *, to_addr: str, subject: str, body: str, from_name: str) -> dict[str, Any]:
    """Envía usando una fila de email_accounts (mismas credenciales IMAP)."""
    address = acc.get("address") or acc.get("imap_user") or ""
    smtp = smtp_settings_for_account(acc)
    return send_smtp_email(
        smtp_host=smtp["smtp_host"],
        smtp_port=int(smtp.get("smtp_port", 587)),
        user=acc.get("imap_user") or address,
        password=acc.get("imap_password", ""),
        to_addr=to_addr,
        subject=subject,
        body=body,
        from_name=from_name,
        from_addr=address,
        use_tls=bool(smtp.get("use_tls", True)),
    )


def send_via_account_with_attachments(
    acc: dict,
    *,
    to_addr: str,
    subject: str,
    body: str,
    from_name: str,
    attachments: list[tuple[str, bytes, str]],
) -> dict[str, Any]:
    """Envía con adjuntos (nombre, bytes, mime_type)."""
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    address = acc.get("address") or acc.get("imap_user") or ""
    smtp = smtp_settings_for_account(acc)
    if not to_addr or not address:
        return {"ok": False, "error": "Faltan direcciones"}

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, address)) if from_name else address
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for fname, data, mime in attachments:
        part = MIMEApplication(data, Name=fname)
        part.add_header("Content-Disposition", "attachment", filename=fname)
        if mime:
            part.set_type(mime)
        msg.attach(part)

    try:
        with smtplib.SMTP(smtp["smtp_host"], int(smtp.get("smtp_port", 587)), timeout=45) as server:
            if smtp.get("use_tls", True):
                server.starttls()
            server.login(acc.get("imap_user") or address, acc.get("imap_password", ""))
            server.sendmail(address, [to_addr], msg.as_string())
        return {"ok": True, "to": to_addr, "subject": subject, "attachments": len(attachments)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
