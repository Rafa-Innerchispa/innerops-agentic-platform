"""Renderizado HTML de cotizaciones basado en el motor documental compartido."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.constants import COL_OPS_CLIENTS, COL_OPS_QUOTE_DRAFTS, COL_OPS_SITES
from raphiia_openai.operational.document_engine import (
    build_document_html,
    build_document_number,
    document_kind_label,
    normalize_tax_rate,
    resolve_entity_theme,
)
from raphiia_openai.operational.pcdoctor_store import _serialize
from raphiia_openai.settings import MCP_PUBLIC_URL, RAPHI_IA_PUBLIC_URL

ENTITY_BRANDING: dict[str, dict[str, str]] = {
    "ent_pcdoctor": resolve_entity_theme("ent_pcdoctor"),
    "ent_innerspark": resolve_entity_theme("ent_innerspark"),
    "ent_domotika": resolve_entity_theme("ent_domotika"),
    "default": resolve_entity_theme("default"),
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _resolve_client(quote: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    client_id = quote.get("client_id") or ""
    if client_id:
        doc = db[COL_OPS_CLIENTS].find_one({"client_id": client_id})
        if doc:
            return _serialize(doc)
        legacy = db["quote_clients"].find_one({"client_id": client_id}, {"_id": 0})
        if legacy:
            return {
                "display_name": legacy.get("client_name"),
                "tax_id": legacy.get("client_id"),
                "email": legacy.get("contact", ""),
                "phone": legacy.get("contact", ""),
            }
    return {
        "display_name": quote.get("client_name") or "Cliente",
        "tax_id": quote.get("client_tax_id") or client_id,
        "email": quote.get("client_email") or "",
        "phone": quote.get("client_phone") or "",
        "address": quote.get("client_address") or "",
        "city": quote.get("client_city") or "",
    }


def _resolve_site(quote: dict[str, Any]) -> dict[str, Any]:
    site_id = quote.get("site_id")
    if not site_id:
        return {}
    db = mongo_store.get_db()
    doc = db[COL_OPS_SITES].find_one({"site_id": site_id})
    return _serialize(doc) if doc else {}


def build_quote_context(quote_id: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    quote = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": quote_id})
    if not quote:
        quote = db["quote_opportunities"].find_one({"quote_number": quote_id})
        if quote:
            quote = _quote_opportunity_to_draft_shape(quote)
    if not quote:
        return {"ok": False, "error": "quote not found"}
    client = _resolve_client(quote)
    site = _resolve_site(quote)
    entity_id = quote.get("entity_id") or "ent_pcdoctor"
    brand = ENTITY_BRANDING.get(entity_id, ENTITY_BRANDING["default"])
    display_number = (
        quote.get("display_number")
        or quote.get("quote_number")
        or quote.get("quote_id", "")
    )
    intro = quote.get("intro_md") or quote.get("scope_summary") or quote.get("notes") or ""
    ticket_id = quote.get("ticket_id") or ""
    tracking_url = ""
    if ticket_id:
        base = (MCP_PUBLIC_URL or RAPHI_IA_PUBLIC_URL or "").rstrip("/")
        tracking_url = f"{base}/api/v1/quotes/track/{ticket_id}"
    return {
        "ok": True,
        "quote": _serialize(quote),
        "client": client,
        "site": site,
        "brand": brand,
        "entity_id": entity_id,
        "display_number": display_number,
        "intro_html": intro,
        "ticket_id": ticket_id,
        "tracking_url": tracking_url,
    }


def _quote_opportunity_to_draft_shape(doc: dict[str, Any]) -> dict[str, Any]:
    items = doc.get("items") or []
    line_items = [
        {
            "description": it.get("name") or it.get("description") or "Ítem",
            "quantity": it.get("quantity", 1),
            "unit_price": it.get("price", 0),
            "total": it.get("total", 0),
        }
        for it in items
    ]
    return {
        "quote_id": doc.get("quote_number"),
        "display_number": doc.get("quote_number"),
        "client_id": doc.get("client_id"),
        "client_name": doc.get("client_name"),
        "title": doc.get("description") or "Propuesta comercial",
        "intro_md": doc.get("solution_summary") or doc.get("diagnosis") or "",
        "entity_id": doc.get("entity_id") or "ent_innerspark",
        "line_items": line_items,
        "subtotal": doc.get("total_amount"),
        "total": doc.get("total_amount"),
        "currency": "USD",
        "tax_rate": 0,
        "tax": 0,
        "valid_until": doc.get("valid_until"),
        "created_at": doc.get("created_at"),
        "status": doc.get("status", "draft"),
    }


def _quote_spec(ctx: dict[str, Any], *, ticket_id: str | None = None) -> dict[str, Any]:
    quote = ctx["quote"]
    client = ctx["client"]
    site = ctx["site"]
    line_items = quote.get("line_items") or []
    tax_rate = normalize_tax_rate(quote.get("tax_rate") or 0)
    subtotal = 0.0
    table_rows = []
    for idx, item in enumerate(line_items, start=1):
        qty = float(item.get("quantity", 1) or 1)
        unit = float(item.get("unit_price", item.get("price", 0)) or 0)
        line_total = round(qty * unit, 2)
        subtotal += line_total
        table_rows.append({
            "idx": idx,
            "description": item.get("description") or item.get("name") or f"Ítem {idx}",
            "quantity": qty,
            "unit_price": unit,
            "total": round(float(item.get("total") or line_total), 2),
        })
    subtotal = round(float(quote.get("subtotal") or subtotal), 2)
    tax = round(float(quote.get("tax") or (subtotal * tax_rate)), 2)
    total = round(float(quote.get("total") or (subtotal + tax)), 2)
    document_number = ctx["display_number"] or quote.get("quote_id") or ""
    total_rows = [
        {"label": "Subtotal", "value": subtotal},
    ]
    if tax:
        total_rows.append({"label": f"IVA ({tax_rate * 100:g}%)", "value": tax})
    total_rows.append({"label": "Total", "value": total, "strong": True})
    commercial = quote.get("commercial_terms") or {}
    if not commercial:
        commercial = {
            "seller_name": quote.get("seller_name") or "Héctor José Mejías Rosales",
            "payment_terms": quote.get("payment_terms") or "60% anticipo y 40% contra entrega",
            "warranty": quote.get("warranty") or "1 año equipos · 1 mes instalación",
            "validity": quote.get("validity_text") or (f"{quote.get('valid_until', '')} (10 días calendario)" if quote.get("valid_until") else "10 días calendario"),
            "includes": quote.get("scope_includes") or [],
            "excludes": quote.get("scope_excludes") or [],
        }
    return {
        "document_type": "quote",
        "entity_id": ctx.get("entity_id") or quote.get("entity_id") or "ent_pcdoctor",
        "document_number": document_number,
        "display_number": document_number,
        "title": quote.get("title") or "Cotización",
        "status": quote.get("status", "draft"),
        "issued_at": quote.get("issued_at") or quote.get("created_at"),
        "valid_until": quote.get("valid_until"),
        "currency": quote.get("currency") or "USD",
        "tax_rate": tax_rate,
        "client": client,
        "site": site,
        "summary_md": quote.get("intro_md") or quote.get("scope_summary") or quote.get("notes") or "",
        "table_title": "Detalle comercial",
        "table": {
            "columns": [
                {"key": "idx", "title": "#", "width": "5%", "align": "right", "kind": "number"},
                {"key": "description", "title": "Ítem / Descripción", "width": "47%"},
                {"key": "quantity", "title": "Cant.", "width": "10%", "align": "right", "kind": "quantity"},
                {"key": "unit_price", "title": "Precio", "width": "18%", "align": "right", "kind": "money"},
                {"key": "total", "title": "Subtotal", "width": "20%", "align": "right", "kind": "money"},
            ],
            "rows": table_rows,
        },
        "totals": total_rows,
        "commercial_terms": commercial,
        "sections": [],
        "appendices": [],
        "ticket_id": ticket_id or ctx.get("ticket_id") or "",
        "tracking_url": ctx.get("tracking_url") or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "footer_note": quote.get("footer_note") or "Validez sujeta a disponibilidad y condiciones comerciales vigentes.",
    }


def build_quote_document_spec(quote_id: str, *, ticket_id: str | None = None) -> dict[str, Any]:
    ctx = build_quote_context(quote_id)
    if not ctx.get("ok"):
        return ctx
    return {"ok": True, "spec": _quote_spec(ctx, ticket_id=ticket_id)}


def render_quote_html(quote_id: str, *, ticket_id: str | None = None) -> dict[str, Any]:
    ctx = build_quote_context(quote_id)
    if not ctx.get("ok"):
        return ctx
    spec = _quote_spec(ctx, ticket_id=ticket_id)
    html_doc = build_document_html(spec)
    return {"ok": True, "quote_id": quote_id, "html": html_doc, **{k: v for k, v in ctx.items() if k != "ok"}}


def render_tracking_html(ticket_id: str) -> dict[str, Any]:
    """Página pública de seguimiento — estilo moderno, no ticket clásico."""
    from raphiia_openai.operational.quote_delivery import get_delivery_by_ticket

    delivery = get_delivery_by_ticket(ticket_id)
    if not delivery.get("ok"):
        return delivery
    doc = delivery["delivery"]
    events = doc.get("events") or []
    status = doc.get("status", "sent")
    status_labels = {
        "draft": "Borrador",
        "sent": "Enviada",
        "viewed": "Vista por cliente",
        "accepted": "Aceptada",
        "rejected": "Rechazada",
        "expired": "Vencida",
        "follow_up": "En seguimiento",
    }
    label = status_labels.get(status, status.title())
    theme = resolve_entity_theme("ent_pcdoctor")
    timeline = []
    for ev in events:
        timeline.append(
            f"""
            <div class="event">
              <div class="dot"></div>
              <div>
                <strong>{_esc(ev.get('title', 'Actualización'))}</strong>
                <p>{_esc(ev.get('detail', ''))}</p>
                <time>{_esc(ev.get('at', ''))}</time>
              </div>
            </div>"""
        )
    html_doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Seguimiento {ticket_id}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Outfit:wght@700;800&display=swap" rel="stylesheet">
  <style>
    body {{
      font-family: Inter, sans-serif;
      background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
      color: #e2e8f0;
      min-height: 100vh;
      padding: 1.5rem 1rem;
    }}
    .card {{
      max-width: 580px;
      margin: 0 auto;
      background: #1e293b;
      border-radius: 20px;
      padding: 1.5rem;
      box-shadow: 0 25px 50px rgba(0,0,0,.4);
      border: 1px solid rgba(255,255,255,.06);
    }}
    .badge {{
      display: inline-block;
      background: {theme['accent']};
      color: #fff;
      padding: 0.35rem 0.9rem;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 700;
    }}
    h1 {{
      font-family: Outfit, sans-serif;
      font-size: 1.7rem;
      margin: 1rem 0 0.25rem;
    }}
    .ticket {{ font-family: monospace; color: #94a3b8; font-size: 0.95rem; }}
    .status {{
      margin: 1.2rem 0;
      padding: 1rem;
      background: #0f172a;
      border-radius: 12px;
      border-left: 4px solid {theme['accent']};
    }}
    .timeline {{ margin-top: 1.2rem; }}
    .event {{ display: flex; gap: 1rem; margin-bottom: 1rem; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; background: {theme['accent']}; margin-top: 6px; flex-shrink: 0; }}
    .event p {{ color: #94a3b8; font-size: 0.9rem; margin: 0.2rem 0; }}
    .event time {{ font-size: 0.75rem; color: #64748b; }}
    .wa-hint {{ margin-top: 1.25rem; font-size: 0.85rem; color: #94a3b8; }}
    .wa-hint strong {{ color: #25d366; }}
    @media (max-width: 640px) {{
      .card {{ padding: 1.2rem; }}
    }}
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">Seguimiento de cotización</span>
    <h1>{_esc(doc.get('client_name', 'Tu propuesta'))}</h1>
    <p class="ticket">Referencia: {_esc(ticket_id)}</p>
    <div class="status">
      <div>Estado actual</div>
      <strong style="font-size:1.15rem">{_esc(label)}</strong>
      <div style="margin-top:0.5rem;color:#94a3b8">Cotización {_esc(doc.get('display_number', ''))}</div>
    </div>
    <div class="timeline">{''.join(timeline) or '<p style="color:#64748b">Sin eventos aún.</p>'}</div>
    <p class="wa-hint">¿Dudas? Responde por <strong>WhatsApp</strong> citando la referencia <strong>{_esc(ticket_id)}</strong>.</p>
  </div>
</body>
</html>"""
    return {"ok": True, "ticket_id": ticket_id, "html": html_doc, "delivery": doc}
