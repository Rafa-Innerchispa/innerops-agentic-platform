"""Generación de imágenes — ComfyUI RealVisXL modo ultra calidad."""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

from raphiia_openai import local_image_runtime
from raphiia_openai.local_image_runtime import IMAGE_QUALITY, REALVIS_CKPT, _is_turbo, _resolve_checkpoint

# Ultra: más resolución nativa antes de upscale (32 GB VRAM).
ASPECT_GEN_SIZE: dict[str, tuple[int, int]] = {
    "9:16": (1024, 1792),
    "16:9": (1536, 864),
    "1:1": (1152, 1152),
}

ASPECT_GEN_SIZE_STANDARD: dict[str, tuple[int, int]] = {
    "9:16": (832, 1216),
    "16:9": (1344, 768),
    "1:1": (1024, 1024),
}

OUTPUT_SIZE: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def _gen_sizes(aspect: str, *, quality: str) -> tuple[int, int]:
    ckpt = _resolve_checkpoint()
    if _is_turbo(ckpt):
        return {**ASPECT_GEN_SIZE_STANDARD, "16:9": (1152, 648)}.get(aspect, (1344, 768))
    if quality in ("ultra", "max", "high"):
        return ASPECT_GEN_SIZE.get(aspect, (1536, 864))
    return ASPECT_GEN_SIZE_STANDARD.get(aspect, (1344, 768))


def _upscale_image(src: Path, dest: Path, *, width: int, height: int) -> None:
    from PIL import Image, ImageFilter

    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.size != (width, height):
            im = im.resize((width, height), Image.Resampling.LANCZOS)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=130, threshold=1))
        im.save(dest, format="JPEG", quality=95, optimize=True, subsampling=0)


def generate_scene_image(
    prompt: str,
    output: Path,
    *,
    aspect: str = "9:16",
    title: str = "",
    cinematic: bool = True,
    seed: int | None = None,
    quality: str | None = None,
) -> dict[str, Any]:
    q = (quality or IMAGE_QUALITY or "ultra").strip().lower()
    w, h = OUTPUT_SIZE.get(aspect, OUTPUT_SIZE["16:9"])
    gen_w, gen_h = _gen_sizes(aspect, quality=q)
    ckpt = _resolve_checkpoint()

    comfy = local_image_runtime.health()
    if comfy.get("ok"):
        tmp = output.with_suffix(".gen.png")
        result = local_image_runtime.generate(
            prompt,
            tmp,
            width=gen_w,
            height=gen_h,
            seed=seed,
            quality=q,
        )
        if result.get("ok"):
            p = Path(result.get("media_path") or tmp)
            if p.is_file() and p.stat().st_size > 10_000:
                _upscale_image(p, output, width=w, height=h)
                tmp.unlink(missing_ok=True)
                return {
                    "ok": True,
                    "path": str(output),
                    "provider": "comfyui",
                    "checkpoint": ckpt,
                    "gen_resolution": f"{gen_w}x{gen_h}",
                    "quality": q,
                    "steps": result.get("steps"),
                    "photoreal": ckpt == REALVIS_CKPT,
                }
    return {"ok": False, "error": "comfyui_unavailable", "provider": "failed"}
