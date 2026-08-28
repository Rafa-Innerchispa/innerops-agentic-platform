"""Entrega de cotizaciones — ticket moderno, WhatsApp primario, email registro."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.audit import log_ops_action
from raphiia_openai.operational.constants import (
    COL_OPS_CLIENTS,
    COL_OPS_QUOTE_DELIVERIES,
    COL_OPS_QUOTE_DRAFTS,
)
from raphiia_openai.operational.pcdoctor_store import _serialize, update_quote_draft
from raphiia_openai.operational.quote_renderer import build_quote_context, render_quote_html
from raphiia_openai.settings import MCP_API_KEY, MCP_PUBLIC_URL, RAPHI_IA_PUBLIC_URL
from raphiia_openai.whatsapp_mcp_bridge import send_whatsapp_message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _public_base() -> str:
    return (MCP_PUBLIC_URL or RAPHI_IA_PUBLIC_URL or "http://127.0.0.1:8099").rstrip("/")


_PDF_TOKEN_TTL_SEC = int(os.getenv("QUOTE_PDF_TOKEN_TTL", "86400"))
_PDF_TOKEN_SECRET = os.getenv("QUOTE_PDF_TOKEN_SECRET") or MCP_API_KEY or "ralfia-quote-pdf"


def issue_quote_pdf_token(ticket_id: str, *, quote_ref: str | None = None, ttl_sec: int | None = None) -> str:
    exp = int(datetime.now(timezone.utc).timestamp()) + int(ttl_sec or _PDF_TOKEN_TTL_SEC)
    tid = str(ticket_id).strip()
    qref = str(quote_ref or "").strip()
    payload = f"{tid}:{qref}:{exp}"
    sig = hmac.new(_PDF_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{tid}.{exp}.{sig}"


def verify_quote_pdf_token(token: str, *, ticket_id: str | None = None, quote_ref: str | None = None) -> dict[str, Any]:
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        return {"ok": False, "error": "invalid_token"}
    tid, exp_s, sig = parts
    if ticket_id and tid != ticket_id:
        return {"ok": False, "error": "ticket_mismatch"}
    try:
        exp = int(exp_s)
    except ValueError:
        return {"ok": False, "error": "invalid_exp"}
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return {"ok": False, "error": "token_expired"}
    qref = str(quote_ref or "").strip()
    payload = f"{tid}:{qref}:{exp}"
    expect = hmac.new(_PDF_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(expect, sig):
        return {"ok": False, "error": "bad_signature"}
    return {"ok": True, "ticket_id": tid, "exp": exp}


def build_quote_pdf_download_url(ticket_id: str, *, quote_ref: str | None = None) -> str:
    token = issue_quote_pdf_token(ticket_id, quote_ref=quote_ref)
    return f"{_public_base()}/api/v1/quotes/pdf/{ticket_id}?token={token}"


def _new_ticket_id() -> str:
    """Formato legible: PCD-COT-YYYYMM-XXXX (como tracking moderno por WhatsApp)."""
    now = datetime.now(timezone.utc)
    suffix = secrets.token_hex(2).upper()
    return f"PCD-COT-{now.strftime('%Y%m')}-{suffix}"


def _append_event(doc: dict[str, Any], title: str, detail: str, channel: str = "system") -> dict[str, Any]:
    events = list(doc.get("events") or [])
    events.append({"at": _now_iso(), "title": title, "detail": detail, "channel": channel})
    return {"events": events}


def _ensure_delivery_indexes() -> None:
    db = _db()
    for spec in (
        ([("ticket_id", 1)], {"name": "ux_quote_deliveries_ticket", "unique": True}),
        ([("delivery_id", 1)], {"name": "ux_quote_deliveries_delivery_id", "unique": True}),
        ([("quote_id", 1)], {"name": "ix_quote_deliveries_quote_id"}),
    ):
        try:
            db[COL_OPS_QUOTE_DELIVERIES].create_index(spec[0], **spec[1])
        except Exception:
            continue


def _resolve_quote_ref(quote_ref: str) -> tuple[dict[str, Any] | None, str]:
    """Unifica ref → ops_quote_drafts canónico."""
    from raphiia_openai.operational.quote_unify import resolve_canonical_quote

    resolved = resolve_canonical_quote(quote_ref)
    if not resolved.get("ok"):
        return None, quote_ref
    quote = resolved.get("quote") or {}
    key = resolved.get("canonical_quote_id") or quote_ref
    if quote:
        return quote, key
    db = _db()
    doc = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": key})
    return (_serialize(doc) if doc else None), key


def get_delivery_by_ticket(ticket_id: str) -> dict[str, Any]:
    _ensure_delivery_indexes()
    doc = _db()[COL_OPS_QUOTE_DELIVERIES].find_one({"ticket_id": ticket_id})
    if not doc:
        return {"ok": False, "error": "ticket not found"}
    return {"ok": True, "delivery": _serialize(doc)}


def _persist_intro(quote: dict[str, Any], quote_key: str, intro_md: str) -> None:
    db = _db()
    if quote.get("quote_id") and db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote["quote_id"]}):
        update_quote_draft({"quote_id": quote["quote_id"], "intro_md": intro_md, "scope_summary": intro_md[:280]})
    elif quote.get("quote_number"):
        db["quote_opportunities"].update_one(
            {"quote_number": quote["quote_number"]},
            {"$set": {"solution_summary": intro_md, "updated_at": _now_iso()}},
        )


def _client_phone_email(quote: dict[str, Any], client: dict[str, Any]) -> tuple[str, str]:
    phone = (
        quote.get("client_phone")
        or client.get("phone")
        or client.get("whatsapp")
        or ""
    ).strip()
    email = (quote.get("client_email") or client.get("email") or "").strip()
    if not phone and "@" not in (client.get("contact") or ""):
        contact = (client.get("contact") or quote.get("contact") or "").strip()
        if contact and "@" in contact:
            email = email or contact
        elif contact:
            phone = phone or contact
    return phone, email


def build_whatsapp_message(
    *,
    ticket_id: str,
    client_name: str,
    display_number: str,
    total: float | str,
    tracking_url: str,
    preview_url: str,
    pdf_download_url: str | None = None,
) -> str:
    nl = chr(10)
    download_line = f"⬇️ Descargar PDF: {pdf_download_url}{nl}" if pdf_download_url else ""
    return nl.join([
        f"*PC Doctor · Propuesta comercial*",
        "",
        f"Hola *{client_name}*,",
        "",
        f"Tu cotización *{display_number}* está lista.",
        f"💰 Total: *${float(total):,.2f}*",
        "",
        f"📋 *Seguimiento:* `{ticket_id}`",
        f"🔗 Estado: {tracking_url}",
        f"📄 Ver propuesta: {preview_url}",
        download_line.rstrip(nl),
        f"Responde a este mensaje citando `{ticket_id}` para aprobar, preguntar o solicitar cambios.",
    ])


def build_email_payload(
    *,
    ticket_id: str,
    client_name: str,
    display_number: str,
    email_to: str,
    tracking_url: str,
    preview_url: str,
    pdf_download_url: str | None = None,
) -> dict[str, Any]:
    nl = chr(10)
    subject = f"Propuesta comercial {display_number} — PC Doctor [{ticket_id}]"
    pdf_line = f"Descargar PDF: {pdf_download_url}{nl}" if pdf_download_url else ""
    body = nl.join([
        f"Hola {client_name},",
        "",
        f"Adjuntamos la propuesta comercial {display_number}.",
        "",
        f"Referencia de seguimiento: {ticket_id}",
        f"Ver estado en línea: {tracking_url}",
        f"Ver documento: {preview_url}",
        pdf_line.rstrip(nl),
        "Atentamente,",
        "PC Doctor & InnerSpark",
    ])
    return {"to": email_to, "subject": subject, "body": body, "status": "queued"}


def send_quote_delivery(


    quote_ref: str,
    *,
    channels: list[str] | None = None,
    phone: str | None = None,
    email: str | None = None,
    intro_md: str | None = None,
) -> dict[str, Any]:
    """
    Envía cotización al cliente con ticket de seguimiento.
    Canales: whatsapp (primario), email (registro).
    """
    _ensure_delivery_indexes()
    channels = [c.strip().lower() for c in (channels or ["whatsapp", "email"])]
    quote, quote_key = _resolve_quote_ref(quote_ref)
    if not quote:
        return {"ok": False, "error": "quote not found"}

    ctx = build_quote_context(quote_key)
    if not ctx.get("ok"):
        return ctx

    if intro_md:
        _persist_intro(quote, quote_key, intro_md)

    client = ctx["client"]
    client_name = client.get("display_name") or quote.get("client_name") or "Cliente"
    target_phone, target_email = _client_phone_email(quote, client)
    if phone:
        target_phone = phone.strip()
    if email:
        target_email = email.strip()

    ticket_id = _new_ticket_id()
    delivery_id = f"delivery_{ticket_id.lower().replace('-', '_')}"
    base = _public_base()
    tracking_url = f"{base}/api/v1/quotes/track/{ticket_id}"
    preview_url = f"{base}/api/v1/quotes/{quote_key}/document"
    display_number = ctx["display_number"]
    total = ctx["quote"].get("total") or ctx["quote"].get("subtotal") or 0

    from raphiia_openai.operational.quote_pdf import generate_quote_pdf

    pdf_result = generate_quote_pdf(quote_key, ticket_id=ticket_id)
    pdf_path = pdf_result.get("pdf_path") if pdf_result.get("ok") else None
    pdf_download_url = build_quote_pdf_download_url(ticket_id=ticket_id, quote_ref=quote_key)

    now = _now_iso()
    delivery_doc: dict[str, Any] = {
        "delivery_id": delivery_id,
        "ticket_id": ticket_id,
        "quote_id": quote_key,
        "display_number": display_number,
        "client_id": quote.get("client_id") or client.get("client_id"),
        "client_name": client_name,
        "status": "sent",
        "channels_requested": channels,
        "whatsapp_number": target_phone,
        "email": target_email,
        "tracking_url": tracking_url,
        "preview_url": preview_url,
        "pdf_download_url": pdf_download_url,
        "pdf_path": pdf_path,
        "events": [
            {"at": now, "title": "Cotización registrada", "detail": f"Ticket {ticket_id} creado", "channel": "system"},
        ],
        "created_at": now,
        "updated_at": now,
    }

    results: dict[str, Any] = {}

    if "whatsapp" in channels:
        if not target_phone:
            results["whatsapp"] = {"ok": False, "error": "client phone required"}
            delivery_doc["events"].append(
                {"at": _now_iso(), "title": "WhatsApp pendiente", "detail": "Sin número de cliente", "channel": "whatsapp"}
            )
        else:
            wa_text = build_whatsapp_message(
                ticket_id=ticket_id,
                client_name=client_name,
                display_number=display_number,
                total=total,
                tracking_url=tracking_url,
                preview_url=preview_url,
                pdf_download_url=pdf_download_url,
            )
            wa_result = send_whatsapp_message(wa_text, number=target_phone)
            results["whatsapp"] = wa_result
            if wa_result.get("ok"):
                delivery_doc["events"].append(
                    {"at": _now_iso(), "title": "Enviado por WhatsApp", "detail": f"A {target_phone}", "channel": "whatsapp"}
                )
                if pdf_path:
                    from raphiia_openai.whatsapp_mcp_bridge import send_whatsapp_document

                    doc_res = send_whatsapp_document(
                        pdf_path,
                        number=target_phone,
                        caption=f"Propuesta {display_number} — Ref {ticket_id}",
                    )
                    results["whatsapp_pdf"] = doc_res
                    if doc_res.get("ok"):
                        delivery_doc["events"].append(
                            {"at": _now_iso(), "title": "PDF enviado por WhatsApp", "detail": pdf_path, "channel": "whatsapp"}
                        )
            else:
                delivery_doc["events"].append(
                    {"at": _now_iso(), "title": "Fallo WhatsApp", "detail": str(wa_result.get("error") or wa_result), "channel": "whatsapp"}
                )

    if "email" in channels:
        if not target_email:
            results["email"] = {"ok": False, "error": "client email required", "status": "skipped"}
        else:
            payload = build_email_payload(
                ticket_id=ticket_id,
                client_name=client_name,
                display_number=display_number,
                email_to=target_email,
                tracking_url=tracking_url,
                preview_url=preview_url,
                pdf_download_url=pdf_download_url,
            )
            from raphiia_openai.notifications.email_client import send_email

            mail_res = send_email(
                to_addr=target_email,
                subject=payload["subject"],
                body=payload["body"],
                attachment_path=pdf_path,
                attachment_name=pdf_result.get("pdf_filename") if pdf_result.get("ok") else None,
            )
            payload["send_result"] = mail_res
            payload["queued_at"] = _now_iso()
            payload["status"] = "sent" if mail_res.get("ok") else "queued"
            delivery_doc["email_payload"] = payload
            results["email"] = mail_res if mail_res.get("ok") else {"ok": False, "status": "queued", "payload": payload, "error": mail_res.get("error")}
            delivery_doc["events"].append(
                {"at": _now_iso(), "title": "Correo enviado" if mail_res.get("ok") else "Correo en cola", "detail": f"Para {target_email}", "channel": "email"}
            )

    delivery_doc["channel_results"] = results
    delivery_doc["updated_at"] = _now_iso()
    _db()[COL_OPS_QUOTE_DELIVERIES].insert_one(delivery_doc)

    if quote.get("quote_id") and _db()[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote["quote_id"]}):
        update_quote_draft({
            "quote_id": quote["quote_id"],
            "status": "sent",
            "ticket_id": ticket_id,
            "sent_at": now,
        })
    elif quote.get("quote_number"):
        _db()["quote_opportunities"].update_one(
            {"quote_number": quote["quote_number"]},
            {"$set": {"status": "sent", "ticket_id": ticket_id, "sent_at": now}},
        )

    log_ops_action(
        actor="CHATGPT",
        action="send_quote_delivery",
        resource_type="quote_delivery",
        resource_id=delivery_id,
        summary=f"Quote {display_number} → ticket {ticket_id}",
        tool_used="send_quote_delivery",
        metadata={"channels": channels, "ticket_id": ticket_id},
    )

    html_result = render_quote_html(quote_key, ticket_id=ticket_id)
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "delivery_id": delivery_id,
        "tracking_url": tracking_url,
        "preview_url": preview_url,
        "pdf_download_url": pdf_download_url,
        "channel_results": results,
        "whatsapp_message_preview": build_whatsapp_message(
            ticket_id=ticket_id,
            client_name=client_name,
            display_number=display_number,
            total=total,
            tracking_url=tracking_url,
            preview_url=preview_url,
            pdf_download_url=pdf_download_url,
        ),
        "document_html_available": bool(html_result.get("html")),
    }


def generate_quote_intro(quote_ref: str, *, visit_id: str | None = None) -> dict[str, Any]:
    """
    Genera introducción narrativa para cotización (no informe técnico completo).
    Resume contexto para que el cliente entienda qué se cotiza.
    """
    from raphiia_openai import local_model_router

    quote, quote_key = _resolve_quote_ref(quote_ref)
    if not quote:
        return {"ok": False, "error": "quote not found"}

    ctx = build_quote_context(quote_key)
    client = ctx.get("client") or {}
    payload = {
        "task": "quote_intro",
        "client": client.get("display_name"),
        "project": quote.get("title") or ctx.get("site", {}).get("name"),
        "line_items": (quote.get("line_items") or [])[:8],
        "notes": quote.get("notes"),
        "visit_id": visit_id or quote.get("visit_id"),
    }
    prompt = (
        "Redacta una INTRODUCCIÓN COMERCIAL breve (máx 180 palabras) para una cotización. "
        "Explica en lenguaje claro qué se propone y por qué, sin jerga excesiva. "
        "NO es un informe técnico de campo — no listes hallazgos detallados ni procedimientos. "
        "Usa 2-3 párrafos cortos o viñetas. Español Ecuador.\n\n"
        f"Datos: {payload}"
    )
    model_result = local_model_router.run_local_model(
        task_type="quote_intro",
        prompt=prompt,
        max_tokens=400,
        temperature=0.3,
    )
    if model_result.get("ok"):
        intro_md = (model_result.get("response") or "").strip()
    else:
        items = quote.get("line_items") or []
        names = ", ".join((it.get("description") or it.get("name") or "servicio") for it in items[:3])
        intro_md = (
            f"Presentamos esta propuesta para *{client.get('display_name') or 'su empresa'}*, "
            f"orientada a {quote.get('title') or 'sus necesidades tecnológicas'}.\n\n"
            f"Incluye: {names or 'servicios y equipamiento acordados'}."
        )

    if quote.get("quote_id") and _db()[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote["quote_id"]}):
        update_quote_draft({"quote_id": quote["quote_id"], "intro_md": intro_md, "scope_summary": intro_md[:280]})
    elif quote.get("quote_number"):
        _db()["quote_opportunities"].update_one(
            {"quote_number": quote["quote_number"]},
            {"$set": {"solution_summary": intro_md, "updated_at": _now_iso()}},
        )

    return {"ok": True, "quote_id": quote_key, "intro_md": intro_md, "model": model_result.get("model")}


def update_delivery_status(ticket_id: str, status: str, detail: str = "") -> dict[str, Any]:
    allowed = {"sent", "viewed", "accepted", "rejected", "expired", "follow_up"}
    if status not in allowed:
        return {"ok": False, "error": f"status must be one of {sorted(allowed)}"}
    doc = _db()[COL_OPS_QUOTE_DELIVERIES].find_one({"ticket_id": ticket_id})
    if not doc:
        return {"ok": False, "error": "ticket not found"}
    patch = _append_event(doc, f"Estado: {status}", detail or status)
    patch["status"] = status
    patch["updated_at"] = _now_iso()
    _db()[COL_OPS_QUOTE_DELIVERIES].update_one({"_id": doc["_id"]}, {"$set": patch})
    updated = _db()[COL_OPS_QUOTE_DELIVERIES].find_one({"_id": doc["_id"]})
    return {"ok": True, "delivery": _serialize(updated)}


def list_quote_deliveries(limit: int = 30, status: str | None = None) -> dict[str, Any]:
    _ensure_delivery_indexes()
    filt: dict[str, Any] = {}
    if status:
        filt["status"] = status
    items = list(
        _db()[COL_OPS_QUOTE_DELIVERIES]
        .find(filt, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 100)))
    )
    return {"ok": True, "count": len(items), "deliveries": items}
