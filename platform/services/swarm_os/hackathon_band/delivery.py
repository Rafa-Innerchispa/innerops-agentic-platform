"""Entrega del reporte: WhatsApp + email."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hackathon_band import config
from hackathon_band.console_log import log as clog
from hackathon_band.email_notify import send_report_emails
from hackathon_band.phone_utils import parse_phone_list
from hackathon_band.whatsapp_notify import build_whatsapp_message, public_report_download_url


def deliver_report(
    question: str,
    report_path: str,
    report_markdown: str,
    *,
    memory_hits: list[dict[str, Any]] | None = None,
    memory_hits_count: int = 0,
    lang: str = "en",
    extra_phones: list[str] | None = None,
    extra_emails: list[str] | None = None,
) -> None:
    _deliver_whatsapp(
        question,
        report_path,
        report_markdown,
        memory_hits=memory_hits,
        memory_hits_count=memory_hits_count,
        lang=lang,
        extra_phones=extra_phones,
    )
    send_report_emails(
        question,
        report_markdown,
        report_path,
        extra_emails=extra_emails,
        memory_hits=memory_hits,
        memory_hits_count=memory_hits_count,
        lang=lang,
    )


def _format_whatsapp_error(result: dict[str, Any] | None) -> str:
    if not result:
        return "sin respuesta"
    msg = result.get("message")
    if msg:
        return str(msg)[:200]
    resp = result.get("response")
    if isinstance(resp, dict):
        for key in ("message", "error", "detail"):
            val = resp.get(key)
            if val:
                return str(val)[:200]
    http = result.get("http_status")
    if http:
        return f"HTTP {http}"
    return str(result)[:200]


def _whatsapp_attachment(report_path: str, report_markdown: str) -> tuple[Path, str, str]:
    """Prepara adjunto WhatsApp: PDF preferido (Evolution no admite .md bien)."""
    from hackathon_band.report_pdf import markdown_to_pdf

    md_path = Path(report_path)
    pdf_path = md_path.with_suffix(".pdf")
    md_text = report_markdown
    if not md_text and md_path.is_file():
        md_text = md_path.read_text(encoding="utf-8")
    if md_text:
        try:
            markdown_to_pdf(md_text, pdf_path)
            if pdf_path.is_file():
                return pdf_path, "application/pdf", "PCDoctor_Band_Report.pdf"
        except Exception:
            pass
    if md_path.is_file():
        return md_path, "text/plain", "PCDoctor_Band_Report.txt"
    return md_path, "text/plain", "PCDoctor_Band_Report.txt"


def _deliver_whatsapp(
    question: str,
    report_path: str,
    report_markdown: str,
    *,
    memory_hits: list[dict[str, Any]] | None = None,
    memory_hits_count: int = 0,
    lang: str = "en",
    extra_phones: list[str] | None = None,
) -> None:
    evo_key = config.EVOLUTION_API_KEY
    evo_inst = config.EVOLUTION_INSTANCE
    recipients = parse_phone_list(config.HACKATHON_WHATSAPP_TO, *(extra_phones or []))

    if not evo_key:
        clog("info", "whatsapp", "Evolution API not configured — skipped")
        return

    if not recipients:
        clog("info", "whatsapp", "No phone recipients configured")
        return

    clog("info", "whatsapp", f"Sending to {len(recipients)} number(s): {', '.join(r[:6]+'…' for r in recipients)}")

    try:
        from tools.evolution_api import send_whatsapp, send_whatsapp_document

        text = build_whatsapp_message(
            question,
            report_markdown,
            hits=memory_hits,
            memory_hits_count=memory_hits_count,
            lang=lang,
        )
        download_url = public_report_download_url()
        doc_caption = (
            "Reporte Band of Agents — PC Doctor"
            if lang == "es"
            else "Band of Agents report — PC Doctor"
        )

        sent = 0
        for num in recipients:
            try:
                result = send_whatsapp(num, text, instance=evo_inst or None, skip_existence_check=True)
                if result.get("status") != "sent":
                    clog(
                        "error",
                        "whatsapp",
                        f"{num}: {result.get('message') or result.get('check') or result}",
                    )
                    continue
                sent += 1
                clog("success", "whatsapp", f"Summary → {result.get('number', num)}")
                attach_path, mime, fname = _whatsapp_attachment(report_path, report_markdown)
                if attach_path.is_file():
                    doc = send_whatsapp_document(
                        num,
                        attach_path,
                        caption=doc_caption,
                        instance=evo_inst or None,
                        file_name=fname,
                        mimetype=mime,
                        skip_existence_check=True,
                    )
                    if doc.get("status") == "sent":
                        clog("success", "whatsapp", f"Attachment → {num}")
                    else:
                        clog("error", "whatsapp", f"Attachment {num}: {_format_whatsapp_error(doc)}")
                else:
                    clog("info", "whatsapp", f"No attachment file — link only for {num}")
            except Exception as exc:
                clog("error", "whatsapp", f"{num}: {exc}")
        if sent:
            clog("success", "whatsapp", f"{sent}/{len(recipients)} OK — {download_url}")
    except Exception as exc:
        clog("error", "whatsapp", f"Delivery failed: {exc}")
