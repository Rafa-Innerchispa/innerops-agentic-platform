#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter

from PIL import Image, ImageDraw, ImageFont

from raphiia_openai import whatsapp_media


def evolution_payload(message_id: str, kind: str, mimetype: str, size: int, *, seconds: int = 0, caption: str = ""):
    return {
        "event": "messages.upsert",
        "instance": "OPENAI-DEMO-FIXTURE",
        "data": {
            "key": {"id": message_id, "remoteJid": "fixture@s.whatsapp.net", "fromMe": False},
            "message": {
                f"{kind}Message": {
                    "mimetype": mimetype,
                    "fileLength": size,
                    "seconds": seconds,
                    "caption": caption,
                }
            },
        },
    }


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="ralfia-multimodal-e2e-") as directory:
        root = Path(directory)
        audio = root / "synthetic-command.ogg"
        image = root / "synthetic-quote.png"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "flite=text='Codex run the synthetic project tests'",
                "-c:a", "libopus", str(audio),
            ],
            check=True,
            timeout=60,
        )
        canvas = Image.new("RGB", (1200, 720), "white")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        draw.multiline_text(
            (90, 120),
            "PC DOCTOR — OPENAI DEMO\n\nQUOTE REQUEST\n2 SECURITY CAMERAS\n1 ACCESS CONTROLLER\n\nSYNTHETIC — NO PRIVATE DATA",
            fill="black",
            spacing=22,
            font=font,
        )
        canvas.save(image)

        old_root = whatsapp_media.MEDIA_ROOT
        whatsapp_media.MEDIA_ROOT = root / "cache"
        try:
            audio_bytes = audio.read_bytes()
            image_bytes = image.read_bytes()
            audio_payload = evolution_payload(
                "OPENAI-DEMO-AUDIO-001", "audio", "audio/ogg", len(audio_bytes), seconds=3
            )
            image_payload = evolution_payload(
                "OPENAI-DEMO-IMAGE-001",
                "image",
                "image/png",
                len(image_bytes),
                caption="Necesito una cotización borrador; no enviar sin aprobación.",
            )
            started = perf_counter()
            audio_result = whatsapp_media.process_media(
                audio_payload,
                node="primary",
                downloader=lambda *_: base64.b64encode(audio_bytes).decode(),
            )
            audio_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            image_result = whatsapp_media.process_media(
                image_payload,
                node="primary",
                downloader=lambda *_: base64.b64encode(image_bytes).decode(),
            )
            image_ms = (perf_counter() - started) * 1000
            duplicate = whatsapp_media.process_media(
                image_payload,
                node="primary",
                downloader=lambda *_: (_ for _ in ()).throw(RuntimeError("duplicate downloaded twice")),
            )
        finally:
            whatsapp_media.MEDIA_ROOT = old_root

    transcript = (audio_result.get("transcript") or {}).get("text", "")
    ocr_text = (image_result.get("ocr") or {}).get("text", "")
    vision_text = (image_result.get("vision") or {}).get("text", "")
    passed = bool(
        audio_result.get("processing_status") == "processed"
        and transcript
        and image_result.get("processing_status") in {"processed", "partial"}
        and ocr_text
        and duplicate.get("idempotent") is True
    )
    return {
        "ok": passed,
        "fixture": "SYNTHETIC_NO_PII",
        "audio": {
            "message_id": "OPENAI-DEMO-AUDIO-001",
            "media_key": audio_result.get("media_key"),
            "checksum": audio_result.get("checksum"),
            "status": audio_result.get("processing_status"),
            "normalized": audio_result.get("audio_normalized"),
            "provider": (audio_result.get("transcript") or {}).get("provider"),
            "language": (audio_result.get("transcript") or {}).get("language"),
            "confidence": (audio_result.get("transcript") or {}).get("confidence"),
            "text": transcript,
            "latency_ms": round(audio_ms, 2),
        },
        "image": {
            "message_id": "OPENAI-DEMO-IMAGE-001",
            "media_key": image_result.get("media_key"),
            "checksum": image_result.get("checksum"),
            "status": image_result.get("processing_status"),
            "ocr_provider": (image_result.get("ocr") or {}).get("provider"),
            "ocr_text": ocr_text[:500],
            "vision_provider": (image_result.get("vision") or {}).get("provider"),
            "vision_model": (image_result.get("vision") or {}).get("model"),
            "vision_text": vision_text[:700],
            "latency_ms": round(image_ms, 2),
        },
        "idempotency": {
            "second_status": duplicate.get("status"),
            "idempotent": duplicate.get("idempotent"),
        },
        "paid_api_calls": 0,
    }


if __name__ == "__main__":
    evidence = run()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    raise SystemExit(0 if evidence["ok"] else 1)
