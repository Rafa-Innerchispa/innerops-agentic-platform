"""Generación PDF de cotizaciones desde el motor documental compartido."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from raphiia_openai.operational.document_engine import render_pdf_document
from raphiia_openai.operational.quote_renderer import build_quote_document_spec

QUOTE_PDF_ROOT = Path(os.getenv("QUOTE_PDF_ROOT", "/home/rlopez/data/media/pcdoctor/quotes"))
QUOTE_PDF_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value)[:80]


def generate_quote_pdf(quote_ref: str, *, ticket_id: str | None = None) -> dict[str, Any]:
    spec_result = build_quote_document_spec(quote_ref, ticket_id=ticket_id)
    if not spec_result.get("ok"):
        return spec_result
    spec = spec_result["spec"]
    display = spec.get("document_number") or quote_ref
    fname = _safe_filename(f"COT_{display}_{ticket_id or 'draft'}") + ".pdf"
    out_path = QUOTE_PDF_ROOT / fname
    pdf_result = render_pdf_document(spec, out_path)
    if not pdf_result.get("ok"):
        return pdf_result
    return {
        "ok": True,
        "quote_ref": quote_ref,
        "pdf_path": pdf_result.get("pdf_path"),
        "pdf_filename": pdf_result.get("pdf_filename"),
        "display_number": display,
        "ticket_id": ticket_id,
    }
