"""Subir imagen a borrador editorial — ChatGPT (URL/base64) sin Google API."""

from __future__ import annotations

import base64
import re
import urllib.request
from pathlib import Path
from typing import Any

from raphiia_openai import editorial_store
from raphiia_openai.image_gen import _media_path

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _decode_base64_image(raw: str) -> tuple[bytes, str]:
    text = (raw or "").strip()
    mime = "image/png"
    if text.startswith("data:"):
        header, _, payload = text.partition(",")
        m = re.search(r"data:([^;]+)", header)
        if m:
            mime = m.group(1).lower()
        text = payload
    # quitar espacios/saltos
    text = re.sub(r"\s+", "", text)
    try:
        data = base64.b64decode(text, validate=False)
    except Exception as exc:
        raise ValueError(f"base64 inválido: {exc}") from exc
    if len(data) < 100:
        raise ValueError("imagen demasiado pequeña")
    ext = _MIME_EXT.get(mime, "png")
    return data, ext


def _download_url(url: str, timeout: float = 45.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "RalfIA-MCP/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < 100:
        raise ValueError("descarga vacía o inválida")
    return data


def upload_to_draft(
    draft_id: str,
    *,
    image_base64: str = "",
    image_url: str = "",
    mime_type: str = "image/png",
    prompt: str = "",
    source: str = "chatgpt",
) -> dict[str, Any]:
    """Guarda imagen en disco y la vincula al borrador (provider chatgpt_* → LinkedIn OK)."""
    dr = editorial_store.get_draft(draft_id)
    if not dr.get("ok"):
        return dr

    provider_map = {
        "chatgpt": "chatgpt_native",
        "dalle": "chatgpt_dalle",
        "chatgpt_dalle": "chatgpt_dalle",
        "url": "chatgpt_url",
    }
    provider = provider_map.get((source or "chatgpt").lower(), f"chatgpt_{source}")

    if image_base64.strip():
        data, ext = _decode_base64_image(image_base64)
    elif image_url.strip():
        data = _download_url(image_url.strip())
        ext = _MIME_EXT.get(mime_type.lower(), "png")
        provider = "chatgpt_dalle" if "dalle" in source.lower() else "chatgpt_url"
    else:
        return {"ok": False, "error": "provide image_base64 or image_url"}

    out: Path = _media_path(draft_id, ext=ext)
    out.write_bytes(data)

    editorial_store.update_draft(draft_id, {"status": editorial_store.STATUS_GENERATING})
    result = editorial_store.attach_media(
        draft_id,
        media_path=str(out),
        media_prompt=prompt or f"ChatGPT image ({provider})",
        provider=provider,
    )
    return {
        "ok": True,
        "media_path": str(out),
        "provider": provider,
        "bytes": len(data),
        "panel_preview": f"http://192.168.1.4:8101/editorial",
        **result,
    }
