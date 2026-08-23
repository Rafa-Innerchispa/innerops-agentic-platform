"""REST legacy + Centralized Clients API. Integración ChatGPT = MCP :8102 (docs/MCP_CHATGPT.md)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from raphiia_openai.mongo_store import ping_mongo, get_db
from raphiia_openai.operational.quote_delivery import get_delivery_by_ticket, list_quote_deliveries, send_quote_delivery, verify_quote_pdf_token
from raphiia_openai.operational.quote_renderer import render_quote_html, render_tracking_html
from raphiia_openai.settings import MCP_PORT, MCP_PUBLIC_URL, SWARM_API_BASE

router = APIRouter(prefix="/api/v1", tags=["raphiia-openai"])


class QuoteDeliveryRequest(BaseModel):
    quote_ref: str
    channels: list[str] | None = None
    phone: str | None = None
    email: str | None = None
    intro_md: str | None = None


@router.get("/health")
def health():
    return {
        "service": "raphiia-openai",
        "mode": "mcp",
        "mongo": ping_mongo(),
        "swarm_api": SWARM_API_BASE,
        "mcp_local": f"http://127.0.0.1:{MCP_PORT}/mcp",
        "mcp_public_hint": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
        "note": "ChatGPT Connectors → MCP. No usar OpenAI API sk- en este servicio.",
    }


@router.get("/clients/lookup/{client_id}")
def global_client_lookup(client_id: str):
    try:
        db = get_db()
        
        # 1. Check local MongoDB pcdoctor_swarm
        client_doc = db["quote_clients"].find_one({"client_id": client_id}, {"_id": 0})
        if client_doc:
            return {"ok": True, "source": "local_db", "client": client_doc}
        
        # 2. Fallback to SRI mock (centralized lookup)
        from raphiia_openai.sri_validation import lookup_ruc
        sri_res = lookup_ruc(client_id)
        
        # 3. Create client document schema
        client_type = "Persona Natural"
        if len(client_id) == 13 and not client_id.startswith("0") and not client_id.endswith("001"):
            client_type = "Empresa / Jurídica"
        elif len(client_id) == 13 and client_id.endswith("001"):
            # Check if it's natural RUC or company
            client_type = "Persona Natural" if client_id[2] < "9" else "Empresa / Jurídica"

        client_data = {
            "client_name": sri_res.get("name", f"CLIENTE RUC {client_id}"),
            "client_id": client_id,
            "client_type": client_type,
            "entity_id": "ent_pcdoctor",
            "contact": "",
            "business_type": "Otro"
        }
        
        # Register in database automatically if we got a real name
        if sri_res.get("name") and not sri_res.get("name").startswith("CLIENTE RUC"):
            db["quote_clients"].update_one(
                {"client_id": client_id},
                {"$set": client_data},
                upsert=True
            )
        
        return {"ok": True, "source": sri_res.get("source", "sri_mock"), "client": client_data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/quotes/{quote_ref}/document", response_class=HTMLResponse)
def quote_document_html(quote_ref: str):
    """Vista HTML imprimible de cotización — estética alineada a informes PC Doctor."""
    result = render_quote_html(quote_ref)
    if not result.get("ok"):
        return HTMLResponse(f"<h1>Cotización no encontrada</h1><p>{result.get('error')}</p>", status_code=404)
    return HTMLResponse(result["html"])


@router.get("/quotes/track/{ticket_id}", response_class=HTMLResponse)
def quote_tracking_page(ticket_id: str):
    """Seguimiento moderno de cotización — visible por enlace WhatsApp."""
    result = render_tracking_html(ticket_id)
    if not result.get("ok"):
        return HTMLResponse(f"<h1>Referencia no encontrada</h1><p>{result.get('error')}</p>", status_code=404)
    return HTMLResponse(result["html"])


@router.get("/quotes/deliveries")
def quote_deliveries_list(limit: int = 30, status: str | None = None):
    return list_quote_deliveries(limit=limit, status=status)


@router.get("/quotes/delivery/{ticket_id}")
def quote_delivery_status(ticket_id: str):
    return get_delivery_by_ticket(ticket_id)


@router.get("/quotes/pdf/{ticket_id}")
def quote_pdf_download(ticket_id: str, token: str = ""):
    """Descarga segura del PDF de cotización con token temporal."""
    from pathlib import Path

    from html import escape

    delivery = get_delivery_by_ticket(ticket_id)
    if not delivery.get("ok"):
        raise HTTPException(404, delivery.get("error", "ticket not found"))
    check = verify_quote_pdf_token(token, ticket_id=ticket_id)
    if not check.get("ok"):
        raise HTTPException(401, check.get("error", "invalid_token"))
    pdf_path = (delivery.get("delivery") or {}).get("pdf_path") or ""
    if not pdf_path:
        raise HTTPException(404, "pdf not found")
    p = Path(pdf_path)
    allowed = Path("/home/rlopez/data/media/pcdoctor/quotes")
    try:
        p.resolve().relative_to(allowed.resolve())
    except ValueError:
        raise HTTPException(403, "path not allowed")
    if not p.is_file():
        raise HTTPException(404, "pdf not found")
    return FileResponse(p, media_type="application/pdf", filename=escape(p.name))


@router.post("/quotes/delivery")
def quote_delivery_send(body: QuoteDeliveryRequest):
    """Envía cotización con ticket — WhatsApp + email registro."""
    return send_quote_delivery(
        body.quote_ref,
        channels=body.channels,
        phone=body.phone,
        email=body.email,
        intro_md=body.intro_md,
    )


@router.get("/email-archive/{mail_id}", response_class=HTMLResponse)
def email_archive_view(mail_id: str, token: str = ""):
    """Deep link autenticado (HMAC) con detalle y análisis server-rendered."""
    from html import escape

    from raphiia_openai.notifications import email_archive, email_review

    check = email_archive.verify_email_view_token(token)
    if not check.get("ok"):
        return HTMLResponse(
            f"<h1>Enlace no válido</h1><p>{escape(str(check.get('error')))}</p>",
            status_code=401,
        )
    if check.get("mail_id") != mail_id:
        return HTMLResponse("<h1>Token no coincide</h1>", status_code=401)
    result = email_review.get_review(mail_id, hydrate=True)
    if not result.get("ok"):
        return HTMLResponse(f"<h1>No encontrado</h1><p>{escape(mail_id)}</p>", status_code=404)
    msg = result["message"]
    analysis = result.get("analysis") or email_review.analyze_email(msg)
    body = escape((msg.get("body_text") or "")[:30000]).replace("\n", "<br>")
    actions = "".join(
        f"<li>{escape(str(item))}</li>" for item in (analysis.get("suggested_actions") or [])
    )
    attachments = result.get("attachments") or []
    attach_html = "".join(
        f"<li>{escape(str(item.get('filename') or 'adjunto'))} "
        f"({escape(str(item.get('content_type') or 'archivo'))})</li>"
        for item in attachments
    )
    reply_hint = escape(f"responder {mail_id}: escribe aquí tu respuesta")
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{escape(msg.get('subject') or mail_id)}</title>
<style>body{{font-family:system-ui,sans-serif;background:#f5f7fb;color:#152033;margin:0;line-height:1.5}}
main{{max-width:820px;margin:auto;padding:20px}}.card{{background:white;border-radius:14px;padding:18px;margin:12px 0;box-shadow:0 2px 12px #1b2a4112}}
h1{{font-size:1.45rem;margin:.2rem 0}}h2{{font-size:1.05rem}}.meta{{color:#526176;font-size:.9rem}}
.badge{{display:inline-block;background:#e9f0ff;color:#174ea6;border-radius:999px;padding:4px 10px;font-weight:650}}
.body{{overflow-wrap:anywhere}}code{{background:#eef2f8;padding:4px 7px;border-radius:6px}}</style></head><body><main>
<section class=card><span class=badge>{escape(str(analysis.get('priority') or 'normal').upper())}</span>
<h1>{escape(str(analysis.get('subject') or '(sin asunto)'))}</h1>
<p class=meta><strong>De:</strong> {escape(str(msg.get('from_addr') or ''))}<br>
<strong>Cuenta:</strong> {escape(str(msg.get('account_address') or ''))}<br>
<strong>Recibido:</strong> {escape(str(msg.get('received_at') or ''))}<br>
<strong>ID:</strong> {escape(mail_id)}</p></section>
<section class=card><h2>Resumen</h2><p>{escape(str(analysis.get('summary') or ''))}</p>
<h2>Acciones posibles</h2><ul>{actions or '<li>Revisar el mensaje completo</li>'}</ul></section>
<section class=card><h2>Mensaje</h2><div class=body>{body or '<em>(sin cuerpo disponible)</em>'}</div></section>
{f'<section class=card><h2>Adjuntos</h2><ul>{attach_html}</ul></section>' if attach_html else ''}
<section class=card><h2>Responder con confirmación</h2><p>En el chat de RalfIA escribe:</p>
<p><code>{reply_hint}</code></p><p class=meta>RalfIA mostrará una vista previa y solo enviará después de que respondas “sí”.</p></section>
<p class=meta>Archivo privado RalfIA · enlace temporal autenticado</p>
</main>
</body></html>"""
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, private",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )


@router.post("/whatsapp/evolution/webhook")
async def whatsapp_evolution_webhook_v1(payload: dict):
    """Webhook Evolution (respaldo :8099 — principal en portal :2002)."""
    from raphiia_openai import whatsapp_automation

    return whatsapp_automation.ingest_inbound_event(payload)
