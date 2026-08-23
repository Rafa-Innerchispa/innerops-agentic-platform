"""Genera PDF simple del reporte hackathon (UTF-8)."""

from __future__ import annotations

import re
from pathlib import Path


def markdown_to_pdf(markdown: str, out_path: Path) -> Path:
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError("Instala fpdf2: pip install fpdf2") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    font_dir = Path(__file__).resolve().parent / "assets"
    regular = font_dir / "DejaVuSans.ttf"
    bold = font_dir / "DejaVuSans-Bold.ttf"
    use_dejavu = regular.is_file()
    if use_dejavu:
        pdf.add_font("DejaVu", "", str(regular))
        if bold.is_file():
            pdf.add_font("DejaVu", "B", str(bold))
        pdf.set_font("DejaVu", size=10)

    def _set_body() -> None:
        pdf.set_font("DejaVu" if use_dejavu else "Helvetica", size=10)

    def _set_heading() -> None:
        if use_dejavu and bold.is_file():
            pdf.set_font("DejaVu", "B", 11)
        elif use_dejavu:
            pdf.set_font("DejaVu", size=11)
        else:
            pdf.set_font("Helvetica", "B", 11)

    if not use_dejavu:
        pdf.set_font("Helvetica", size=10)

    plain = _markdown_to_plain(markdown)
    for block in plain.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("## "):
            _set_heading()
            pdf.multi_cell(0, 6, block[3:].strip())
            _set_body()
        else:
            pdf.multi_cell(0, 5, block)
        pdf.ln(2)

    pdf.output(str(out_path))
    return out_path


def _markdown_to_plain(md: str) -> str:
    text = md.replace("\r\n", "\n")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()
