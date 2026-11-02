"""OAuth Microsoft — correo Hotmail/Outlook/ESPOL (.edu M365) sin contraseña IMAP.

Flujo device code: Rafael abre URL en Windows, el servidor guarda refresh_token cifrado.
"""

from __future__ import annotations

import imaplib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store, owner_vault

COL_PENDING = "ralfia_ms_oauth_pending"
COL_TOKENS = "ralfia_ms_oauth_tokens"

# IMAP OAuth2 (personal + muchos tenants) o Graph Mail.Read
DEFAULT_SCOPES = (
    "https://outlook.office.com/IMAP.AccessAsUser.All "
    "https://outlook.office.com/SMTP.Send offline_access openid profile email"
)

TENANT_COMMON = "common"  # personal + work/school multi-tenant
TENANT_ESPOL = "espol.edu.ec"  # intento directo institucional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client_id() -> str:
    return (os.getenv("MICROSOFT_MAIL_CLIENT_ID") or os.getenv("AZURE_MAIL_CLIENT_ID") or "").strip()


def _device_endpoint(tenant: str = TENANT_COMMON) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"


def _token_endpoint(tenant: str = TENANT_COMMON) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


def oauth_config_status() -> dict[str, Any]:
    cid = _client_id()
    return {
        "ok": bool(cid),
        "client_id_configured": bool(cid),
        "client_id_hint": cid[:8] + "..." if cid else "",
        "flow": "device_code",
        "scopes": DEFAULT_SCOPES.strip(),
        "supports": ["hrlg@hotmail.com", "heralope@espol.edu.ec", "outlook/hotmail/live"],
        "setup_doc": "Registrar app Azure → cuentas personales + organizaciones → permiso IMAP.AccessAsUser.All → device code → MICROSOFT_MAIL_CLIENT_ID en .env",
    }


def start_device_login(*, email: str, tenant: str = TENANT_COMMON) -> dict[str, Any]:
    """Inicia login Microsoft; Rafael abre verification_uri en su PC."""
    cid = _client_id()
    if not cid:
        return {
            "ok": False,
            "error": "microsoft_client_id_missing",
            "hint": "Crea app en Azure Portal y define MICROSOFT_MAIL_CLIENT_ID en .env",
        }
    email = email.strip().lower()
    try:
        r = httpx.post(
            _device_endpoint(tenant),
            data={"client_id": cid, "scope": DEFAULT_SCOPES},
            timeout=30.0,
        )
        r.raise_for_status()
        body = r.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

    session_id = f"msoauth_{uuid.uuid4().hex[:12]}"
    expires = _now() + timedelta(seconds=int(body.get("expires_in") or 900))
    doc = {
        "session_id": session_id,
        "email": email,
        "tenant": tenant,
        "device_code": body.get("device_code"),
        "interval": int(body.get("interval") or 5),
        "expires_at": expires,
        "created_at": _now(),
    }
    mongo_store.get_db()[COL_PENDING].insert_one(doc)
    return {
        "ok": True,
        "session_id": session_id,
        "email": email,
        "tenant": tenant,
        "user_code": body.get("user_code"),
        "verification_uri": body.get("verification_uri"),
        "message": body.get("message"),
        "expires_in": body.get("expires_in"),
        "instructions": "Abre verification_uri en tu Windows, inicia sesión con la cuenta indicada, luego llama complete_microsoft_mail_oauth(session_id).",
    }


def complete_device_login(session_id: str, *, timeout_sec: int = 300) -> dict[str, Any]:
    """Poll token endpoint hasta que Rafael complete login en el navegador."""
    cid = _client_id()
    if not cid:
        return {"ok": False, "error": "microsoft_client_id_missing"}

    db = mongo_store.get_db()
    pending = db[COL_PENDING].find_one({"session_id": session_id})
    if not pending:
        return {"ok": False, "error": "session_not_found", "session_id": session_id}

    tenant = str(pending.get("tenant") or TENANT_COMMON)
    email = str(pending.get("email") or "")
    device_code = str(pending.get("device_code") or "")
    interval = int(pending.get("interval") or 5)
    deadline = time.time() + max(30, min(timeout_sec, 600))

    last_err = ""
    while time.time() < deadline:
        try:
            r = httpx.post(
                _token_endpoint(tenant),
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": cid,
                    "device_code": device_code,
                },
                timeout=30.0,
            )
            body = r.json()
            if r.is_success and body.get("access_token"):
                return _store_tokens(email, tenant, body, session_id=session_id)
            err = body.get("error") or ""
            if err == "authorization_pending":
                time.sleep(interval)
                continue
            if err == "slow_down":
                time.sleep(interval + 2)
                continue
            last_err = json.dumps(body)[:400]
            break
        except Exception as exc:
            last_err = str(exc)[:300]
            time.sleep(interval)

    return {"ok": False, "error": "device_login_timeout_or_failed", "detail": last_err}


def _store_tokens(email: str, tenant: str, token_body: dict[str, Any], *, session_id: str = "") -> dict[str, Any]:
    access = str(token_body.get("access_token") or "")
    refresh = str(token_body.get("refresh_token") or "")
    expires_in = int(token_body.get("expires_in") or 3600)
    expires_at = _now() + timedelta(seconds=expires_in)

    owner_vault.save_owner_credential(
        key=f"{email}:ms_refresh_token",
        secret=refresh or access,
        category="oauth_microsoft",
        label=f"Microsoft OAuth {email}",
        metadata={"tenant": tenant, "expires_at": expires_at.isoformat()},
    )

    db = mongo_store.get_db()
    db[COL_TOKENS].update_one(
        {"email": email.lower()},
        {
            "$set": {
                "email": email.lower(),
                "tenant": tenant,
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires_at,
                "updated_at": _now(),
                "auth_method": "oauth2",
            }
        },
        upsert=True,
    )

    # Habilitar cuenta email
    db.email_accounts.update_one(
        {"address": email.lower()},
        {
            "$set": {
                "enabled": True,
                "auth_method": "oauth2",
                "oauth_provider": "microsoft",
                "last_error": "",
                "updated_at": _now(),
            }
        },
        upsert=False,
    )
    if session_id:
        db[COL_PENDING].delete_one({"session_id": session_id})

    imap_ok, imap_msg = test_imap_oauth(email)
    return {
        "ok": True,
        "email": email,
        "tenant": tenant,
        "stored": True,
        "imap_test": imap_ok,
        "imap_message": imap_msg,
    }


def _get_valid_access_token(email: str) -> str:
    db = mongo_store.get_db()
    row = db[COL_TOKENS].find_one({"email": email.lower()}) or {}
    access = str(row.get("access_token") or "")
    expires_at = row.get("expires_at")
    if access and isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > _now() + timedelta(minutes=2):
            return access

    refresh = str(row.get("refresh_token") or "")
    if not refresh:
        cred = owner_vault.get_owner_credential(f"{email.lower()}:ms_refresh_token", reveal=True)
        refresh = str(cred.get("secret") or "")

    cid = _client_id()
    tenant = str(row.get("tenant") or TENANT_COMMON)
    if not refresh or not cid:
        return ""

    r = httpx.post(
        _token_endpoint(tenant),
        data={
            "grant_type": "refresh_token",
            "client_id": cid,
            "refresh_token": refresh,
            "scope": DEFAULT_SCOPES,
        },
        timeout=30.0,
    )
    if not r.is_success:
        return ""
    body = r.json()
    access = str(body.get("access_token") or "")
    if access:
        new_refresh = str(body.get("refresh_token") or refresh)
        expires_at = _now() + timedelta(seconds=int(body.get("expires_in") or 3600))
        db[COL_TOKENS].update_one(
            {"email": email.lower()},
            {"$set": {"access_token": access, "refresh_token": new_refresh, "expires_at": expires_at, "updated_at": _now()}},
        )
        if new_refresh != refresh:
            owner_vault.save_owner_credential(
                key=f"{email.lower()}:ms_refresh_token",
                secret=new_refresh,
                category="oauth_microsoft",
                label=f"Microsoft OAuth {email}",
                metadata={"tenant": tenant},
            )
    return access


def imap_xoauth2_string(email: str, access_token: str) -> str:
    return f"user={email}\x01auth=Bearer {access_token}\x01\x01"


def test_imap_oauth(email: str, *, host: str = "outlook.office365.com", port: int = 993) -> tuple[bool, str]:
    token = _get_valid_access_token(email)
    if not token:
        return False, "sin access_token"
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=25)
        auth = imap_xoauth2_string(email, token)
        conn.authenticate("XOAUTH2", lambda _: auth.encode())
        conn.select("INBOX", readonly=True)
        conn.logout()
        return True, "oauth_imap_ok"
    except Exception as exc:
        return False, str(exc)[:200]


def fetch_new_messages_oauth(
    email: str,
    *,
    host: str = "outlook.office365.com",
    port: int = 993,
    folder: str = "INBOX",
    last_uid: int = 0,
    max_messages: int = 30,
    snippet_max: int = 300,
    since_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """IMAP con XOAUTH2 — misma salida que Swarm email_imap.fetch_new_messages."""
    import email as email_lib
    from email.header import decode_header

    def decode_hdr(value: str | None) -> str:
        if not value:
            return ""
        parts = decode_header(value)
        out = []
        for frag, enc in parts:
            if isinstance(frag, bytes):
                out.append(frag.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(frag))
        return " ".join(out).strip()

    token = _get_valid_access_token(email)
    if not token:
        return []

    conn = imaplib.IMAP4_SSL(host, port)
    try:
        auth = imap_xoauth2_string(email, token)
        conn.authenticate("XOAUTH2", lambda _: auth.encode())
        conn.select(folder, readonly=True)
        if since_date:
            date_str = since_date.strftime("%d-%b-%Y")
            _, data = conn.uid("search", None, f"(SINCE {date_str})")
        elif last_uid:
            _, data = conn.uid("search", None, f"(UID {last_uid + 1}:*)")
        else:
            _, data = conn.uid("search", None, "UNSEEN")
        uids = (data[0] or b"").split()
        if not uids:
            return []
        uids_int = sorted(int(u) for u in uids)
        if last_uid:
            uids_int = [u for u in uids_int if u > last_uid]
        results = []
        for uid in uids_int[:max_messages]:
            uid_b = str(uid).encode()
            _, full_data = conn.uid("fetch", uid_b, "(RFC822.SIZE BODY.PEEK[])")
            full_raw = b""
            for part in full_data or []:
                if isinstance(part, tuple) and part[1]:
                    full_raw = part[1]
                    break
            if not full_raw:
                continue
            msg = email_lib.message_from_bytes(full_raw)
            snippet = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            snippet = payload.decode(part.get_content_charset() or "utf-8", errors="replace")[:snippet_max]
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    snippet = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")[:snippet_max]
            results.append({
                "uid": uid,
                "message_id": decode_hdr(msg.get("Message-ID")),
                "from_addr": decode_hdr(msg.get("From")),
                "to_addr": decode_hdr(msg.get("To")),
                "subject": decode_hdr(msg.get("Subject")) or "(sin asunto)",
                "date_hdr": decode_hdr(msg.get("Date")),
                "snippet": " ".join(snippet.split())[:snippet_max],
                "has_attachment": False,
            })
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass
