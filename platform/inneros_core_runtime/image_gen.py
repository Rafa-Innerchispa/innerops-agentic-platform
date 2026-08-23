"""Generación de imágenes — Google Imagen (API) + overlay tipográfico opcional (PIL)."""

from __future__ import annotations

import base64
import json
import os
import textwrap
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.editorial_i18n import overlay_brand
from raphiia_openai import config_store, local_image_runtime
from raphiia_openai.settings import (
    EDITORIAL_MEDIA_ROOT,
    IMAGE_GEN_MODEL,
    IMAGE_GEN_PROVIDER,
)

_NO_TEXT_SUFFIX = (
    " Absolutely no text anywhere in the image. No readable words. No typography. "
    "No fake letters. No logos. No watermarks. No captions. No UI. No signs. No labels."
)


def _media_path(draft_id: str, ext: str = "png") -> Path:
    root = Path(EDITORIAL_MEDIA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return root / f"draft_{draft_id}_{ts}.{ext}"


def _build_visual_prompt(title: str, markdown: str, *, include_ai_text: bool = False) -> str:
    """Prompt visual. Por defecto NO incluye título/contenido literal (evita letras IA corruptas)."""
    if include_ai_text:
        topic = (title or "innovación tecnológica").strip()
        context = (markdown or "")[:400].replace("\n", " ")
        return (
            f"Professional LinkedIn editorial illustration about: {topic}. {context}. "
            "Modern workspace, cinematic lighting, premium tech aesthetic."
        )
    return (
        "Premium abstract editorial illustration for a LinkedIn business technology post. "
        "Human entrepreneur reviewing AI-assisted workflow, holographic assistant subtle in background. "
        "Dark slate atmosphere, electric blue neural light trails, subtle warm orange accent spark. "
        "Corporate innovation, human-in-the-loop, purpose-driven technology. "
        "Ultra realistic photography style, shallow depth of field, square 1:1 composition."
        + _NO_TEXT_SUFFIX
    )


def _apply_text_overlay(image_path: Path, text: str, *, lang: str = "es") -> str:
    """Superpone texto legible con PIL — tipografía real, no IA."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return str(image_path)

    text = (text or "").strip()
    if not text:
        return str(image_path)

    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    bar_h = int(h * 0.28)
    for y in range(bar_h):
        alpha = int(200 * (y / max(bar_h, 1)))
        draw.line([(0, h - bar_h + y), (w, h - bar_h + y)], fill=(15, 23, 42, alpha))

    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(22, w // 28))
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(16, w // 38))
    except OSError:
        font_lg = ImageFont.load_default()
        font_sm = font_lg

    lines = textwrap.wrap(text, width=38)[:3]
    y0 = h - bar_h + 24
    for i, line in enumerate(lines):
        draw.text((32, y0 + i * (font_lg.size + 8)), line, fill=(248, 250, 252, 255), font=font_lg)

    else:
        draw.text((32, h - 28), overlay_brand(lang), fill=(148, 163, 184, 220), font=font_sm)

    out = Image.alpha_composite(img, overlay).convert("RGB")
    out_path = image_path.with_name(image_path.stem + "_overlay.png")
    out.save(out_path, format="PNG", quality=95)
    return str(out_path)


def _placeholder_image(path: Path, title: str, prompt: str) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        path.write_bytes(b"")
        return str(path)

    w, h = 1080, 1080
    img = Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.text((48, 48), "Preview sin Google API", fill=(56, 189, 248), font=font)
    img.save(path, format="PNG")
    return str(path)


def _google_headers() -> dict[str, str]:
    key = config_store.get_google_api_key()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY no configurada — Panel :2002 → APIs y claves")
    return {"Content-Type": "application/json", "x-goog-api-key": key}


def _google_imagen(prompt: str, out_path: Path) -> tuple[str, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_GEN_MODEL}:predict"
    body = json.dumps(
        {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1, "aspectRatio": "1:1"}}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_google_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    predictions = data.get("predictions") or data.get("generatedImages") or []
    if not predictions:
        raise RuntimeError(f"Imagen sin predictions: {json.dumps(data)[:300]}")
    pred = predictions[0]
    b64 = pred.get("bytesBase64Encoded") or pred.get("image", {}).get("bytesBase64Encoded")
    if not b64:
        raise RuntimeError("formato imagen Google no reconocido")
    out_path.write_bytes(base64.b64decode(b64))
    return str(out_path), "google_imagen"


def _google_gemini_image(prompt: str, out_path: Path) -> tuple[str, str]:
    model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_google_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                out_path.write_bytes(base64.b64decode(inline["data"]))
                return str(out_path), "google_gemini"
    raise RuntimeError("Gemini no devolvió imagen inline")


def generate_for_draft(
    draft_id: str,
    title: str,
    markdown: str,
    *,
    include_ai_text: bool = False,
    overlay_text: str | None = None,
    overlay_lang: str = "es",
) -> dict[str, Any]:
    """Genera imagen. Por defecto sin texto IA; overlay_text usa PIL legible."""
    visual_prompt = _build_visual_prompt(title, markdown, include_ai_text=include_ai_text)
    out = _media_path(draft_id)
    provider = "placeholder"
    errors: list[str] = []

    if IMAGE_GEN_PROVIDER in {"local_comfy", "comfyui"}:
        result = local_image_runtime.generate(visual_prompt, out)
        if result.get("ok"):
            final = result["media_path"]
            if overlay_text and overlay_text.strip():
                final = _apply_text_overlay(Path(final), overlay_text.strip(), lang=overlay_lang)
            return {
                "ok": True,
                "media_path": final,
                "media_prompt": visual_prompt,
                "provider": result.get("backend", "comfyui"),
                "backend": result.get("backend", "comfyui"),
                "overlay_applied": bool(overlay_text and overlay_text.strip()),
                "include_ai_text": include_ai_text,
            }
        errors.append(result.get("error", "local image generation failed"))

    if IMAGE_GEN_PROVIDER == "google" and config_store.get_google_api_key():
        for fn in (_google_imagen, _google_gemini_image):
            try:
                path, provider = fn(visual_prompt, out)
                final = path
                if overlay_text and overlay_text.strip():
                    final = _apply_text_overlay(Path(path), overlay_text.strip(), lang=overlay_lang)
                return {
                    "ok": True,
                    "media_path": final,
                    "media_prompt": visual_prompt,
                    "provider": provider,
                    "overlay_applied": bool(overlay_text and overlay_text.strip()),
                    "include_ai_text": include_ai_text,
                }
            except (urllib.error.URLError, OSError, RuntimeError, json.JSONDecodeError, KeyError) as exc:
                errors.append(str(exc))

    path = _placeholder_image(out, title, visual_prompt)
    if overlay_text and overlay_text.strip():
        path = _apply_text_overlay(Path(path), overlay_text.strip(), lang=overlay_lang)
    return {
        "ok": True,
        "media_path": path,
        "media_prompt": visual_prompt,
        "provider": provider,
        "warnings": errors,
        "overlay_applied": bool(overlay_text and overlay_text.strip()),
        "include_ai_text": include_ai_text,
    }
