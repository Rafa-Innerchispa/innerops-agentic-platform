"""Perfiles ComfyUI para Open WebUI / MCP — turbo (rápido) vs RealVis (fotorrealismo)."""

from __future__ import annotations

from pathlib import Path

CHECKPOINTS_DIR = Path("/home/rlopez/apps/ComfyUI/models/checkpoints")

TURBO = "sd_xl_turbo_1.0_fp16.safetensors"
REALVIS = "RealVisXL_V5.0_fp16.safetensors"

DEFAULT_NEGATIVE = (
    "cartoon, anime, illustration, painting, drawing, sketch, low quality, blurry, "
    "deformed, ugly, bad anatomy, bad hands, watermark, text, oversaturated, "
    "cgi, plastic skin, doll"
)

IMAGE_PROMPT_TEMPLATE = """\
{{prompt}}

Estilo: fotorrealista salvo que el usuario pida explícitamente dibujo/cartoon.
Para personas reales o escenas futuristas usa en el prompt (inglés): photorealistic, ultra detailed, cinematic lighting, 8k uhd, dslr, realistic skin texture, sharp focus.
Negative: cartoon, anime, illustration, painting, sketch, low quality, blurry, deformed."""

IMAGEN_SYSTEM = (
    "Eres RalfIA Imagen HD. ComfyUI + RealVisXL dibujan en el servidor; tú redactas prompts en INGLÉS.\n"
    "Reglas:\n"
    "- Personas reales / futurista / conectados a IA → photorealistic, ultra detailed, cinematic lighting, "
    "8k uhd, dslr, realistic skin, sharp focus, futuristic city, holographic interfaces.\n"
    "- NO uses: cartoon, illustration, anime, drawing, sketch (salvo que el usuario lo pida).\n"
    "- Confirma la imagen solo si ves el archivo adjunto en el chat.\n"
    "- No uses web search ni MCP."
)

IMAGEN_RAPIDA_SYSTEM = (
    "Eres RalfIA Imagen Rápida (SDXL turbo). Prompts cortos en inglés. "
    "Calidad menor que Imagen HD — avisa si piden fotorrealismo detallado."
)


def checkpoint_path(name: str) -> Path:
    return CHECKPOINTS_DIR / name


def pick_quality_checkpoint() -> str:
    if checkpoint_path(REALVIS).is_file():
        return REALVIS
    return TURBO


def profile_for(checkpoint: str) -> dict:
    if checkpoint == TURBO:
        return {
            "checkpoint": TURBO,
            "steps": 8,
            "cfg": 1.6,
            "sampler_name": "euler",
            "scheduler": "karras",
            "label": "rápido",
        }
    return {
        "checkpoint": checkpoint,
        "steps": 30,
        "cfg": 5.0,
        "sampler_name": "dpmpp_2m",
        "scheduler": "karras",
        "label": "HD fotorrealista",
    }


def build_workflow(profile: dict) -> dict:
    ckpt = profile["checkpoint"]
    neg = DEFAULT_NEGATIVE
    return {
        "3": {
            "inputs": {
                "seed": 0,
                "steps": profile["steps"],
                "cfg": profile["cfg"],
                "sampler_name": profile["sampler_name"],
                "scheduler": profile["scheduler"],
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
            "class_type": "KSampler",
        },
        "4": {"inputs": {"ckpt_name": ckpt}, "class_type": "CheckpointLoaderSimple"},
        "5": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptyLatentImage"},
        "6": {"inputs": {"text": "", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "7": {"inputs": {"text": neg, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
        "9": {"inputs": {"filename_prefix": "openwebui", "images": ["8", 0]}, "class_type": "SaveImage"},
    }


def workflow_nodes(profile: dict) -> list[dict]:
    ckpt = profile["checkpoint"]
    return [
        {"node_ids": ["4"], "key": "ckpt_name", "value": ckpt},
        {"type": "prompt", "node_ids": ["6"], "key": "text"},
        {"type": "negative_prompt", "node_ids": ["7"], "key": "text"},
        {"type": "width", "node_ids": ["5"], "key": "width"},
        {"type": "height", "node_ids": ["5"], "key": "height"},
        {"type": "steps", "node_ids": ["3"], "key": "steps"},
        {"type": "seed", "node_ids": ["3"], "key": "seed"},
    ]
