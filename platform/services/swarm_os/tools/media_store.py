import shutil
import uuid
from pathlib import Path

from config import MEDIA_DIR
from tools.mongo import get_inspection, update_inspection


def save_upload(inspection_id: str, filename: str, content: bytes) -> dict:
    folder = MEDIA_DIR / inspection_id
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    path = folder / safe_name
    path.write_bytes(content)
    entry = {"filename": safe_name, "path": str(path), "kind": _guess_kind(filename)}
    insp = get_inspection(inspection_id)
    media = (insp or {}).get("media", [])
    media.append(entry)
    update_inspection(inspection_id, {"media": media})
    return entry


def _guess_kind(filename: str) -> str:
    low = filename.lower()
    if low.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "photo"
    if low.endswith((".mp3", ".wav", ".m4a", ".ogg")):
        return "audio"
    return "file"
