"""Envío de reporte por email (PDF adjunto) — reutiliza cuentas IMAP/SMTP de InnerOS."""

from __future__ import annotations

from pathlib import Path

from hackathon_band import config
from hackathon_band.phone_utils import parse_email_list
from hackathon_band.report_pdf import markdown_to_pdf
from hackathon_band.whatsapp_notify import build_whatsapp_message, public_report_download_url


def send_report_emails(
    question: str,
    report_markdown: str,
    report_path: str,
    *,
    extra_emails: list[str] | None = None,
    memory_hits: list | None = None,
    memory_hits_count: int = 0,
    lang: str = "en",
) -> dict:
    from hackathon_band.console_log import log as clog
    from tools.email_smtp import send_via_account_with_attachments
    from tools.mongo import get_db

    recipients = parse_email_list(config.HACKATHON_EMAIL_TO, *(extra_emails or []))
    if not recipients:
        clog("info", "email", "No email recipients — set HACKATHON_EMAIL_TO or add emails in dashboard")
        return {"ok": False, "sent": 0, "recipients": []}

    db = get_db()
    acc = db.email_accounts.find_one({"enabled": True}, sort=[("created_at", 1)])
    if not acc:
        clog("error", "email", "No hay cuenta email_accounts activa — configura Correos en InnerOS :5173")
        return {"ok": False, "sent": 0, "error": "no_email_account"}

    md_path = Path(report_path)
    if not md_path.is_file() and report_markdown:
        md_path.write_text(report_markdown, encoding="utf-8")

    pdf_path = md_path.with_suffix(".pdf")
    try:
        markdown_to_pdf(report_markdown or md_path.read_text(encoding="utf-8"), pdf_path)
    except Exception as exc:
        clog("error", "email", f"PDF generation failed: {exc}")
        return {"ok": False, "sent": 0, "error": str(exc)}

    body = build_whatsapp_message(
        question,
        report_markdown,
        hits=memory_hits,
        memory_hits_count=memory_hits_count,
        lang=lang,
    )
    body += f"\n\nDownload: {public_report_download_url()}"

    if lang == "es":
        subject = f"PC Doctor · Reporte Band — {question[:60]}"
    else:
        subject = f"PC Doctor · Band Report — {question[:60]}"

    sent = 0
    errors: list[str] = []
    for to_addr in recipients:
        result = send_via_account_with_attachments(
            acc,
            to_addr=to_addr,
            subject=subject,
            body=body,
            from_name="PC Doctor Band",
            attachments=[
                (pdf_path.name, pdf_path.read_bytes(), "application/pdf"),
                (md_path.name, md_path.read_bytes(), "text/markdown"),
            ],
        )
        if result.get("ok"):
            sent += 1
            clog("success", "email", f"Report PDF sent → {to_addr}")
        else:
            err = result.get("error", "unknown")
            errors.append(f"{to_addr}: {err}")
            clog("error", "email", f"{to_addr}: {err}")

    return {"ok": sent > 0, "sent": sent, "recipients": recipients, "errors": errors}
