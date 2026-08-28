"""URL pública y mensajes WhatsApp enriquecidos para hackathon."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from hackathon_band import config


def resolve_public_base_url() -> str:
    """Base URL ngrok (sin slash final) para enlaces en WhatsApp."""
    env_url = (os.getenv("HACKATHON_PUBLIC_URL") or "").strip().rstrip("/")
    if env_url:
        return env_url

    url_file = config.REPO_ROOT / "data" / "hackathon_public_url.txt"
    if url_file.exists():
        for line in url_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("public_hackathon_ui:"):
                u = line.split(":", 1)[1].strip()
                if u.startswith("http"):
                    return u.rstrip("/")

    demo_file = config.REPO_ROOT / "data" / "public_demo_url.txt"
    if demo_file.exists():
        for line in demo_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ngrok_hackathon:") or line.startswith("ngrok_base:"):
                u = line.split(":", 1)[1].strip()
                if u.startswith("http"):
                    return u.rstrip("/")

    return f"http://192.168.1.4:{config.HACKATHON_BAND_PORT}"


def public_report_download_url() -> str:
    return f"{resolve_public_base_url()}/api/report/download"


def _extract_teaser_lines(report_markdown: str, hits: list[dict[str, Any]], lang: str, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for h in hits[:limit]:
        text = (h.get("text") or "").strip().replace("\n", " ")
        if len(text) > 10:
            src = h.get("source", "mongodb")
            lines.append(f"• {text[:140]} [{src}]")

    if lines:
        return lines

    md = report_markdown or ""
    for pattern in (
        r"## MongoDB Evidence[^\n]*\n+(.*?)(?=\n## |\Z)",
        r"## Evidencia MongoDB[^\n]*\n+(.*?)(?=\n## |\Z)",
        r"## Executive Summary\n+(.*?)(?=\n## |\Z)",
    ):
        m = re.search(pattern, md, re.DOTALL | re.IGNORECASE)
        if m:
            block = m.group(1).strip()
            for raw in block.split("\n"):
                raw = raw.strip().lstrip("-*> ")
                if len(raw) > 15:
                    lines.append(f"• {raw[:160]}")
                if len(lines) >= limit:
                    break
        if lines:
            break
    return lines[:limit]


def build_whatsapp_message(
    question: str,
    report_markdown: str,
    *,
    hits: list[dict[str, Any]] | None = None,
    memory_hits_count: int = 0,
    lang: str = "en",
) -> str:
    download = public_report_download_url()
    teasers = _extract_teaser_lines(report_markdown, hits or [], lang)
    teaser_block = "\n".join(teasers) if teasers else (
        "• Datos reales recuperados de MongoDB pcdoctor_swarm"
        if lang == "es"
        else "• Real data retrieved from MongoDB pcdoctor_swarm"
    )

    if lang == "es":
        return (
            "🧠 *PC Doctor · Band of Agents*\n"
            "✅ *Reporte ejecutivo listo*\n"
            "🤖 Router → Memory → Analyst → Documentation (Band LIVE)\n\n"
            f"📋 *Pregunta:*\n{question[:200]}\n\n"
            f"🔍 *De tu memoria organizacional* ({memory_hits_count or len(hits or [])} fuentes):\n"
            f"{teaser_block}\n\n"
            f"⬇️ *Descargar reporte (.md):*\n{download}\n\n"
            "📎 El PDF completo llega adjunto en el siguiente mensaje."
        )

    return (
        "🧠 *PC Doctor · Band of Agents*\n"
        "✅ *Executive report ready*\n"
        "🤖 Router → Memory → Analyst → Documentation (Band LIVE)\n\n"
        f"📋 *Question:*\n{question[:200]}\n\n"
        f"🔍 *From organizational memory* ({memory_hits_count or len(hits or [])} sources):\n"
        f"{teaser_block}\n\n"
        f"⬇️ *Download report (.md):*\n{download}\n\n"
        "📎 Full file attached in the next message."
    )
