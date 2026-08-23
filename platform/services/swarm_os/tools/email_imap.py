"""Lectura IMAP — solo metadatos y snippet (ahorra espacio)."""

from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timezone
from email.header import decode_header
from typing import Any


def _decode_hdr(value: str | None) -> str:
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


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _snippet_from_msg(msg: email.message.Message, max_len: int = 300) -> str:
    body = ""
    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition", "")):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            chunk = payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/plain" and not plain:
                plain = chunk
            elif part.get_content_type() == "text/html" and not html:
                html = chunk
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                html = body
            else:
                plain = body
    body = plain or _strip_html(html) or body
    body = " ".join(body.split())
    return body[:max_len]


def fetch_new_messages(
    host: str,
    user: str,
    password: str,
    *,
    port: int = 993,
    folder: str = "INBOX",
    since_date: datetime | None = None,
    last_uid: int = 0,
    max_messages: int = 30,
    snippet_max: int = 300,
) -> list[dict[str, Any]]:
    """Devuelve mensajes nuevos con metadatos ligeros (sin guardar PST/cuerpo completo)."""
    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(user, password)
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
        # Primera sincronización: del más antiguo al más nuevo (no solo los últimos 30)
        uids_batch = uids_int[:max_messages]
        results = []
        for uid in uids_batch:
            uid_b = str(uid).encode()
            _, msg_data = conn.uid("fetch", uid_b, "(RFC822.SIZE BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.400>)")
            if not msg_data or not msg_data[0]:
                continue
            raw_hdr = b""
            for part in msg_data:
                if isinstance(part, tuple) and part[1]:
                    raw_hdr = part[1]
                    break
            msg = email.message_from_bytes(raw_hdr)
            _, full_data = conn.uid("fetch", uid_b, "(RFC822.SIZE BODY.PEEK[])")
            full_raw = b""
            for part in full_data or []:
                if isinstance(part, tuple) and len(part[1]) > 100:
                    full_raw = part[1]
                    break
            full_msg = email.message_from_bytes(full_raw) if full_raw else msg
            snippet = _snippet_from_msg(full_msg, snippet_max)
            date_hdr = _decode_hdr(msg.get("Date"))
            results.append({
                "uid": uid,
                "message_id": _decode_hdr(msg.get("Message-ID")),
                "from_addr": _decode_hdr(msg.get("From")),
                "to_addr": _decode_hdr(msg.get("To")),
                "subject": _decode_hdr(msg.get("Subject")) or "(sin asunto)",
                "date_hdr": date_hdr,
                "snippet": snippet,
                "has_attachment": any(
                    p.get_content_disposition() == "attachment" for p in full_msg.walk()
                ) if full_msg.is_multipart() else False,
            })
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass
