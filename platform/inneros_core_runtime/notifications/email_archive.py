"""Archivo permanente de correo — metadata + cuerpo + adjuntos en Mongo/disco.

No elimina mensajes del origen IMAP. Deep-link autenticado vía token HMAC en :8101.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

ARCHIVE_COL = "email_archive"
ATTACH_COL = "email_archive_attachments"
ARCHIVE_ROOT = Path(os.getenv("EMAIL_ARCHIVE_ROOT", "/home/rlopez/data/media/email_archive"))
ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
_TOKEN_TTL_SEC = int(os.getenv("EMAIL_ARCHIVE_TOKEN_TTL", "86400"))  # 24h
_TOKEN_SECRET = os.getenv("EMAIL_ARCHIVE_TOKEN_SECRET") or os.getenv("MCP_API_KEY") or "ralfia-email-archive"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _view_base_url() -> str:
    db = _db()
    settings = db.email_settings.find_one({"_id": "global"}) or {}
    base = (
        settings.get("email_archive_view_base_url")
        or os.getenv("EMAIL_ARCHIVE_VIEW_BASE")
        or "https://correo.pcdoctor.ai/api/v1/email-archive"
    )
    return str(base).rstrip("/")


def issue_email_view_token(mail_id: str, *, ttl_sec: int | None = None) -> str:
    """Token HMAC mail_id:exp:sig — válido TTL segundos."""
    exp = int(time.time()) + int(ttl_sec or _TOKEN_TTL_SEC)
    mid = str(mail_id).strip()
    payload = f"{mid}:{exp}"
    sig = hmac.new(_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{mid}.{exp}.{sig}"


def verify_email_view_token(token: str) -> dict[str, Any]:
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        return {"ok": False, "error": "invalid_token"}
    mid, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return {"ok": False, "error": "invalid_exp"}
    if exp < int(time.time()):
        return {"ok": False, "error": "token_expired"}
    payload = f"{mid}:{exp}"
    expect = hmac.new(_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(expect, sig):
        return {"ok": False, "error": "bad_signature"}
    return {"ok": True, "mail_id": mid, "exp": exp}


def build_view_url(mail_id: str) -> str:
    tok = issue_email_view_token(mail_id)
    return f"{_view_base_url()}/{mail_id}?token={tok}"


def ensure_email_archive_indexes() -> dict[str, Any]:
    db = _db()
    specs = [
        (ARCHIVE_COL, [("message_id", 1)], {"name": "ux_email_archive_message_id", "unique": True, "sparse": True, "partialFilterExpression": {"message_id": {"$type": "string", "$ne": ""}}}),
        (ARCHIVE_COL, [("mail_id", 1)], {"name": "ux_email_archive_mail_id", "unique": True, "sparse": True}),
        (ARCHIVE_COL, [("account_address", 1), ("received_at", -1)], {"name": "ix_email_archive_account_received"}),
        (ARCHIVE_COL, [("from_addr", 1)], {"name": "ix_email_archive_from"}),
        (ARCHIVE_COL, [("subject_norm", 1)], {"name": "ix_email_archive_subject"}),
        (ATTACH_COL, [("mail_id", 1)], {"name": "ix_email_attach_mail"}),
    ]
    created = []
    for col, keys, kwargs in specs:
        try:
            db[col].create_index(keys, **kwargs)
            created.append(kwargs.get("name"))
        except Exception:
            continue
    return {"ok": True, "indexes": created}


def _subject_norm(subject: str) -> str:
    return " ".join((subject or "").lower().split())


def archive_email_message(doc: dict[str, Any], *, body_text: str | None = None, raw_eml: bytes | None = None) -> dict[str, Any]:
    """Persiste un mensaje (desde email_messages Swarm o payload directo)."""
    ensure_email_archive_indexes()
    db = _db()
    mail_id = str(doc.get("mail_id") or doc.get("message_id") or "").strip()
    if not mail_id:
        mail_id = hashlib.sha256(
            f"{doc.get('account_address')}|{doc.get('from_addr')}|{doc.get('subject')}|{doc.get('received_at')}".encode()
        ).hexdigest()[:24]
        mail_id = f"mail_{mail_id}"
    message_id = str(doc.get("message_id") or doc.get("rfc822_message_id") or "").strip() or None
    has_att_raw = doc.get("has_attachment")
    has_attachment = bool(has_att_raw) if not isinstance(has_att_raw, str) else has_att_raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "si",
        "sí",
    }
    att_count = int(doc.get("attachment_count") or (1 if has_attachment else 0))
    archived = {
        "mail_id": mail_id,
        "message_id": message_id,
        "email_account_id": doc.get("email_account_id"),
        "uid": doc.get("uid"),
        "account_address": (doc.get("account_address") or "").strip().lower(),
        "from_addr": doc.get("from_addr") or doc.get("from") or "",
        "to_addr": doc.get("to_addr") or doc.get("to") or "",
        "subject": doc.get("subject") or "",
        "subject_norm": _subject_norm(doc.get("subject") or ""),
        "importance": doc.get("importance"),
        "importance_reason": doc.get("importance_reason"),
        "received_at": doc.get("received_at"),
        "body_text": (body_text or doc.get("body_text") or doc.get("snippet") or "")[:50000],
        "has_raw_eml": False,
        "has_attachment": has_attachment,
        "attachment_count": att_count,
        "client_id": doc.get("client_id"),
        "project_id": doc.get("project_id"),
        "source": doc.get("source") or "swarm_email_messages",
        "archived_at": _now(),
        "updated_at": _now(),
    }
    if raw_eml:
        rel = Path(archived["account_address"] or "unknown") / f"{mail_id}.eml"
        path = ARCHIVE_ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_eml)
        archived["has_raw_eml"] = True
        archived["eml_path"] = str(path)
        archived["eml_sha256"] = hashlib.sha256(raw_eml).hexdigest()
    # Prefer stable RFC822 message_id when present to avoid dup index collisions
    filt: dict[str, Any]
    if message_id:
        filt = {"message_id": message_id}
    else:
        filt = {"mail_id": mail_id}
    try:
        db[ARCHIVE_COL].update_one(filt, {"$set": archived}, upsert=True)
    except Exception:
        # Fallback if unique index race on message_id
        db[ARCHIVE_COL].update_one({"mail_id": mail_id}, {"$set": archived}, upsert=True)
    # Deep link autenticado (token rotativo en cada sync)
    # Never preserve the legacy Admin-SPA URL: it returned only an empty shell
    # in external browsers. Every archive link must target this authenticated
    # server-rendered route with a fresh HMAC token.
    view_url = build_view_url(mail_id)
    db[ARCHIVE_COL].update_one({"mail_id": mail_id}, {"$set": {"view_url": view_url, "updated_at": _now()}})
    # Persist attachment metadata stubs if present on source
    attachments = doc.get("attachments")
    security_summary = None
    if isinstance(attachments, list) and attachments:
        try:
            from raphiia_openai.notifications import email_security

            security_summary = email_security.scan_email_message(archived, attachments)
            archived["security_verdict"] = security_summary.get("verdict")
            archived["fetch_attachments"] = security_summary.get("fetch_attachments")
        except Exception:
            pass
    if isinstance(attachments, list):
        for idx, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            att_id = str(att.get("attachment_id") or att.get("filename") or f"{mail_id}:{idx}")
            att_scan = {}
            if security_summary and idx < len(security_summary.get("attachment_scans") or []):
                att_scan = security_summary["attachment_scans"][idx]
            db[ATTACH_COL].update_one(
                {"attachment_id": att_id, "mail_id": mail_id},
                {
                    "$set": {
                        "attachment_id": att_id,
                        "mail_id": mail_id,
                        "filename": att.get("filename") or att.get("name") or f"attach_{idx}",
                        "content_type": att.get("content_type") or att.get("mime") or "",
                        "size": att.get("size"),
                        "path": att.get("path") or att.get("local_path"),
                        "security_verdict": att_scan.get("verdict"),
                        "fetch_allowed": att_scan.get("fetch_allowed"),
                        "auto_process": att_scan.get("auto_process"),
                        "updated_at": _now(),
                    }
                },
                upsert=True,
            )
    return {"ok": True, "mail_id": mail_id, "archived": True, "view_url": view_url}


def sync_email_archive_from_messages(*, limit: int = 500) -> dict[str, Any]:
    """Copia email_messages (Swarm/notify) → email_archive sin borrar origen."""
    db = _db()
    ensure_email_archive_indexes()
    items = list(db.email_messages.find({}).sort("received_at", -1).limit(max(1, min(limit, 5000))))
    archived = 0
    for doc in items:
        saved = archive_email_message(doc)
        if saved.get("view_url") and doc.get("mail_id"):
            db.email_messages.update_one(
                {"_id": doc.get("_id")},
                {"$set": {"view_url": saved["view_url"], "view_url_updated_at": _now()}},
            )
        archived += 1
    return {
        "ok": True,
        "scanned": len(items),
        "archived": archived,
        "archive_count": db[ARCHIVE_COL].count_documents({}),
        "root": str(ARCHIVE_ROOT),
    }


def search_email_archive(
    query: str | None = None,
    account_address: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    db = _db()
    filt: dict[str, Any] = {}
    if account_address:
        filt["account_address"] = account_address.strip().lower()
    if query:
        q = query.strip()
        # Multi-token: OR de palabras (p.ej. "bright data credits" → bright|credits)
        tokens = [t for t in re.split(r"\s+", q) if len(t) >= 3]
        if len(tokens) > 1:
            filt["$or"] = []
            for tok in tokens[:8]:
                filt["$or"].extend([
                    {"subject": {"$regex": re.escape(tok), "$options": "i"}},
                    {"from_addr": {"$regex": re.escape(tok), "$options": "i"}},
                    {"body_text": {"$regex": re.escape(tok), "$options": "i"}},
                ])
        else:
            filt["$or"] = [
                {"subject": {"$regex": q, "$options": "i"}},
                {"from_addr": {"$regex": q, "$options": "i"}},
                {"body_text": {"$regex": q, "$options": "i"}},
                {"mail_id": q},
                {"message_id": q},
            ]
    rows = list(db[ARCHIVE_COL].find(filt).sort("received_at", -1).limit(max(1, min(limit, 100))))
    for r in rows:
        r["_id"] = str(r["_id"])
    return {"ok": True, "count": len(rows), "messages": rows, "filter": filt}


def get_email_archive_message(mail_id: str, *, refresh_token: bool = True) -> dict[str, Any]:
    """Detalle de un correo archivado + deep link autenticado."""
    db = _db()
    mid = (mail_id or "").strip()
    if not mid:
        return {"ok": False, "error": "mail_id_required"}
    doc = db[ARCHIVE_COL].find_one({"mail_id": mid})
    if not doc:
        return {"ok": False, "error": "not_found", "mail_id": mid}
    doc["_id"] = str(doc["_id"])
    atts = list(db[ATTACH_COL].find({"mail_id": mid}, {"_id": 0}))
    view_url = build_view_url(mid) if refresh_token else (doc.get("view_url") or build_view_url(mid))
    if refresh_token:
        db[ARCHIVE_COL].update_one({"mail_id": mid}, {"$set": {"view_url": view_url, "updated_at": _now()}})
    return {
        "ok": True,
        "message": doc,
        "attachments": atts,
        "view_url": view_url,
        "has_raw_eml": bool(doc.get("has_raw_eml")),
        "note": "Deep link con token HMAC (TTL 24h). .eml completo requiere fetch IMAP futuro.",
    }


def get_email_archive_status() -> dict[str, Any]:
    db = _db()
    with_att = db[ARCHIVE_COL].count_documents({"has_attachment": True})
    with_eml = db[ARCHIVE_COL].count_documents({"has_raw_eml": True})
    with_view = db[ARCHIVE_COL].count_documents({"view_url": {"$type": "string", "$ne": ""}})
    return {
        "ok": True,
        "archive_count": db[ARCHIVE_COL].count_documents({}),
        "attachment_meta_count": db[ATTACH_COL].count_documents({}),
        "with_attachment_flag": with_att,
        "with_raw_eml": with_eml,
        "with_view_url": with_view,
        "source_email_messages": db.email_messages.count_documents({}),
        "root": str(ARCHIVE_ROOT),
        "view_base": _view_base_url(),
        "note": "Metadata+snippet+deep-link OK. Adjuntos .eml reales = fase IMAP fetch.",
    }
