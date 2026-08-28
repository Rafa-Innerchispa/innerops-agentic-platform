"""Detección automática de servidores IMAP (Gmail, Outlook, etc.)."""

from __future__ import annotations

import imaplib
from typing import Any


PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "gmail.com": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "provider": "Gmail",
        "auth_note": "Google exige contraseña de aplicación (no la clave normal). Activa 2FA → Seguridad → Contraseñas de aplicaciones.",
        "help_url": "https://myaccount.google.com/apppasswords",
    },
    "googlemail.com": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "provider": "Gmail",
        "auth_note": "Usa contraseña de aplicación de Google.",
        "help_url": "https://myaccount.google.com/apppasswords",
    },
    "hotmail.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "provider": "Outlook / Hotmail",
        "auth_note": "Microsoft puede exigir contraseña de aplicación o IMAP activado en configuración del buzón.",
        "help_url": "https://support.microsoft.com/es-es/office/configuración-de-imap-y-pop-en-outlook-com",
    },
    "outlook.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "provider": "Outlook",
        "auth_note": "Activa IMAP en Outlook.com y usa contraseña de aplicación si tienes 2FA.",
        "help_url": "https://support.microsoft.com/es-es/office/configuración-de-imap-y-pop-en-outlook-com",
    },
    "live.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "provider": "Microsoft Live",
        "auth_note": "Igual que Outlook — IMAP + app password.",
        "help_url": "https://support.microsoft.com/es-es/office/configuración-de-imap-y-pop-en-outlook-com",
    },
    "msn.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "provider": "MSN",
        "auth_note": "Cuenta Microsoft — IMAP en outlook.office365.com.",
        "help_url": "",
    },
    "yahoo.com": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "provider": "Yahoo",
        "auth_note": "Yahoo exige contraseña de aplicación generada en su panel de seguridad.",
        "help_url": "https://help.yahoo.com/kb/generate-manage-third-party-passwords-sln15241.html",
    },
    "icloud.com": {
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "provider": "iCloud",
        "auth_note": "Apple exige contraseña específica de app en appleid.apple.com.",
        "help_url": "https://support.apple.com/es-es/102654",
    },
    "me.com": {
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "provider": "iCloud",
        "auth_note": "Contraseña de app de Apple.",
        "help_url": "",
    },
}


def detect_provider(address: str) -> dict[str, Any]:
    addr = address.strip().lower()
    domain = addr.split("@")[-1] if "@" in addr else ""
    preset = PROVIDER_PRESETS.get(domain)
    if preset:
        return {"address": addr, "domain": domain, "detected": True, **preset}
    return {
        "address": addr,
        "domain": domain,
        "detected": False,
        "imap_host": f"mail.{domain}" if domain else "",
        "imap_port": 993,
        "provider": "Correo corporativo / otro",
        "auth_note": "Confirma IMAP y puerto 993 con tu proveedor de hosting (cPanel, Zoho, etc.).",
        "help_url": "",
    }


def test_imap_connection(
    host: str,
    user: str,
    password: str,
    *,
    port: int = 993,
    folder: str = "INBOX",
) -> dict[str, Any]:
    if not host or not user or not password:
        return {"ok": False, "error": "Faltan servidor, usuario o contraseña"}
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=20)
        conn.login(user, password)
        status, data = conn.select(folder, readonly=True)
        if status != "OK":
            conn.logout()
            return {"ok": False, "error": f"No se pudo abrir carpeta {folder}"}
        count = int(data[0]) if data and data[0] else 0
        conn.logout()
        return {
            "ok": True,
            "message": f"Conexión OK — carpeta {folder} con ~{count} mensajes visibles",
            "folder": folder,
            "message_count_hint": count,
        }
    except imaplib.IMAP4.error as e:
        err = str(e)
        hint = ""
        if "AUTHENTICATIONFAILED" in err.upper() or "Invalid credentials" in err:
            hint = " Credenciales incorrectas o necesitas contraseña de aplicación (Gmail/Outlook/Yahoo)."
        return {"ok": False, "error": err + hint}
    except Exception as e:
        return {"ok": False, "error": str(e)}
