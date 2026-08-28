"""Genera documentos exportables (MVP: Markdown listo para PDF)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import EXPORTS_DIR


def _ts() -> str:
    return datetime.now(ZoneInfo("America/Guayaquil")).strftime("%Y-%m-%d")


def export_technical_report(
    inspection_id: str,
    report: dict,
    client: dict,
    code: str | None = None,
) -> str:
    client_name = client.get("name", "Cliente")
    short = client_name[:20].replace(" ", "")
    label = (code or f"PCD-RPT-26-{inspection_id[:6]}").replace("/", "-")
    path = EXPORTS_DIR / f"{label}-{short}.md"
    body = f"""# Informe Técnico — PC Doctor S.A.

**Cliente:** {client_name}
**RUC:** {client.get('ruc', '')}
**Fecha:** {_ts()}
**Ubicación:** {report.get('location', '')}
**Técnico:** {report.get('technician', 'Por confirmar')}

## Resumen
{report.get('summary', '')}

## Hallazgos
{report.get('findings_text', '')}

## Trabajo realizado
{report.get('work_done', 'Inspección y diagnóstico en campo.')}

## Estado final
{report.get('final_status', 'Pendiente de cotización')}

## Recomendaciones
{report.get('recommendations', '')}
"""
    path.write_text(body, encoding="utf-8")
    return str(path)


def export_quote(
    inspection_id: str,
    quote: dict,
    client: dict,
    code: str | None = None,
) -> str:
    client_name = client.get("name", "Cliente")
    short = client_name[:20].replace(" ", "")
    label = (code or f"PCD-COT-26-{inspection_id[:6]}").replace("/", "-")
    path = EXPORTS_DIR / f"{label}-{short}.md"
    lines_txt = "\n".join(
        f"- {l.get('qty', 1)} x {l.get('name', '')} @ ${l.get('unit_price', 0):.2f}"
        for l in quote.get("lines", [])
    )
    body = f"""# Cotización — PC Doctor S.A.

**Cliente:** {client_name}
**RUC:** {client.get('ruc', '')}
**Fecha:** {_ts()}
**Alcance:** {quote.get('scope', '')}

## Ítems
{lines_txt}

**Subtotal:** ${quote.get('subtotal', 0):.2f}
**IVA 15%:** ${quote.get('iva', 0):.2f}
**Total:** ${quote.get('total', 0):.2f}
"""
    path.write_text(body, encoding="utf-8")
    return str(path)
