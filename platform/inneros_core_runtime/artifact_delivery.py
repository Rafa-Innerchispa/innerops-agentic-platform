"""URLs públicas para vídeos/imágenes generados localmente (Artifact Delivery)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

MEDIA_WEB_ROOT = Path(os.getenv("MEDIA_WEB_ROOT", "/home/rlopez/data/media/web"))
MEDIA_VIDEOS_DIR = MEDIA_WEB_ROOT / "videos"
MEDIA_IMAGES_DIR = MEDIA_WEB_ROOT / "images"

DEFAULT_PUBLIC_BASES = (
    "https://voz.pcdoctor.ai",
    "https://sworn-profusely-alongside.ngrok-free.dev",
)


def _public_bases() -> list[str]:
    bases: list[str] = []
    for key in ("MEDIA_PUBLIC_BASE_URL", "ARTIFACT_PUBLIC_BASE_URL", "VOICE_PUBLIC_URL"):
        val = os.getenv(key, "").strip().rstrip("/")
        if val and val not in bases:
            bases.append(val)
    pub_file = Path(os.getenv("VOICE_PUBLIC_URL_FILE", "/home/rlopez/data/ralfia/voice_public_url.txt"))
    if pub_file.is_file():
        for line in pub_file.read_text(encoding="utf-8").splitlines():
            u = line.strip().rstrip("/")
            if u.startswith("https://") and u not in bases:
                bases.append(u)
    for u in DEFAULT_PUBLIC_BASES:
        if u not in bases:
            bases.append(u)
    return bases


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not re.match(r"^[A-Za-z0-9._-]+\.(mp4|webm|mov|jpg|jpeg|png|webp)$", base):
        raise ValueError("invalid_media_filename")
    return base


def publish_video_copy(src: Path) -> Path:
    MEDIA_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MEDIA_VIDEOS_DIR / src.name
    if src.resolve() != dest.resolve():
        import shutil

        shutil.copy2(src, dest)
    return dest


def public_url_for_video(filename: str, *, base_index: int = 0) -> str:
    safe = _safe_filename(filename)
    bases = _public_bases()
    base = bases[min(base_index, len(bases) - 1)] if bases else "https://voz.pcdoctor.ai"
    return f"{base}/media/videos/{safe}"


def public_url_for_local_path(path: str | Path) -> str | None:
    p = Path(path).resolve()
    try:
        videos_root = MEDIA_VIDEOS_DIR.resolve()
        if p.is_file() and (p.parent == videos_root or videos_root in p.parents):
            return public_url_for_video(p.name)
        if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mov"}:
            staged = publish_video_copy(p)
            return public_url_for_video(staged.name)
    except (ValueError, OSError):
        return None
    return None


def artifact_info(path: str | Path, *, title: str = "") -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"file not found: {p}"}
    staged = publish_video_copy(p) if p.suffix.lower() in {".mp4", ".webm", ".mov"} else p
    pub = public_url_for_video(staged.name) if staged.suffix.lower() in {".mp4", ".webm", ".mov"} else None
    lan_ip = os.getenv("RALFIA_LAN_IP", "192.168.1.5")
    return {
        "ok": True,
        "path": str(p),
        "staged_path": str(staged),
        "title": title or p.stem,
        "public_url": pub,
        "public_urls": [public_url_for_video(staged.name, base_index=i) for i in range(len(_public_bases()))],
        "lan_url": f"http://{lan_ip}:8200/media/videos/{staged.name}",
    }
