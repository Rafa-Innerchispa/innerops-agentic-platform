"""Motor documental compartido para piezas comerciales y operativas.

Este módulo centraliza:
- temas por entidad;
- normalización de IVA / tax_rate;
- numeración comercial;
- HTML responsivo reutilizable;
- PDF multipágina con cabecera y pie repetidos.

La idea es que cotizaciones, propuestas, diagnósticos, reportes,
órdenes de trabajo y actas puedan compartir la misma base visual y
estructural sin duplicar layouts.
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fpdf import FPDF

ENTITY_THEMES: dict[str, dict[str, str]] = {
    "ent_pcdoctor": {
        "name": "PC Doctor",
        "tagline": "Soluciones Tecnológicas · Infraestructura · Soporte",
        "accent": "#0ea5e9",
        "accent_dark": "#0369a1",
        "surface": "#ffffff",
        "surface_alt": "#f1f5f9",
    },
    "ent_innerspark": {
        "name": "InnerSpark",
        "tagline": "Servidores Locales Inteligentes · IA On-Premise",
        "accent": "#8b5cf6",
        "accent_dark": "#6d28d9",
        "surface": "#ffffff",
        "surface_alt": "#f5f3ff",
    },
    "ent_innerchispa": {
        "name": "InnerChispa",
        "tagline": "Innovación · IA · Transformación digital",
        "accent": "#f59e0b",
        "accent_dark": "#d97706",
        "surface": "#ffffff",
        "surface_alt": "#fffbeb",
    },
    "ent_ralfia": {
        "name": "Ralfi IA",
        "tagline": "Plataforma operativa · MCP · Agentes",
        "accent": "#6366f1",
        "accent_dark": "#4338ca",
        "surface": "#ffffff",
        "surface_alt": "#eef2ff",
    },
    "ent_iskcon": {
        "name": "ISKCON",
        "tagline": "Servicio espiritual · Comunidad",
        "accent": "#f97316",
        "accent_dark": "#c2410c",
        "surface": "#ffffff",
        "surface_alt": "#fff7ed",
    },
    "ent_rafael_personal": {
        "name": "Rafael López",
        "tagline": "Personal · Memoria · Salud",
        "accent": "#64748b",
        "accent_dark": "#475569",
        "surface": "#ffffff",
        "surface_alt": "#f8fafc",
    },
    "ent_domotika": {
        "name": "Domotika",
        "tagline": "Automatización · Seguridad · Edificios Conectados",
        "accent": "#14b8a6",
        "accent_dark": "#0f766e",
        "surface": "#ffffff",
        "surface_alt": "#f0fdfa",
    },
    "default": {
        "name": "Ralfi IA",
        "tagline": "Documentos operativos y comerciales",
        "accent": "#0ea5e9",
        "accent_dark": "#0369a1",
        "surface": "#ffffff",
        "surface_alt": "#f8fafc",
    },
}

DOCUMENT_KIND_LABELS = {
    "quote": "Cotización",
    "invoice": "Factura",
    "proposal": "Propuesta",
    "diagnostic": "Diagnóstico",
    "report": "Reporte",
    "work_order": "Orden de trabajo",
    "minutes": "Acta",
}


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _fmt_date(value: Any) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%d/%m/%Y")
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:19] if "T" in raw else raw[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw[:10]


def _fmt_datetime(value: Any) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    raw = str(value).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        except ValueError:
            continue
    return raw


def _truncate(text: Any, limit: int) -> str:
    raw = _norm(text)
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def _pdf_safe(value: Any) -> str:
    """Texto seguro para Helvetica base de FPDF."""
    raw = _norm(value)
    replacements = {
        "—": "-",
        "–": "-",
        "·": "-",
        "•": "-",
        "…": "...",
        "“": "\"",
        "”": "\"",
        "‘": "'",
        "’": "'",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    return raw


def normalize_tax_rate(value: Any) -> float:
    """Acepta 0.15, 15 o '15%' y devuelve fracción normalizada."""
    if value in (None, ""):
        return 0.0
    try:
        rate = float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return 0.0
    if rate <= 0:
        return 0.0
    if rate <= 1:
        return round(rate, 4)
    if rate <= 100:
        return round(rate / 100.0, 4)
    return 0.0


def format_money(value: Any, currency: str = "USD") -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    symbol = "$" if currency.upper() == "USD" else currency.upper()
    return f"{symbol}{amount:,.2f}"


def format_quantity(value: Any) -> str:
    """Cantidades enteras sin decimal; fracciones solo si aplica (ej. 2.5 L)."""
    try:
        qty = float(value or 0)
    except (TypeError, ValueError):
        return _norm(value)
    if abs(qty - round(qty)) < 1e-9:
        return str(int(round(qty)))
    text = f"{qty:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def build_document_number(prefix: str, sequence: int, *, year: int | None = None, width: int = 6) -> str:
    """Formato canónico sugerido: PCD-COT-YY-######."""
    yy = str(year or datetime.now(timezone.utc).year)[-2:]
    return f"{prefix}-{yy}-{int(sequence):0{width}d}"


def resolve_entity_theme(entity_id: str | None) -> dict[str, str]:
    key = (entity_id or "default").strip().lower()
    if key in ENTITY_THEMES:
        return dict(ENTITY_THEMES[key])
    return dict(ENTITY_THEMES["default"])


def document_kind_label(document_type: str | None) -> str:
    key = (document_type or "").strip().lower()
    if key in DOCUMENT_KIND_LABELS:
        return DOCUMENT_KIND_LABELS[key]
    return key.replace("_", " ").title() or "Documento"


def markdown_to_html(text: str) -> str:
    """Markdown ligero para secciones cortas.

    Soporta:
    - headings # / ## / ###;
    - listas con - o *;
    - párrafos.
    """
    if not text:
        return ""
    lines = str(text).replace("\r\n", "\n").splitlines()
    parts: list[str] = []
    in_list = False
    for raw in lines:
        line = raw.strip()
        if not line:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        if line.startswith("### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h4>{_esc(line[4:])}</h4>")
        elif line.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{_esc(line[3:])}</h3>")
        elif line.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{_esc(line[2:])}</h2>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_esc(line[2:])}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p>{_esc(line)}</p>")
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def _table_cell_value(row: dict[str, Any], column: dict[str, Any]) -> str:
    key = column.get("key", "")
    value = row.get(key, "")
    kind = (column.get("kind") or "").lower()
    if callable(column.get("format")):
        try:
            value = column["format"](value, row=row, column=column)
        except Exception:
            value = value
    elif kind in {"money", "currency"}:
        value = format_money(value, column.get("currency", "USD"))
    elif kind in {"quantity", "qty", "number"}:
        value = format_quantity(value)
    elif kind in {"date"}:
        value = _fmt_date(value)
    elif kind in {"datetime", "timestamp"}:
        value = _fmt_datetime(value)
    else:
        value = _norm(value)
    limit = int(column.get("max_chars") or 0)
    if limit > 0:
        value = _truncate(value, limit)
    return _esc(value)


def _render_table_html(table: dict[str, Any], *, currency: str = "USD") -> str:
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not columns:
        return ""
    head = "".join(
        (
            f"<th class='{('num' if (col.get('align') or ('right' if (col.get('kind') or '').lower() in {'money', 'currency', 'quantity', 'qty', 'number'} else 'left')) in {'right', 'center'} else '')}' "
            f"style='width:{_esc(col.get('width') or '')};text-align:{_esc(col.get('align') or ('right' if (col.get('kind') or '').lower() in {'money', 'currency', 'quantity', 'qty', 'number'} else 'left'))}'>"
            f"{_esc(col.get('title') or col.get('label') or col.get('key') or '')}</th>"
        )
        for col in columns
    )
    body_rows: list[str] = []
    for row in rows:
        cells = []
        for col in columns:
            value = _table_cell_value(row, {**col, "currency": col.get("currency", currency)})
            align = col.get("align") or ("right" if (col.get("kind") or "").lower() in {"money", "currency", "number"} else "left")
            cls = "num" if align in {"right", "center"} else ""
            cells.append(f"<td class='{cls}' style='text-align:{_esc(align)}'>{value}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    if not body_rows:
        body_rows.append(f"<tr><td colspan='{len(columns)}' class='muted'>Sin líneas</td></tr>")
    return f"""
    <table class="doc-table">
      <thead><tr>{head}</tr></thead>
      <tbody>{''.join(body_rows)}</tbody>
    </table>
    """


def build_document_html(spec: dict[str, Any]) -> str:
    """Render HTML responsivo compartido para documentos."""
    theme = resolve_entity_theme(spec.get("entity_id"))
    doc_kind = document_kind_label(spec.get("document_type"))
    title = _norm(spec.get("title")) or doc_kind
    number = _norm(spec.get("document_number") or spec.get("display_number") or spec.get("quote_ref") or "")
    client = spec.get("client") or {}
    site = spec.get("site") or {}
    issued_at = _fmt_date(spec.get("issued_at") or spec.get("created_at"))
    valid_until = _fmt_date(spec.get("valid_until")) if spec.get("valid_until") else "—"
    status = _norm(spec.get("status") or "draft").replace("_", " ").title()
    currency = _norm(spec.get("currency") or "USD").upper()
    tax_rate = normalize_tax_rate(spec.get("tax_rate"))
    tax_label = f"{tax_rate * 100:g}%"
    tracking_url = _norm((spec.get("tracking") or {}).get("url") or spec.get("tracking_url"))
    ticket_id = _norm((spec.get("tracking") or {}).get("ticket_id") or spec.get("ticket_id"))

    meta_cells = [
        ("Número", number or "—"),
        ("Fecha emisión", issued_at),
        ("Válida hasta", valid_until),
        ("Estado", status),
    ]
    if spec.get("meta_extra"):
        for item in spec["meta_extra"][:4]:
            meta_cells.append((item.get("label", ""), item.get("value", "")))

    client_rows = [
        ("Cliente", client.get("display_name") or client.get("legal_name") or spec.get("client_name") or "—"),
        ("RUC / Cédula", client.get("tax_id") or client.get("ruc") or spec.get("client_id") or "—"),
        ("Contacto", client.get("contact_name") or client.get("contact") or "—"),
        ("Teléfono", client.get("phone") or "—"),
        ("Proyecto / Sitio", site.get("name") or spec.get("site_name") or spec.get("project_name") or "—"),
        ("Dirección", ", ".join(filter(None, [client.get("address"), client.get("city")])) or site.get("address") or "—"),
    ]

    sections_html: list[str] = []
    summary_md = _norm(spec.get("summary_md") or spec.get("intro_md") or "")
    section_counter = 1
    if summary_md:
        sections_html.append(
            f"""
            <section class="section">
              <div class="section-head"><span>{section_counter:02d}</span><h2>Contexto</h2></div>
              <div class="body markdown">{markdown_to_html(summary_md)}</div>
              <p class="note">Este bloque resume el alcance. No sustituye el detalle técnico del campo.</p>
            </section>
            """
        )
        section_counter += 1

    for section in spec.get("sections") or []:
        body = _norm(section.get("body_md") or section.get("body") or "")
        bullets = section.get("bullets") or []
        table = section.get("table") or {}
        appendix = section.get("appendix") or []
        notes = section.get("note") or ""
        title_section = _norm(section.get("title") or f"Sección {section_counter}")
        body_html = markdown_to_html(body) if body else ""
        bullets_html = ""
        if bullets:
            bullets_html = "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in bullets) + "</ul>"
        table_html = _render_table_html(table, currency=currency) if table else ""
        appendix_html = ""
        if appendix:
            cards = []
            for item in appendix:
                caption = _norm(item.get("caption") or item.get("label") or "")
                path = _norm(item.get("path") or item.get("media_path") or "")
                note = _norm(item.get("note") or "")
                cards.append(
                    f"""
                    <figure class="appendix-card">
                      <div class="appendix-preview">{_esc(caption or 'Adjunto')}</div>
                      <figcaption>
                        <strong>{_esc(caption or 'Adjunto')}</strong>
                        <span>{_esc(path)}</span>
                        {f"<small>{_esc(note)}</small>" if note else ""}
                      </figcaption>
                    </figure>
                    """
                )
            appendix_html = f"<div class='appendix-grid'>{''.join(cards)}</div>"
        sections_html.append(
            f"""
            <section class="section">
              <div class="section-head"><span>{section_counter:02d}</span><h2>{_esc(title_section)}</h2></div>
              {f"<div class='body markdown'>{body_html}</div>" if body_html else ""}
              {f"<div class='body bullets'>{bullets_html}</div>" if bullets_html else ""}
              {table_html}
              {f"<p class='note'>{_esc(notes)}</p>" if notes else ""}
              {appendix_html}
            </section>
            """
        )
        section_counter += 1

    totals_rows = []
    for item in spec.get("totals") or []:
        label = _norm(item.get("label") or "")
        value = item.get("value", 0)
        strong = bool(item.get("strong"))
        totals_rows.append(
            f"<div class='totals-row{' grand' if strong else ''}'><span>{_esc(label)}</span><span>{_esc(format_money(value, currency))}</span></div>"
        )

    ticket_block = ""
    if ticket_id:
        ticket_block = f"""
        <div class="ticket-strip">
          <span>Seguimiento</span>
          <strong>{_esc(ticket_id)}</strong>
          {f'<a href="{_esc(tracking_url)}">Ver estado en línea</a>' if tracking_url else ''}
        </div>
        """

    appendix_block = ""
    if spec.get("appendices"):
        appendix_cards = []
        for appendix in spec["appendices"]:
            appendix_title = _norm(appendix.get("title") or "")
            items = appendix.get("items") or []
            cards = []
            for item in items:
                caption = _norm(item.get("caption") or item.get("label") or "")
                path = _norm(item.get("path") or item.get("media_path") or "")
                cards.append(
                    f"""
                    <figure class="appendix-card">
                      <div class="appendix-preview">{_esc(caption or 'Adjunto')}</div>
                      <figcaption>
                        <strong>{_esc(caption or 'Adjunto')}</strong>
                        <span>{_esc(path)}</span>
                      </figcaption>
                    </figure>
                    """
                )
            appendix_cards.append(
                f"""
                <section class="section">
                  <div class="section-head"><span>{section_counter:02d}</span><h2>{_esc(appendix_title or 'Anexos')}</h2></div>
                  <div class='appendix-grid'>{''.join(cards)}</div>
                </section>
                """
            )
            section_counter += 1
        appendix_block = "".join(appendix_cards)

    table_block = ""
    if spec.get("table"):
        table_block = f"""
        <section class="section">
          <div class="section-head"><span>{section_counter:02d}</span><h2>{_esc(spec.get('table_title') or 'Detalle comercial')}</h2></div>
          {_render_table_html(spec['table'], currency=currency)}
        </section>
        """
        section_counter += 1

    commercial_block = ""
    commercial = spec.get("commercial_terms") or {}
    if commercial:
        rows = []
        for label, key in (
            ("Vendedor", "seller_name"),
            ("Forma de pago", "payment_terms"),
            ("Garantía", "warranty"),
            ("Validez", "validity"),
        ):
            val = _norm(commercial.get(key))
            if val:
                rows.append(f"<div><dt>{_esc(label)}</dt><dd>{_esc(val)}</dd></div>")
        includes = commercial.get("includes") or []
        excludes = commercial.get("excludes") or []
        includes_html = ""
        if includes:
            includes_html = "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in includes) + "</ul>"
        excludes_html = ""
        if excludes:
            excludes_html = "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in excludes) + "</ul>"
        commercial_block = f"""
        <section class="section">
          <div class="section-head"><span>{section_counter:02d}</span><h2>Condiciones comerciales</h2></div>
          {f"<dl class='client-band'>{''.join(rows)}</dl>" if rows else ""}
          {f"<div class='body'><h3>Incluye</h3>{includes_html}</div>" if includes_html else ""}
          {f"<div class='body'><h3>No incluye</h3>{excludes_html}</div>" if excludes_html else ""}
        </section>
        """
        section_counter += 1

    html_doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(doc_kind)} {_esc(number or title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Outfit:wght@500;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --accent: {theme["accent"]};
      --accent-dark: {theme["accent_dark"]};
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --bg: #f8fafc;
      --card: {theme["surface"]};
      --card-alt: {theme["surface_alt"]};
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', system-ui, sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.5;
      padding: 1.5rem 1rem 2rem;
    }}
    .page {{
      max-width: 960px;
      margin: 0 auto;
      background: var(--card);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.15);
    }}
    .hero {{
      background: linear-gradient(135deg, var(--accent-dark) 0%, var(--accent) 55%, #38bdf8 100%);
      color: #fff;
      padding: 2rem 2.25rem;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 1.25rem;
      align-items: start;
    }}
    .hero h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: clamp(1.5rem, 2.2vw, 2.1rem);
      font-weight: 800;
      letter-spacing: -0.02em;
    }}
    .hero .tagline {{ opacity: 0.9; font-size: 0.92rem; margin-top: 0.25rem; }}
    .doc-type {{
      text-align: right;
      font-family: 'Outfit', sans-serif;
    }}
    .doc-type .label {{
      display: inline-block;
      background: rgba(255,255,255,0.18);
      padding: 0.35rem 0.75rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .doc-type h2 {{ font-size: 1.45rem; margin-top: 0.5rem; }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    .meta-cell {{
      padding: 1rem 1.15rem;
      border-right: 1px solid var(--line);
    }}
    .meta-cell:last-child {{ border-right: none; }}
    .meta-cell span {{ display: block; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
    .meta-cell strong {{ display: block; margin-top: 0.2rem; font-size: 0.96rem; }}
    .client-band {{
      padding: 1.25rem 2.25rem;
      background: var(--card-alt);
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.85rem 1.5rem;
      border-bottom: 1px solid var(--line);
    }}
    .client-band dt {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }}
    .client-band dd {{ font-weight: 700; margin-top: 0.14rem; }}
    .content {{ padding: 1.8rem 2.25rem 2.25rem; }}
    .section {{ margin-bottom: 1.8rem; }}
    .section-head {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.95rem;
      padding-bottom: 0.5rem;
      border-bottom: 2px solid var(--accent);
    }}
    .section-head span {{
      font-family: 'Outfit', sans-serif;
      font-weight: 800;
      color: var(--accent);
      font-size: 1rem;
    }}
    .section-head h2 {{ font-family: 'Outfit', sans-serif; font-size: 1.08rem; }}
    .body p {{ margin-bottom: 0.7rem; color: #334155; }}
    .body ul {{ margin: 0.5rem 0 0.9rem 1.2rem; color: #334155; }}
    .body li {{ margin-bottom: 0.35rem; }}
    .note {{ font-size: 0.8rem; color: var(--muted); font-style: italic; margin-top: 0.4rem; }}
    .doc-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      margin-top: 0.2rem;
      table-layout: fixed;
    }}
    .doc-table th {{
      background: #f8fafc;
      text-align: left;
      padding: 0.72rem 0.6rem;
      border-bottom: 2px solid var(--line);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      vertical-align: middle;
    }}
    .doc-table th.num {{ text-align: right; }}
    .doc-table td {{
      padding: 0.72rem 0.6rem;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      word-wrap: break-word;
      overflow-wrap: break-word;
    }}
    .doc-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .doc-table .strong {{ font-weight: 800; color: var(--accent-dark); }}
    .totals {{
      margin-top: 1rem;
      display: flex;
      justify-content: flex-end;
    }}
    .totals-box {{
      min-width: min(100%, 300px);
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: hidden;
      background: #fff;
    }}
    .totals-row {{
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      padding: 0.65rem 1rem;
      border-bottom: 1px solid var(--line);
    }}
    .totals-row.grand {{
      background: linear-gradient(90deg, var(--accent-dark), var(--accent));
      color: #fff;
      font-weight: 800;
      font-size: 1.04rem;
      border: none;
    }}
    .ticket-strip {{
      margin-top: 1rem;
      padding: 0.95rem 1.15rem;
      border-radius: 10px;
      background: #ecfdf5;
      border: 1px solid #a7f3d0;
      display: flex;
      align-items: center;
      gap: 0.9rem;
      flex-wrap: wrap;
    }}
    .ticket-strip span {{ color: #047857; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .ticket-strip strong {{ color: #065f46; font-family: 'Outfit', sans-serif; }}
    .ticket-strip a {{ color: var(--accent-dark); font-weight: 700; }}
    .appendix-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 0.85rem;
    }}
    .appendix-card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      background: #fff;
    }}
    .appendix-preview {{
      min-height: 120px;
      background: linear-gradient(135deg, #e2e8f0, #cbd5e1);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
      font-weight: 700;
      color: #334155;
      text-align: center;
    }}
    .appendix-card figcaption {{
      padding: 0.8rem 0.9rem 0.95rem;
      display: grid;
      gap: 0.25rem;
    }}
    .appendix-card figcaption span,
    .appendix-card figcaption small {{
      color: var(--muted);
      font-size: 0.8rem;
      overflow-wrap: anywhere;
    }}
    .footer {{
      padding: 1rem 2.25rem 1.4rem;
      border-top: 1px solid var(--line);
      font-size: 0.78rem;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      flex-wrap: wrap;
    }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .page {{ box-shadow: none; border-radius: 0; }}
    }}
    @media (max-width: 720px) {{
      .meta-grid {{ grid-template-columns: 1fr 1fr; }}
      .client-band {{ grid-template-columns: 1fr; }}
      .hero {{ grid-template-columns: 1fr; }}
      .doc-type {{ text-align: left; }}
      .content, .footer, .hero, .client-band {{ padding-left: 1rem; padding-right: 1rem; }}
    }}
  </style>
</head>
<body>
  <article class="page">
    <header class="hero">
      <div>
        <h1>{_esc(theme["name"])} · {_esc(title)}</h1>
        <p class="tagline">{_esc(theme["tagline"])}</p>
      </div>
      <div class="doc-type">
        <span class="label">{_esc(doc_kind)}</span>
        <h2>{_esc(number or "—")}</h2>
      </div>
    </header>
    <div class="meta-grid">
      {''.join(f"<div class='meta-cell'><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>" for label, value in meta_cells[:4])}
    </div>
    <dl class="client-band">
      {''.join(f"<div><dt>{_esc(label)}</dt><dd>{_esc(value)}</dd></div>" for label, value in client_rows)}
    </dl>
    <div class="content">
      {''.join(sections_html)}
      {table_block}
      {f'<div class="totals"><div class="totals-box">{"".join(totals_rows)}</div></div>' if totals_rows else ''}
      {commercial_block}
      {ticket_block}
      {appendix_block}
    </div>
    <footer class="footer">
      <span>Generado por RalfIA · {_fmt_datetime(spec.get("generated_at") or datetime.now(timezone.utc).isoformat())}</span>
      <span>{_esc(spec.get("footer_note") or "Validez sujeta a disponibilidad y condiciones comerciales vigentes.")}</span>
    </footer>
  </article>
</body>
</html>"""
    return html_doc


class DocumentPDF(FPDF):
    """PDF multipágina con cabecera/pie compartidos."""

    def __init__(self, spec: dict[str, Any]) -> None:
        super().__init__()
        self.spec = spec
        self.theme = resolve_entity_theme(spec.get("entity_id"))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(14, 16, 14)
        self.set_title(_norm(spec.get("title") or spec.get("document_number") or "Documento"))
        self.set_author("RalfIA")

    def header(self) -> None:  # noqa: D401
        self.set_fill_color(255, 255, 255)
        self.set_text_color(15, 23, 42)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 7, _pdf_safe(f"{self.theme['name']} - {document_kind_label(self.spec.get('document_type'))}"), ln=True)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 116, 139)
        left = _norm(self.spec.get("document_number") or self.spec.get("display_number") or self.spec.get("quote_ref") or "")
        right = _norm(self.spec.get("status") or "draft").replace("_", " ").title()
        self.cell(0, 5, _pdf_safe(f"{left} - {right}"), ln=True)
        self.set_draw_color(226, 232, 240)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:  # noqa: D401
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 116, 139)
        self.cell(0, 5, f"Página {self.page_no()} / {{nb}}", align="C")


def _doc_text(pdf: DocumentPDF, text: str, *, size: int = 10, bold: bool = False, color: tuple[int, int, int] = (15, 23, 42)) -> None:
    if not text:
        return
    pdf.set_text_color(*color)
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.multi_cell(0, 5, _pdf_safe(text))
    pdf.ln(1)


def _doc_markdown(pdf: DocumentPDF, text: str) -> None:
    if not text:
        return
    pdf.set_text_color(51, 65, 85)
    pdf.set_font("Helvetica", "", 10)
    width = pdf.w - pdf.l_margin - pdf.r_margin
    for raw in str(text).replace("\r\n", "\n").splitlines():
        line = raw.strip()
        if not line:
            pdf.ln(1)
            continue
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_x(pdf.l_margin)
            pdf.cell(width, 6, _pdf_safe(line[4:]), ln=True)
            pdf.set_font("Helvetica", "", 10)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_x(pdf.l_margin)
            pdf.cell(width, 7, _pdf_safe(line[3:]), ln=True)
            pdf.set_font("Helvetica", "", 10)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_x(pdf.l_margin)
            pdf.cell(width, 8, _pdf_safe(line[2:]), ln=True)
            pdf.set_font("Helvetica", "", 10)
        elif line.startswith("- ") or line.startswith("* "):
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(width, 5, _pdf_safe(f"- {line[2:]}"))
        else:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(width, 5, _pdf_safe(line))


def _pdf_row(pdf: DocumentPDF, widths: list[float], values: list[str], *, line_h: float = 6.2, fills: list[bool] | None = None) -> None:
    x0 = pdf.get_x()
    y0 = pdf.get_y()
    fills = fills or [False] * len(values)
    max_h = line_h
    for idx, width in enumerate(widths):
        pdf.set_xy(x0 + sum(widths[:idx]), y0)
        pdf.multi_cell(width, line_h, values[idx], border=1, align="L", fill=fills[idx], new_x="RIGHT", new_y="TOP")
        max_h = max(max_h, pdf.get_y() - y0)
    pdf.set_xy(x0, y0 + max_h)


def _pdf_table(pdf: DocumentPDF, table: dict[str, Any], *, currency: str = "USD") -> None:
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not columns:
        return
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    widths = []
    for col in columns:
        width = col.get("width")
        if isinstance(width, (int, float)):
            widths.append(float(width))
        else:
            widths.append(0.0)
    if not any(widths):
        widths = [epw / len(columns)] * len(columns)
    else:
        declared = sum(widths)
        if declared <= 0:
            widths = [epw / len(columns)] * len(columns)
        elif declared < epw:
            last = widths[-1] + (epw - declared)
            widths[-1] = last
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.set_fill_color(248, 250, 252)
    header_values = [_pdf_safe(_truncate(col.get("title") or col.get("label") or col.get("key") or "", 36)) for col in columns]
    pdf.set_x(pdf.l_margin)
    _pdf_row(pdf, widths, header_values, line_h=6.5, fills=[True] * len(columns))
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(15, 23, 42)
    for row in rows:
        values = []
        for col in columns:
            values.append(_pdf_safe(_table_cell_value(row, {**col, "currency": col.get("currency", currency)})))
        pdf.set_x(pdf.l_margin)
        _pdf_row(pdf, widths, values, line_h=6.0)


def _pdf_totals(pdf: DocumentPDF, totals: list[dict[str, Any]], *, currency: str = "USD") -> None:
    if not totals:
        return
    pdf.ln(2)
    box_w = min(80, pdf.w - pdf.l_margin - pdf.r_margin)
    x = pdf.w - pdf.r_margin - box_w
    pdf.set_x(x)
    for idx, item in enumerate(totals):
        strong = bool(item.get("strong"))
        label = _pdf_safe(item.get("label") or "")
        value = format_money(item.get("value"), currency)
        pdf.set_x(x)
        pdf.set_fill_color(240, 253, 250) if strong else pdf.set_fill_color(255, 255, 255)
        pdf.set_font("Helvetica", "B" if strong else "", 10 if strong else 9)
        pdf.cell(box_w * 0.62, 8, label, border=1, fill=strong, ln=0)
        pdf.cell(box_w * 0.38, 8, _pdf_safe(value), border=1, fill=strong, align="R", ln=1)


def _pdf_appendices(pdf: DocumentPDF, appendices: list[dict[str, Any]]) -> None:
    for appendix in appendices:
        title = _pdf_safe(appendix.get("title") or "Anexos")
        items = appendix.get("items") or []
        if not items:
            continue
        pdf.ln(3)
        _doc_text(pdf, title, size=11, bold=True, color=(37, 99, 235))
        pdf.ln(1)
        for item in items:
            label = _pdf_safe(item.get("caption") or item.get("label") or "Adjunto")
            path = _pdf_safe(item.get("path") or item.get("media_path") or "")
            note = _pdf_safe(item.get("note") or "")
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, label, ln=True)
            pdf.set_font("Helvetica", "", 8.5)
            if path:
                pdf.multi_cell(0, 5, f"Archivo: {path}")
                if Path(path).is_file():
                    try:
                        pdf.image(path, w=min(85, pdf.w - pdf.l_margin - pdf.r_margin))
                    except Exception:
                        pass
            if note:
                pdf.multi_cell(0, 5, note)
            pdf.ln(1)


def render_pdf_document(spec: dict[str, Any], output_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Genera PDF multipágina desde el spec compartido."""
    pdf = DocumentPDF(spec)
    pdf.alias_nb_pages()
    pdf.add_page()
    theme = resolve_entity_theme(spec.get("entity_id"))
    doc_kind = document_kind_label(spec.get("document_type"))
    title = _norm(spec.get("title") or doc_kind)
    number = _norm(spec.get("document_number") or spec.get("display_number") or spec.get("quote_ref") or "")

    # Hero inicial
    pdf.set_fill_color(*tuple(int(theme["accent"].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)))
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 10, _pdf_safe(f"{theme['name']} - {title}"), ln=True, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, _pdf_safe(theme["tagline"]), ln=True, fill=True)
    pdf.set_text_color(15, 23, 42)
    pdf.ln(3)

    meta_items = [
        ("Número", number or "-"),
        ("Fecha emisión", _fmt_date(spec.get("issued_at") or spec.get("created_at"))),
        ("Estado", _norm(spec.get("status") or "draft").replace("_", " ").title()),
        ("Cliente", _norm((spec.get("client") or {}).get("display_name") or spec.get("client_name") or "-")),
    ]
    if spec.get("valid_until"):
        meta_items.append(("Válida hasta", _fmt_date(spec.get("valid_until"))))
    if spec.get("ticket_id"):
        meta_items.append(("Seguimiento", _norm(spec.get("ticket_id"))))

    pdf.set_font("Helvetica", "B", 9)
    epw = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = epw / 2
    for i in range(0, len(meta_items), 2):
        left = meta_items[i]
        right = meta_items[i + 1] if i + 1 < len(meta_items) else ("", "")
        y = pdf.get_y()
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(226, 232, 240)
        pdf.multi_cell(col_w, 7, f"{left[0]}\n{left[1]}", border=1, fill=True)
        x_right = pdf.l_margin + col_w
        pdf.set_xy(x_right, y)
        pdf.multi_cell(col_w, 7, f"{right[0]}\n{right[1]}", border=1, fill=True)
        pdf.ln(1)

    client = spec.get("client") or {}
    site = spec.get("site") or {}
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "Datos principales", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(
        0,
        5.5,
        "\n".join(
            [
                f"Cliente: {client.get('display_name') or client.get('legal_name') or spec.get('client_name') or '-'}",
                f"RUC/Cédula: {client.get('tax_id') or spec.get('client_id') or '-'}",
                f"Contacto: {client.get('email') or client.get('phone') or '-'}",
                f"Sitio: {site.get('name') or spec.get('site_name') or spec.get('project_name') or '-'}",
                f"Dirección: {', '.join(filter(None, [client.get('address'), client.get('city')])) or site.get('address') or '-'}",
            ]
        ),
    )

    summary_md = _norm(spec.get("summary_md") or spec.get("intro_md") or "")
    if summary_md:
        pdf.ln(1)
        _doc_text(pdf, "Contexto", size=11, bold=True, color=(37, 99, 235))
        _doc_markdown(pdf, summary_md)

    for idx, section in enumerate(spec.get("sections") or [], start=1):
        title_section = _pdf_safe(section.get("title") or f"Sección {idx}")
        pdf.ln(1)
        _doc_text(pdf, title_section, size=11, bold=True, color=(37, 99, 235))
        if section.get("body_md") or section.get("body"):
            _doc_markdown(pdf, _norm(section.get("body_md") or section.get("body") or ""))
        bullets = section.get("bullets") or []
        if bullets:
            for bullet in bullets:
                pdf.multi_cell(0, 5, _pdf_safe(f"- {_norm(bullet)}"))
        if section.get("table"):
            _pdf_table(pdf, section["table"], currency=_norm(spec.get("currency") or "USD"))
        if section.get("note"):
            pdf.set_text_color(100, 116, 139)
            pdf.set_font("Helvetica", "I", 8.5)
            pdf.multi_cell(0, 5, _norm(section.get("note")))
            pdf.set_text_color(15, 23, 42)
            pdf.set_font("Helvetica", "", 9.5)

    if spec.get("table"):
        pdf.ln(1)
        _doc_text(pdf, _pdf_safe(spec.get("table_title") or "Detalle comercial"), size=11, bold=True, color=(37, 99, 235))
        _pdf_table(pdf, spec["table"], currency=_norm(spec.get("currency") or "USD"))

    if spec.get("totals"):
        _pdf_totals(pdf, spec["totals"], currency=_norm(spec.get("currency") or "USD"))

    if spec.get("appendices"):
        _pdf_appendices(pdf, spec["appendices"])

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return {"ok": True, "pdf_path": str(out), "pdf_filename": out.name}
