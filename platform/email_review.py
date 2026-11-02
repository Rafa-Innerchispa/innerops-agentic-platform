"""Review, hydrate and reply to monitored email without exposing credentials."""

from __future__ import annotations

import hashlib
import html
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.notifications.email_classifier import classify_email

REPLY_AUDIT_COL = "ralfia_email_reply_audit"
MAX_RAW_BYTES = 10 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _email_settings() -> dict[str, Any]:
    doc = mongo_store.get_db().email_settings.find_one({"_id": "global"}) or {}
    return doc


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _plain(value: str) -> str:
    text = html.unescape(str(value or ""))
    # CSS / estilos inline que confunden resúmenes WhatsApp
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"\{[^{}]*\}", " ", text)
    text = re.sub(r"\.[a-z0-9_-]+\s*\{[^}]*\}", " ", text, flags=re.I)
    if "<" in text and ">" in text:
        parser = _HTMLText()
        try:
            parser.feed(text)
            text = " ".join(parser.parts)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sentences(value: str) -> list[str]:
    text = _plain(value)
    parts = re.split(r"(?<=[.!?])\s+|\s*[|•]\s*", text)
    ignored = re.compile(
        r"unsubscribe|desuscrib|view in browser|pol[ií]tica de privacidad|font-family|font-size|"
        r"background-image|\.style\d|body\s*\{|margin:\s*0",
        re.I,
    )
    return [part.strip() for part in parts if len(part.strip()) >= 18 and not ignored.search(part)][:6]


def analyze_email(doc: dict[str, Any]) -> dict[str, Any]:
    settings = _email_settings()
    cl = classify_email(
        doc,
        extra_keywords=list(settings.get("keywords_important") or []),
        extra_domains=list(settings.get("trusted_domains") or []),
    )
    subject = _plain(str(doc.get("subject") or "(sin asunto)"))[:240]
    content = _plain(str(doc.get("body_text") or doc.get("snippet") or ""))
    category = cl["category"]
    priority = cl["priority"]
    reply_recommended = priority in ("high", "normal") and category not in (
        "marketing",
        "security_code",
        "delivery_failure",
    )

    actions_map = {
        "factura": ["Validar importe, fecha y contraparte", "Registrar en Contifico si aplica"],
        "pago": ["Validar importe y vencimiento", "Registrar compromiso de pago"],
        "transferencia": ["Verificar monto y cuenta origen/destino", "Conciliar con extracto"],
        "extracto": ["Revisar movimientos del periodo", "Conciliar contabilidad"],
        "sri_fiscal": ["Revisar comprobante SRI", "Contabilidad / retenciones"],
        "fiscal_us": ["Revisar aviso fiscal IRS", "Consultar contador si aplica"],
        "incidente": ["Confirmar recepción", "Asignar responsable"],
        "cotizacion": ["Revisar cotización/proforma", "Responder al cliente"],
        "delivery_failure": ["Verificar dirección", "Reenviar correo corregido"],
        "servicio_vencimiento": ["Renovar servicio o pagar antes de suspensión", "Verificar factura hosting/dominio"],
        "trusted_sender": ["Revisar remitente de confianza", "Actuar si requiere respuesta"],
        "marketing": ["Archivar", "Desuscribir si es repetitivo"],
        "security_code": ["Usar código solo si tú lo solicitaste", "Ignorar si no lo reconoces"],
    }
    actions = actions_map.get(category, ["Revisar el mensaje completo", "Responder si requiere seguimiento"])

    sentences = _sentences(content)
    if sentences:
        summary = " ".join(sentences[:2])[:520]
    elif content:
        summary = content[:520]
    else:
        summary = f"Correo con asunto «{subject}»; el cuerpo completo todavía no está disponible."

    return {
        "subject": subject,
        "summary": summary,
        "category": category,
        "priority": priority,
        "alert": bool(cl.get("alert")),
        "reason": cl.get("reason", ""),
        "reply_recommended": reply_recommended,
        "suggested_actions": actions,
        "analyzed_at": _now(),
        "analysis_source": cl.get("analysis_source", "email_classifier_v3"),
    }


def _extract_body(message) -> tuple[str, list[dict[str, Any]]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    for part in message.walk() if message.is_multipart() else [message]:
        disposition = str(part.get_content_disposition() or "")
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                {
                    "filename": filename or "attachment",
                    "content_type": part.get_content_type(),
                    "size": len(payload),
                }
            )
            continue
        if part.get_content_maintype() != "text":
            continue
        try:
            value = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            value = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_subtype() == "plain":
            plain_parts.append(str(value))
        elif part.get_content_subtype() == "html":
            html_parts.append(str(value))
    selected = "\n".join(plain_parts) if plain_parts else "\n".join(html_parts)
    return _plain(selected)[:50000], attachments


def hydrate_email(mail_id: str) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive

    db = mongo_store.get_db()
    source = db.email_messages.find_one({"mail_id": str(mail_id).strip()})
    if not source:
        return {"ok": False, "error": "email_not_found"}
    archived = db[email_archive.ARCHIVE_COL].find_one({"mail_id": mail_id}) or {}
    if archived.get("has_raw_eml") and len(str(archived.get("body_text") or "")) >= 80:
        return {"ok": True, "hydrated": False, "reason": "already_hydrated"}
    account = db.email_accounts.find_one(
        {"email_account_id": source.get("email_account_id")}
    ) or db.email_accounts.find_one({"address": source.get("account_address")})
    if not account or not source.get("uid"):
        email_archive.archive_email_message(source)
        return {"ok": False, "error": "imap_source_incomplete"}
    host = str(account.get("imap_host") or "").strip()
    user = str(account.get("imap_user") or account.get("address") or "").strip()
    password = str(account.get("imap_password") or "")
    port = int(account.get("imap_port") or 993)
    folder = str(account.get("imap_folder") or "INBOX")
    client = None
    try:
        client = imaplib.IMAP4_SSL(host, port, timeout=30)
        client.login(user, password)
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            return {"ok": False, "error": "imap_folder_unavailable"}
        status, data = client.uid("fetch", str(source["uid"]), "(RFC822)")
        if status != "OK" or not data:
            return {"ok": False, "error": "imap_message_unavailable"}
        raw = next((item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)), b"")
        if not raw or len(raw) > MAX_RAW_BYTES:
            return {"ok": False, "error": "email_size_invalid", "size": len(raw)}
        message = BytesParser(policy=policy.default).parsebytes(raw)
        body, attachments = _extract_body(message)
        enriched = {**source, "attachments": attachments}
        saved = email_archive.archive_email_message(enriched, body_text=body, raw_eml=raw)
        db.email_messages.update_one(
            {"mail_id": mail_id},
            {"$set": {"body_text": body, "attachment_count": len(attachments), "hydrated_at": _now()}},
        )
        return {"ok": True, "hydrated": True, "body_length": len(body), "attachments": len(attachments), "archive": saved}
    except Exception as exc:
        return {"ok": False, "error": "imap_fetch_failed", "detail": str(exc)[:180]}
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def get_review(mail_id: str, *, hydrate: bool = True) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive

    db = mongo_store.get_db()
    if hydrate:
        hydrate_email(mail_id)
    if not db[email_archive.ARCHIVE_COL].find_one({"mail_id": mail_id}, {"_id": 1}):
        source = db.email_messages.find_one({"mail_id": mail_id})
        if source:
            email_archive.archive_email_message(source)
    result = email_archive.get_email_archive_message(mail_id)
    if not result.get("ok"):
        return result
    message = result["message"]
    analysis = analyze_email(message)
    db[email_archive.ARCHIVE_COL].update_one({"mail_id": mail_id}, {"$set": {"review": analysis}})
    db.email_messages.update_one({"mail_id": mail_id}, {"$set": {"ralfia_review": analysis}})
    return {**result, "analysis": analysis}


def list_reviews(limit: int = 5, *, priority: str | None = None) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if priority:
        filt["ralfia_review.priority"] = priority
    rows = list(db.email_messages.find(filt, {"_id": 0}).sort("received_at", -1).limit(max(1, min(limit, 50))))
    out = []
    for row in rows:
        analysis = row.get("ralfia_review") or analyze_email(row)
        out.append({"message": row, "analysis": analysis})
    return out


def format_review_text(review: dict[str, Any]) -> str:
    from raphiia_openai.notifications import email_archive

    message = review.get("message") or {}
    analysis = review.get("analysis") or analyze_email(message)
    mail_id = str(message.get("mail_id") or "")
    raw_subject = _plain(str(message.get("subject") or analysis.get("subject") or "(sin asunto)"))[:200]
    actions = "\n".join(f"• {item}" for item in analysis.get("suggested_actions") or [])
    reply_hint = f"\nResponder: *responder {mail_id}: tu mensaje*" if analysis.get("reply_recommended") else ""
    reason = analysis.get("reason") or ""
    routing = analysis.get("routing") or {}
    security = analysis.get("security") or {}
    route_line = ""
    if routing.get("agent_id"):
        route_line = (
            f"\n*Enrutar:* {routing.get('agent_id')} → {routing.get('module')}\n"
            f"*Siguiente:* {routing.get('next_step')}\n"
        )
    sec_line = ""
    if security.get("verdict") and security.get("verdict") != "allow_safe":
        sec_line = f"\n*Seguridad:* {security.get('verdict').upper()} — no abrir adjuntos sin revisar\n"
    summary = _plain(str(analysis.get("summary") or ""))
    if not summary or re.search(r"font-family|\.style|background\s*\{", summary, re.I):
        sentences = _sentences(str(message.get("body_text") or message.get("snippet") or ""))
        summary = sentences[0][:280] if sentences else f"Correo de {str(message.get('from_addr') or '')[:60]}"
    view_url = review.get("view_url") or (email_archive.build_view_url(mail_id) if mail_id else "")
    return (
        f"*Correo · {analysis.get('priority', 'normal').upper()} · {analysis.get('category', 'general')}*\n"
        f"*Asunto:* {raw_subject}\n"
        f"*De:* {str(message.get('from_addr') or '')[:120]}\n"
        f"*Cuenta:* {str(message.get('account_address') or '')[:60]}\n"
        f"*Motivo:* {reason[:120]}\n"
        f"{sec_line}{route_line}\n"
        f"*Resumen:* {summary[:400]}\n\n"
        f"*Acciones:*\n{actions}"
        f"{reply_hint}\n"
        f"📎 Ver completo: {view_url}\n"
        f"ID: `{mail_id}`"
    )[:3800]


def format_inbox_text(limit: int = 5) -> str:
    rows = list_reviews(limit)
    lines = ["*RalfIA · Revisión de correos*", ""]
    for item in rows:
        message, analysis = item["message"], item["analysis"]
        lines.extend(
            [
                f"*{analysis['subject']}*",
                f"{analysis['priority'].upper()} · {analysis['category']} · {analysis['summary'][:200]}",
                f"ID: `{message.get('mail_id')}` · escribe *correo {message.get('mail_id')}*",
                "",
            ]
        )
    return "\n".join(lines)[:3800]


def prepare_reply(mail_id: str, body: str) -> dict[str, Any]:
    review = get_review(mail_id, hydrate=True)
    if not review.get("ok"):
        return review
    message = review["message"]
    to_addr = parseaddr(str(message.get("from_addr") or ""))[1].strip().lower()
    clean_body = str(body or "").strip()
    if not to_addr or "@" not in to_addr:
        return {"ok": False, "error": "reply_address_unavailable"}
    if not clean_body:
        return {"ok": False, "error": "reply_body_required"}
    subject = re.sub(r"[\r\n]+", " ", str(message.get("subject") or "")).strip()
    if not re.match(r"^re\s*:", subject, re.I):
        subject = f"Re: {subject or mail_id}"
    payload = {
        "mail_id": mail_id,
        "to_addr": to_addr,
        "subject": subject[:200],
        "body": clean_body[:4000],
        "from_account": message.get("account_address"),
    }
    return {
        "ok": True,
        "payload": payload,
        "preview": (
            f"Voy a responder el correo *{message.get('subject') or mail_id}*.\n"
            f"Respuesta: “{clean_body[:700]}”\n\n"
            "¿Confirmas el envío? Responde *sí* o *no*."
        ),
    }


def send_reply(payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    from raphiia_openai.notifications.email_client import send_email

    result = send_email(
        to_addr=str(payload.get("to_addr") or ""),
        subject=str(payload.get("subject") or ""),
        body=str(payload.get("body") or ""),
        from_account=str(payload.get("from_account") or "") or None,
    )
    audit = {
        "action": "email_reply_sent" if result.get("ok") else "email_reply_failed",
        "mail_id": payload.get("mail_id"),
        "actor": actor,
        "recipient_hash": hashlib.sha256(str(payload.get("to_addr") or "").encode()).hexdigest()[:16],
        "body_hash": hashlib.sha256(str(payload.get("body") or "").encode()).hexdigest(),
        "body_length": len(str(payload.get("body") or "")),
        "ok": bool(result.get("ok")),
        "error": str(result.get("error") or "")[:180],
        "at": _now(),
    }
    mongo_store.get_db()[REPLY_AUDIT_COL].insert_one(audit)
    if result.get("ok"):
        mongo_store.get_db().email_messages.update_one(
            {"mail_id": payload.get("mail_id")},
            {"$set": {"reply_status": "sent", "replied_at": _now()}},
        )
    return result


def _should_alert(row: dict[str, Any], analysis: dict[str, Any]) -> bool:
    if not analysis.get("alert") and analysis.get("priority") != "high":
        return False
    if row.get("whatsapp_sent") or row.get("ralfia_review_notified_at"):
        return False
    if str(row.get("importance") or "").lower() == "baja" and analysis.get("category") == "marketing":
        return False
    return analysis.get("priority") == "high" and analysis.get("alert", True)


def backfill_inbox_reviews(
    *,
    limit: int = 2000,
    send_alerts: bool = False,
    alert_max_age_days: int = 14,
    reanalyze: bool = True,
) -> dict[str, Any]:
    """Re-clasifica correos en Mongo; alertas opcionales solo para high no notificados."""
    from raphiia_openai.notifications import email_archive
    from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
    from raphiia_openai import whatsapp_identity

    email_archive.sync_email_archive_from_messages(limit=limit)
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if not reanalyze:
        filt["ralfia_review.analysis_source"] = {"$ne": "email_classifier_v3"}
    rows = list(db.email_messages.find(filt, {"_id": 0}).sort("received_at", -1).limit(max(1, min(limit, 5000))))
    stats = {"reviewed": 0, "high": 0, "low": 0, "normal": 0, "alerts_sent": 0, "routed": 0, "captured": 0, "blocked": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=alert_max_age_days)
    destinations = whatsapp_identity.notification_destinations()
    route_high_normal = True

    for row in rows:
        analysis = analyze_email(row)
        should_intel = route_high_normal and (
            analysis.get("priority") in ("high", "normal")
            and analysis.get("category") not in ("marketing", "security_code")
        ) or bool(row.get("has_attachment"))
        if should_intel:
            try:
                from raphiia_openai.notifications import email_router

                intel = email_router.process_email_intelligence(row, create_task=True, analysis=analysis)
                analysis = intel.get("analysis") or analysis
                if intel.get("security_verdict") == "block":
                    stats["blocked"] += 1
                if intel.get("capture", {}).get("captured"):
                    stats["captured"] += 1
                if intel.get("action", {}).get("ok"):
                    stats["routed"] += 1
            except Exception:
                pass
        stats["reviewed"] += 1
        stats[analysis["priority"]] = stats.get(analysis["priority"], 0) + 1
        db.email_messages.update_one({"mail_id": row.get("mail_id")}, {"$set": {"ralfia_review": analysis}})
        mail_id = str(row.get("mail_id") or "")
        if mail_id:
            db[email_archive.ARCHIVE_COL].update_one(
                {"mail_id": mail_id}, {"$set": {"review": analysis}}, upsert=False
            )
        if not send_alerts or not _should_alert(row, analysis):
            continue
        received = row.get("received_at")
        if isinstance(received, datetime) and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        if isinstance(received, datetime) and received < cutoff:
            continue
        review = get_review(mail_id, hydrate=False) if mail_id else {"message": row, "analysis": analysis}
        text = format_review_text(review)
        delivered = any(
            bool(send_alert_whatsapp(text, number=number).get("ok"))
            for number in destinations[:1]
        )
        if delivered and mail_id:
            stats["alerts_sent"] += 1
            db.email_messages.update_one(
                {"mail_id": mail_id},
                {"$set": {"ralfia_review_notified_at": _now(), "whatsapp_sent": True}},
            )
    return {"ok": True, **stats}


def process_new_messages(*, started_at: datetime, new_count: int) -> dict[str, Any]:
    from raphiia_openai.notifications import email_archive
    from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
    from raphiia_openai import whatsapp_identity

    email_archive.sync_email_archive_from_messages(limit=500)
    if new_count <= 0:
        return {"ok": True, "reviewed": 0, "alerts_sent": 0}
    cutoff = started_at - timedelta(minutes=30)
    rows = list(
        mongo_store.get_db().email_messages.find(
            {
                "received_at": {"$gte": cutoff},
                "ralfia_review_notified_at": {"$exists": False},
                "whatsapp_sent": {"$ne": True},
            }
        ).sort("received_at", -1).limit(min(max(new_count, 1), 100))
    )
    alerts = 0
    destinations = whatsapp_identity.notification_destinations()
    for row in rows:
        try:
            from raphiia_openai.notifications import email_router

            intel = email_router.process_email_intelligence(row, create_task=True)
            analysis = intel.get("analysis") or analyze_email(row)
        except Exception:
            analysis = analyze_email(row)
        mongo_store.get_db().email_messages.update_one(
            {"mail_id": row.get("mail_id")}, {"$set": {"ralfia_review": analysis}}
        )
        if not _should_alert(row, analysis):
            continue
        review = get_review(str(row.get("mail_id")), hydrate=False)
        text = format_review_text(review)
        delivered = any(
            bool(send_alert_whatsapp(text, number=number).get("ok"))
            for number in destinations[:1]
        )
        if delivered:
            alerts += 1
            mongo_store.get_db().email_messages.update_one(
                {"mail_id": row.get("mail_id")},
                {"$set": {"ralfia_review_notified_at": _now(), "whatsapp_sent": True}},
            )
    return {"ok": True, "reviewed": len(rows), "alerts_sent": alerts}
