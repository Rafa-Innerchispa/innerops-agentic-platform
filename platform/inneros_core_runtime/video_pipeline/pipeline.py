"""Orquestador principal — guion → TTS (XTTS) → imágenes → MP4 → editorial."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.settings import EDITORIAL_VIDEO_ROOT, OLLAMA_URL
from raphiia_openai.time_utils import local_timestamp, now_local_iso
from raphiia_openai.video_pipeline import assemble, overlays, scene_images, scene_prompts, tts, voices


def pipeline_health() -> dict[str, Any]:
    catalog = voices.voice_catalog()
    artifact: dict[str, Any] = {}
    try:
        from raphiia_openai import artifact_delivery

        artifact = {
            "videos_dir": str(artifact_delivery.MEDIA_VIDEOS_DIR),
            "public_bases": artifact_delivery._public_bases()[:3],
            "sample_url_pattern": f"{artifact_delivery._public_bases()[0]}/media/videos/{{filename}}",
        }
    except Exception:
        pass
    return {
        "ok": True,
        "tts": catalog.get("health") or tts.tts_health(),
        "voices": {"count": len(catalog.get("voices") or []), "default": catalog.get("default_voice")},
        "limits": catalog.get("limits"),
        "comfyui": __import__("raphiia_openai.local_image_runtime", fromlist=["health"]).health(),
        "ffmpeg": __import__("shutil").which("ffmpeg") is not None,
        "output_root": str(EDITORIAL_VIDEO_ROOT),
        "artifact_delivery": artifact,
    }


def split_script(script: str, *, max_scenes: int = 8) -> list[str]:
    """Una frase por escena cuando cabe; sub-divide frases largas para más planos."""
    text = (script or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if len(parts) == 1:
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(parts) < max_scenes:
        expanded: list[str] = []
        for part in parts:
            if len(expanded) >= max_scenes:
                expanded.extend(parts[len(expanded) :])
                break
            if len(part) > 70 and "," in part:
                subs = [s.strip() for s in re.split(r",\s+", part) if len(s.strip()) > 12]
                if 1 < len(subs) <= max_scenes - len(expanded):
                    expanded.extend(subs)
                    continue
            expanded.append(part)
        parts = expanded or parts
    if len(parts) > max_scenes:
        chunk = max(1, len(parts) // max_scenes)
        merged: list[str] = []
        for i in range(0, len(parts), chunk):
            merged.append(" ".join(parts[i : i + chunk]))
        parts = merged[:max_scenes]
    return parts[:max_scenes]


def _ollama_narration_script(title: str, brief: str, *, max_words: int = 120) -> dict[str, Any]:
    prompt = (
        f"Eres copywriter de InnerChispa/InnerSpark/PCDoctor/RalfIA. "
        f"Escribe SOLO el guion narrado en español para un vídeo ({max_words} palabras máx). "
        f"Título: {title}\nBrief: {brief}\n"
        "Sin markdown, sin títulos, sin emojis. Tono profesional, cercano y claro."
    )
    body = json.dumps({"model": "qwen2.5:7b", "prompt": prompt, "stream": False}).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL.rstrip('/')}/api/generate",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        script = (data.get("response") or "").strip()
        return {"ok": bool(script), "script": script}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc), "script": brief}


def _write_ass(scenes: list[str], durations: list[float], path: Path, *, width: int = 1080, height: int = 1920) -> None:
    """Subtítulos ASS legibles en móvil — grande, bold, caja oscura, zona segura."""
    path.parent.mkdir(parents=True, exist_ok=True)
    font_size = 52 if height >= 1920 else 40 if height >= 1080 else 32
    margin_v = 260 if height >= 1920 else 180 if height >= 1080 else 120
    margin_lr = 56
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HC0000000,-1,0,0,0,100,100,0,0,3,4,2,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    t = 0.0
    for text, dur in zip(scenes, durations, strict=False):
        start = t
        end = t + dur
        clean = text.replace("\n", " ").strip()
        # ASS escape braces
        clean = clean.replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{clean}")
        t = end
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ass_ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _write_srt(scenes: list[str], durations: list[float], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = 0.0
    lines: list[str] = []
    for idx, (text, dur) in enumerate(zip(scenes, durations, strict=False), start=1):
        start = t
        end = t + dur
        lines.append(str(idx))
        lines.append(f"{_srt_ts(start)} --> {_srt_ts(end)}")
        lines.append(textwrap_short(text))
        lines.append("")
        t = end
    path.write_text("\n".join(lines), encoding="utf-8")


def textwrap_short(text: str, width: int = 42) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(text, width=width))


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_video(
    *,
    title: str,
    script: str = "",
    brief: str = "",
    entity_id: str = "ent_innerchispa",
    aspect: str = "9:16",
    max_scenes: int = 8,
    voice: str | None = None,
    language: str | None = None,
    transition: str = "smooth",
    qr_url: str = "",
    quality: str = "ultra",
    draft_id: str | None = None,
    auto_publish: bool = False,
    destinations: list[str] | None = None,
    whatsapp_status_jids: list[str] | None = None,
) -> dict[str, Any]:
    """Pipeline completo: guion → TTS (XTTS/Piper) → escenas → MP4."""
    from raphiia_openai import editorial_store, mongo_store

    limits = voices.video_limits()
    max_scenes_cap = int(limits.get("max_scenes") or 24)
    max_dur = float(limits.get("max_duration_sec") or 180)
    max_scenes = max(1, min(int(max_scenes), max_scenes_cap))

    started = now_local_iso()
    narration = (script or brief or title).strip()
    if not script and brief:
        gen = _ollama_narration_script(title, brief)
        if gen.get("script"):
            narration = gen["script"]

    voice_id = voice or voices.default_voice_id() or "auto"

    scenes = split_script(narration, max_scenes=max_scenes)
    if not scenes:
        return {"ok": False, "error": "empty script"}

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "video"
    ts = local_timestamp()
    out_dir = Path(EDITORIAL_VIDEO_ROOT) / entity_id / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    audio_path = out_dir / "narration.wav"
    tts_result = tts.synthesize(narration, audio_path, voice=voice_id, language=language)
    if not tts_result.get("ok"):
        return {"ok": False, "error": "tts failed", "tts": tts_result, "voice_requested": voice_id}

    audio_dur = float(tts_result.get("duration_sec") or assemble.probe_duration(audio_path) or len(scenes) * 4)
    if audio_dur > max_dur:
        return {
            "ok": False,
            "error": "duration_exceeds_limit",
            "duration_sec": audio_dur,
            "max_duration_sec": max_dur,
            "hint": f"Reduce script o max_scenes (actual {len(scenes)} escenas)",
        }

    scene_dur = [max(2.5, audio_dur / len(scenes))] * len(scenes)

    images: list[Path] = []
    image_providers: list[str] = []
    scene_prompts_used: list[str] = []
    for idx, scene in enumerate(scenes):
        img_path = out_dir / f"scene_{idx:03d}.jpg"
        visual = scene_prompts.visual_prompt_for_scene(
            scene,
            title=title,
            entity=entity_id,
            scene_index=idx,
            aspect=aspect,
            total_scenes=len(scenes),
        )
        scene_prompts_used.append(visual[:500])
        img = scene_images.generate_scene_image(
            visual,
            img_path,
            aspect=aspect,
            title=title,
            seed=idx * 137 + 42,
            quality=quality,
        )
        if not img.get("ok"):
            return {"ok": False, "error": f"scene image {idx} failed", "detail": img}
        images.append(Path(img["path"]))
        image_providers.append(str(img.get("provider") or "unknown"))

    w, h = assemble.ASPECT_PRESETS.get(aspect, assemble.ASPECT_PRESETS["9:16"])
    ass_path = out_dir / "subs.ass"
    _write_ass(scenes, scene_dur, ass_path, width=w, height=h)
    srt_path = out_dir / "subs.srt"
    _write_srt(scenes, scene_dur, srt_path)

    video_path = out_dir / f"{slug}.mp4"
    build = assemble.build_slideshow_video(
        images,
        audio_path,
        video_path,
        aspect=aspect,
        scene_durations=scene_dur,
        subtitles=ass_path,
        work_dir=out_dir / "_work",
        transition=transition if transition in ("none", "fade", "smooth") else "smooth",
    )
    if not build.get("ok"):
        return {"ok": False, "error": "video assembly failed", "detail": build}

    final_path = video_path
    qr_info: dict[str, Any] | None = None
    if qr_url.strip():
        qr_png = out_dir / "qr_overlay.png"
        qr_info = overlays.generate_qr_png(qr_url.strip(), qr_png)
        if qr_info.get("ok"):
            with_qr = out_dir / f"{slug}_qr.mp4"
            ov = overlays.overlay_image_on_video(video_path, qr_png, with_qr)
            if ov.get("ok"):
                final_path = with_qr
                qr_info["overlay"] = ov

    web_url = ""
    try:
        from raphiia_openai import artifact_delivery

        art = artifact_delivery.artifact_info(str(final_path), title=title)
        if art.get("ok"):
            web_url = str(art.get("public_url") or "")
    except Exception:
        pass
    if not web_url:
        try:
            from raphiia_openai.operational import web_content_manager

            web = web_content_manager.export_video_asset(str(final_path), title=title, caption=narration[:500])
            if web.get("ok"):
                web_url = str(web.get("public_url") or web.get("url") or "")
        except Exception:
            pass

    meta = {
        "title": title,
        "entity_id": entity_id,
        "aspect": aspect,
        "script": narration,
        "scenes": scenes,
        "duration_sec": build.get("duration_sec"),
        "video_path": str(final_path),
        "audio_path": str(audio_path),
        "tts_provider": tts_result.get("provider"),
        "voice_id": tts_result.get("voice_id") or voice_id,
        "image_providers": image_providers,
        "scene_prompts": scene_prompts_used,
        "image_checkpoint": __import__("raphiia_openai.local_image_runtime", fromlist=["_resolve_checkpoint"])._resolve_checkpoint(),
        "image_quality": quality,
        "transition": transition,
        "qr_url": qr_url or None,
        "web_url": web_url or None,
        "created_at": started,
    }
    (out_dir / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "ok": True,
        "video_path": str(final_path),
        "duration_sec": build.get("duration_sec"),
        "scenes": len(scenes),
        "aspect": aspect,
        "resolution": build.get("resolution"),
        "entity_id": entity_id,
        "manifest": str(out_dir / "manifest.json"),
        "tts": tts_result.get("provider"),
        "voice_id": tts_result.get("voice_id") or voice_id,
        "voice_natural": tts_result.get("provider") == "xtts-v2",
        "web_url": web_url or None,
        "lan_url": f"http://{os.getenv('RALFIA_LAN_IP', '192.168.1.5')}:8200/media/videos/{Path(final_path).name}",
        "limits": limits,
        "qr": qr_info,
    }

    if draft_id:
        attach = editorial_store.attach_video(
            draft_id,
            video_path=str(final_path),
            narration_script=narration,
            metadata=meta,
        )
        result["draft"] = attach

    if auto_publish:
        from raphiia_openai.video_pipeline.publish import publish_video

        pub = publish_video(
            str(final_path),
            title=title,
            caption=narration[:900],
            destinations=destinations or ["web"],
            whatsapp_status_jids=whatsapp_status_jids,
        )
        result["publish"] = pub

    try:
        mongo_store.log_coordination(
            agent="EDITORIAL",
            summary=f"Vídeo generado: {title} ({build.get('duration_sec')}s) voice={voice_id}",
            event="video_pipeline",
            project=entity_id,
            metadata={
                "video_path": str(final_path),
                "scenes": len(scenes),
                "duration_sec": float(build.get("duration_sec") or 0),
                "voice_id": str(voice_id),
            },
        )
    except Exception:
        pass
    return result
