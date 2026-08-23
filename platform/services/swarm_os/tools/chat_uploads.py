"""Archivos subidos desde el Centro de Datos."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import CHAT_UPLOADS_DIR


def save_chat_file(session_id: str, filename: str, content: bytes) -> dict:
    folder = CHAT_UPLOADS_DIR / session_id
    folder.mkdir(parents=True, exist_ok=True)
    safe = f"{uuid.uuid4().hex[:8]}_{filename}"
    path = folder / safe
    path.write_bytes(content)
    return {
        "file_id": f"fil_{uuid.uuid4().hex[:12]}",
        "filename": filename,
        "stored_as": safe,
        "path": str(path),
        "size": len(content),
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
