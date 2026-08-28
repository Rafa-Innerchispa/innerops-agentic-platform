"""Generación de fotos standalone — MCP / ChatGPT."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from raphiia_openai.settings import EDITORIAL_MEDIA_ROOT
from raphiia_openai.time_utils import local_timestamp
from raphiia_openai.video_pipeline import scene_images, scene_prompts


def generate_photo(
    *,
    prompt: str = "",
    title: str = "",
    brief: str = "",
    aspect: str = "16:9",
    quality: str = "ultra",
    entity_id: str = "ent_innerspark",
    seed: int | None = None,
) -> dict[str, Any]:
    """Genera una foto fotorrealista local (RealVisXL ultra)."""
    topic = (prompt or brief or title or "tecnología e innovación empresarial").strip()
    visual = scene_prompts.visual_prompt_for_scene(
        topic,
        title=title or topic[:80],
        entity=entity_id,
        scene_index=hash(topic) % 4,
        aspect=aspect,
    )
    if prompt.strip() and len(prompt.strip()) > 40:
        visual = f"{visual} Additional direction: {prompt.strip()[:600]}"

    slug = re.sub(r"[^a-z0-9]+", "-", (title or topic).lower()).strip("-")[:40] or "photo"
    out_dir = Path(EDITORIAL_MEDIA_ROOT) / "photos" / entity_id / local_timestamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.jpg"

    result = scene_images.generate_scene_image(
        visual,
        out_path,
        aspect=aspect,
        title=title or slug,
        seed=seed or (hash(topic) % 999_983),
        quality=quality,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "generation failed"), "prompt": visual[:500]}

    return {
        "ok": True,
        "photo_path": str(out_path),
        "aspect": aspect,
        "quality": quality,
        "provider": result.get("provider"),
        "checkpoint": result.get("checkpoint"),
        "gen_resolution": result.get("gen_resolution"),
        "steps": result.get("steps"),
        "prompt_used": visual[:800],
        "lan_url": f"http://192.168.1.5:8081/files?path={out_path}",
    }
