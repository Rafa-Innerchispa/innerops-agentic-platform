"""Backend local de imagen para RalfIA.

Primera version: ComfyUI como backend principal.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from raphiia_openai.settings import COMFYUI_CHECKPOINT, COMFYUI_URL

IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", os.getenv("VIDEO_IMAGE_QUALITY", "ultra")).strip().lower()

TURBO_CKPT = "sd_xl_turbo_1.0_fp16.safetensors"
REALVIS_CKPT = "RealVisXL_V5.0_fp16.safetensors"

DEFAULT_NEGATIVE = (
    "cartoon, anime, illustration, painting, 3d render, cgi, doll, plastic skin, "
    "deformed, ugly, bad anatomy, bad hands, bad face, crossed eyes, extra fingers, "
    "mutated, disfigured, blurry, low quality, watermark, text, words, letters, "
    "typography, logo, signature, caption, label, sign, writing, screen text, "
    "jpeg artifacts, oversaturated, amateur, duplicate, cropped, "
    "vintage, retro, sepia, film grain, noise, faded, washed out, dull, muddy colors, "
    "1980s, 1990s, old photo, polaroid, vhs, low contrast, soft focus haze, stock photo cliché"
)


def _is_turbo(checkpoint: str) -> bool:
    return checkpoint == TURBO_CKPT or "turbo" in checkpoint.lower()


def _sampler_for(checkpoint: str, *, quality: str = IMAGE_QUALITY) -> dict[str, Any]:
    ultra = quality in ("ultra", "max", "high")
    if _is_turbo(checkpoint):
        return {"steps": 14 if ultra else 12, "cfg": 2.2, "sampler_name": "euler_ancestral", "scheduler": "karras"}
    if ultra:
        return {"steps": 50, "cfg": 6.5, "sampler_name": "dpmpp_sde", "scheduler": "karras"}
    return {"steps": 28, "cfg": 5.5, "sampler_name": "dpmpp_2m", "scheduler": "karras"}


def _resolve_checkpoint() -> str:
    ckpt_dir = Path("/home/rlopez/apps/ComfyUI/models/checkpoints")
    if COMFYUI_CHECKPOINT:
        p = ckpt_dir / COMFYUI_CHECKPOINT
        if p.is_file():
            return COMFYUI_CHECKPOINT
    realvis = ckpt_dir / REALVIS_CKPT
    if realvis.is_file():
        return REALVIS_CKPT
    turbo = ckpt_dir / TURBO_CKPT
    if turbo.is_file():
        return TURBO_CKPT
    return TURBO_CKPT


def _http_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return {"ok": True, "status": getattr(resp, "status", 200), "data": parsed}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _download_bytes(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "RalfIA-MCP/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("empty image payload")
    return data


def health() -> dict[str, Any]:
    object_info = _http_json(f"{COMFYUI_URL}/object_info", timeout=8.0)
    checkpoint_dir = Path("/home/rlopez/apps/ComfyUI/models/checkpoints")
    checkpoints = []
    if checkpoint_dir.exists():
        checkpoints = sorted([p.name for p in checkpoint_dir.glob("*.safetensors")])[:20]
    node_types: list[str] = []
    if object_info.get("ok"):
        data = object_info.get("data")
        if isinstance(data, dict):
            node_types = sorted(data.keys())[:40]
    return {
        "ok": bool(object_info.get("ok")),
        "provider": "comfyui",
        "url": COMFYUI_URL,
        "configured_checkpoint": _resolve_checkpoint(),
        "node_type_count": len(node_types) if node_types else None,
        "node_types_sample": node_types[:12] or None,
        "checkpoint_dir": str(checkpoint_dir),
        "available_checkpoints": checkpoints,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def list_backends() -> dict[str, Any]:
    h = health()
    return {
        "ok": True,
        "backends": [
            {
                "name": "comfyui",
                "endpoint": COMFYUI_URL,
                "ready": bool(h.get("ok")),
                "recommended_for": ["editorial_images", "modular_workflows", "mcp_exposure"],
            },
        ],
        "health": h,
    }


def generate(
    prompt: str,
    out_path: Path,
    *,
    width: int = 1024,
    height: int = 1024,
    seed: int | None = None,
    negative_prompt: str = "",
    quality: str | None = None,
) -> dict[str, Any]:
    checkpoint = _resolve_checkpoint()
    if not checkpoint:
        return {"ok": False, "error": "COMFYUI_CHECKPOINT not configured", "backend": "comfyui"}

    q = (quality or IMAGE_QUALITY or "ultra").strip().lower()
    sampler = _sampler_for(checkpoint, quality=q)
    neg = negative_prompt.strip() or DEFAULT_NEGATIVE
    client_id = f"ralfia-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    workflow = {
        "1": {"inputs": {"ckpt_name": checkpoint}, "class_type": "CheckpointLoaderSimple"},
        "2": {"inputs": {"text": prompt, "clip": ["1", 1]}, "class_type": "CLIPTextEncode"},
        "3": {"inputs": {"text": neg, "clip": ["1", 1]}, "class_type": "CLIPTextEncode"},
        "4": {"inputs": {"seed": int(seed or 0), "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["5", 0], "denoise": 1, **sampler}, "class_type": "KSampler"},
        "5": {"inputs": {"width": int(width), "height": int(height), "batch_size": 1}, "class_type": "EmptyLatentImage"},
        "6": {"inputs": {"samples": ["4", 0], "vae": ["1", 2]}, "class_type": "VAEDecode"},
        "7": {"inputs": {"filename_prefix": out_path.stem, "images": ["6", 0]}, "class_type": "SaveImage"},
    }
    submit = _http_json(f"{COMFYUI_URL}/prompt", method="POST", body={"prompt": workflow, "client_id": client_id}, timeout=20.0)
    if not submit.get("ok"):
        return {"ok": False, "backend": "comfyui", "error": submit.get("error", "prompt submission failed")}
    prompt_id = submit.get("data", {}).get("prompt_id") or submit.get("data", {}).get("data", {}).get("prompt_id")
    if not prompt_id:
        return {"ok": False, "backend": "comfyui", "error": f"missing prompt_id: {submit}"}

    image_info = None
    max_wait = 300 if q in ("ultra", "max", "high") and not _is_turbo(checkpoint) else (180 if not _is_turbo(checkpoint) else 120)
    for _ in range(max_wait):
        history = _http_json(f"{COMFYUI_URL}/history/{prompt_id}", timeout=15.0)
        data = history.get("data", {}) if history.get("ok") else {}
        prompt_hist = data.get(prompt_id) if isinstance(data, dict) else None
        outputs = (prompt_hist or {}).get("outputs", {}) if isinstance(prompt_hist, dict) else {}
        for node in outputs.values():
            images = node.get("images") if isinstance(node, dict) else None
            if images:
                image_info = images[0]
                break
        if image_info:
            break
        time.sleep(2)

    if not image_info:
        return {"ok": False, "backend": "comfyui", "error": "finished without image output", "prompt_id": prompt_id}

    filename = image_info.get("filename")
    subfolder = image_info.get("subfolder", "")
    image_type = image_info.get("type", "output")
    if not filename:
        return {"ok": False, "backend": "comfyui", "error": f"missing filename: {image_info}", "prompt_id": prompt_id}

    view_url = f"{COMFYUI_URL}/view?filename={quote(filename)}&subfolder={quote(subfolder)}&type={quote(image_type)}"
    out_path.write_bytes(_download_bytes(view_url, timeout=45.0))
    return {
        "ok": True,
        "backend": "comfyui",
        "media_path": str(out_path),
        "prompt_id": prompt_id,
        "comfyui_image": image_info,
        "quality": q,
        "steps": sampler.get("steps"),
        "resolution": f"{width}x{height}",
    }
