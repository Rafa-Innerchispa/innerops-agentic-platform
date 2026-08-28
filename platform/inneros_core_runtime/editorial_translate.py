"""Traducción editorial local-first (Ollama) — adaptación, no literal."""

from __future__ import annotations

import json
import re
from typing import Any

from raphiia_openai.editorial_i18n import PUBLICATION_LANGUAGES, normalize_lang
from raphiia_openai.local_model_router import run_local_model


def _parse_json_block(raw: str) -> dict[str, str] | None:
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and ("title" in data or "markdown" in data):
            return {
                "title": str(data.get("title", "")).strip(),
                "markdown": str(data.get("markdown", data.get("body", ""))).strip(),
            }
    except json.JSONDecodeError:
        pass
    return None


def translate_content(
    *,
    title: str,
    markdown: str,
    target_lang: str,
    source_lang: str | None = None,
) -> dict[str, Any]:
    """Traduce título + cuerpo para LinkedIn con tono nativo (no literal)."""
    tgt = normalize_lang(target_lang, allowed=PUBLICATION_LANGUAGES)
    tgt_name = PUBLICATION_LANGUAGES.get(tgt, tgt)
    src = normalize_lang(source_lang, allowed=PUBLICATION_LANGUAGES) if source_lang else "auto"

    prompt = (
        f"Translate this LinkedIn post for a professional technology/business audience.\n"
        f"Target language: {tgt_name} ({tgt}).\n"
        f"Source language hint: {src}.\n\n"
        "Rules:\n"
        "- Do NOT translate word-for-word; adapt naturally for native speakers.\n"
        "- Keep hashtags if present; translate surrounding prose only.\n"
        "- Title: catchy, professional, same intent as original.\n"
        "- Body: preserve structure (paragraphs, bullets), max 2800 chars.\n"
        "- Return ONLY valid JSON: {\"title\": \"...\", \"markdown\": \"...\"}\n\n"
        f"TITLE:\n{title}\n\nBODY:\n{markdown[:3500]}"
    )

    result = run_local_model(task_type="reformat", prompt=prompt, temperature=0.35, max_tokens=2048)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "translation_failed"),
            "detail": result,
            "fallback": _fallback_translate(title, markdown, tgt),
        }

    content = (result.get("response") or "").strip()
    if not content and isinstance(result.get("message"), dict):
        content = result["message"].get("content", "")
    parsed = _parse_json_block(content)
    if not parsed:
        # Ollama a veces devuelve texto plano
        lines = content.split("\n", 1)
        parsed = {
            "title": lines[0].strip()[:200] or title,
            "markdown": (lines[1] if len(lines) > 1 else content).strip() or markdown,
        }

    return {
        "ok": True,
        "title": parsed["title"][:300],
        "markdown": parsed["markdown"][:3000],
        "target_lang": tgt,
        "source_lang": src,
        "method": "ollama",
        "model": result.get("model"),
    }


def _fallback_translate(title: str, markdown: str, tgt: str) -> dict[str, str]:
    """Si Ollama no está — devuelve original con aviso en título."""
    prefix = {"es": "[ES]", "en": "[EN]", "hi": "[HI]"}.get(tgt, f"[{tgt.upper()}]")
    return {"title": f"{prefix} {title}"[:300], "markdown": markdown[:3000]}
