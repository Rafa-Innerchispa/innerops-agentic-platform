"""Transcripción de audio local vía Whisper ASR (Docker :9001)."""

from pathlib import Path

import requests

from config import WHISPER_URL


def transcribe_audio_file(path: str | Path, language: str = "es") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    with path.open("rb") as f:
        r = requests.post(
            f"{WHISPER_URL.rstrip('/')}/asr",
            params={"task": "transcribe", "language": language, "output": "json"},
            files={"audio_file": (path.name, f, _mime(path))},
            timeout=300,
        )
    r.raise_for_status()
    try:
        body = r.json()
        text = body.get("text") or body.get("transcription") or str(body)
    except Exception:
        text = r.text.strip()
    return {"text": text, "language": language, "source": "whisper_local", "file": str(path)}


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")
