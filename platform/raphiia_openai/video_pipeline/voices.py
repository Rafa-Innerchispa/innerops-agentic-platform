"""Voces disponibles para Video Studio — XTTS clonadas + Piper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from raphiia_openai.video_pipeline import tts as video_tts

PIPER_VOICES_DIR = Path(os.getenv("PIPER_VOICES_DIR", "/home/rlopez/data/piper/voices"))


def list_voices() -> list[dict[str, str]]:
    voices: list[dict[str, str]] = []
    try:
        from raphiia_openai import voice_xtts

        for v in voice_xtts.list_cloned_voices():
            voices.append(
                {
                    "id": v["id"],
                    "label": v.get("label") or v["id"],
                    "provider": "xtts-v2",
                    "language": v.get("language") or "es",
                    "natural": "true",
                }
            )
        for sp, job in voice_xtts._load_jobs().items():
            if job.get("status") == "ready" and not any(x["id"] == f"xtts:{sp}" for x in voices):
                voices.append(
                    {
                        "id": f"xtts:{sp}",
                        "label": voice_xtts.SPEAKER_LABELS.get(sp, sp.title()),
                        "provider": "xtts-v2",
                        "language": job.get("language") or "es",
                        "natural": "true",
                    }
                )
    except Exception:
        pass

    if PIPER_VOICES_DIR.is_dir():
        for onnx in sorted(PIPER_VOICES_DIR.glob("*.onnx")):
            voices.append(
                {
                    "id": str(onnx.resolve()),
                    "label": f"Piper · {onnx.stem.replace('_', ' ')}",
                    "provider": "piper",
                    "language": "es",
                    "natural": "medium",
                }
            )
    elif video_tts.PIPER_MODEL.is_file():
        voices.append(
            {
                "id": str(video_tts.PIPER_MODEL.resolve()),
                "label": "Piper · español",
                "provider": "piper",
                "language": "es",
                "natural": "medium",
            }
        )

    health = video_tts.tts_health()
    if health.get("espeak_fallback"):
        voices.append(
            {
                "id": "espeak",
                "label": "Espeak (solo diagnóstico — robótico)",
                "provider": "espeak",
                "language": "es",
                "natural": "false",
            }
        )
    return voices


def default_voice_id() -> str | None:
    try:
        from raphiia_openai import voice_xtts

        jobs = voice_xtts._load_jobs()
        for sp, job in jobs.items():
            if job.get("status") == "ready" and job.get("active"):
                return f"xtts:{sp}"
        for sp, job in jobs.items():
            if job.get("status") == "ready":
                return f"xtts:{sp}"
    except Exception:
        pass
    voices = list_voices()
    for v in voices:
        if v.get("provider") == "xtts-v2":
            return v["id"]
    for v in voices:
        if v.get("provider") == "piper":
            return v["id"]
    return None


def voice_catalog() -> dict[str, Any]:
    voices = list_voices()
    default = default_voice_id()
    return {
        "ok": True,
        "voices": voices,
        "default_voice": default,
        "recommended": default,
        "limits": video_limits(),
        "health": video_tts.tts_health(),
    }


def video_limits() -> dict[str, Any]:
    max_dur = int(os.getenv("VIDEO_MAX_DURATION_SEC", "180"))
    return {
        "max_scenes": int(os.getenv("VIDEO_MAX_SCENES", "24")),
        "max_duration_sec": max_dur,
        "max_duration_minutes": round(max_dur / 60, 1),
        "max_script_chars": int(os.getenv("VIDEO_MAX_SCRIPT_CHARS", "8000")),
        "xtts_chunk_chars": 1800,
        "aspects": {
            "9:16": {"resolution": "1080x1920", "use": "Instagram Reels, Stories, TikTok, WhatsApp Status"},
            "16:9": {"resolution": "1920x1080", "use": "YouTube, LinkedIn"},
            "1:1": {"resolution": "1080x1080", "use": "Feed cuadrado"},
        },
        "instagram_reels_max_sec": 90,
        "youtube_shorts_max_sec": 60,
        "duration_tiers": {
            "short_social": {"sec": 60, "feasible": True, "note": "Reels/Shorts — ideal"},
            "medium": {"sec": 180, "feasible": True, "note": "Límite actual por defecto (~3 min)"},
            "long": {"sec": 600, "feasible": True, "note": "Posible con VIDEO_MAX_DURATION_SEC=600 (~10 min, ~40 min render)"},
            "very_long": {"sec": 3600, "feasible": False, "note": "No recomendado en un solo pase — dividir en capítulos/episodios"},
        },
        "episodic_recommendation": (
            "Para vídeos de 5–60 min: generar episodios de 3–10 min y unirlos en editor, "
            "o subir VIDEO_MAX_DURATION_SEC y max_scenes (cada escena ≈ ComfyUI 90s en GPU local)."
        ),
        "notes": (
            "Duración real ≈ longitud del audio TTS. Más escenas = más tiempo de generación. "
            "ComfyUI ~90s/imagen en RX 7900 XTX. 10 escenas ≈ 15 min solo imágenes."
        ),
    }
