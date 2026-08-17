"""Asset registry — imágenes/archivos ChatGPT → pipeline editorial."""

from __future__ import annotations

import base64
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

from raphiia_openai import editorial_store, mongo_store
from raphiia_openai.settings import COL_ASSET_REGISTRY

ASSET_ROOT = Path("/home/rlopez/data/media/assets")
_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _asset_path(asset_id: str, ext: str = "png") -> Path:
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    return ASSET_ROOT / f"{asset_id}.{ext}"


def register_asset(
    *,
    asset_type: str = "image",
    source: str = "chatgpt",
    mime_type: str = "image/png",
    image_base64: str = "",
    image_url: str = "",
    file_path: str = "",
    prompt: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    now = _now_iso()
    ext = _MIME_EXT.get(mime_type.lower(), "bin")
    temp_id = ObjectId()
    aid = str(temp_id)
    out = _asset_path(aid, ext=ext)

    if image_base64.strip():
        from raphiia_openai import editorial_media_upload

        data, ext2 = editorial_media_upload._decode_base64_image(image_base64)
        ext = ext2
        out = _asset_path(aid, ext=ext)
        out.write_bytes(data)
        bytes_len = len(data)
    elif image_url.strip():
        req = urllib.request.Request(image_url.strip(), headers={"User-Agent": "RalfIA-MCP/1.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
        out.write_bytes(data)
        bytes_len = len(data)
    elif file_path.strip():
        src = Path(file_path)
        if not src.is_file():
            return {"ok": False, "error": "file_path not found"}
        data = src.read_bytes()
        ext = src.suffix.lstrip(".") or ext
        out = _asset_path(aid, ext=ext)
        out.write_bytes(data)
        bytes_len = len(data)
    else:
        return {"ok": False, "error": "provide image_base64, image_url, or file_path"}

    doc = {
        "_id": temp_id,
        "asset_type": asset_type,
        "source": source,
        "mime_type": mime_type,
        "path": str(out),
        "prompt": prompt,
        "bytes": bytes_len,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }
    db[COL_ASSET_REGISTRY].insert_one(doc)
    mongo_store.log_coordination(
        agent=source.upper(),
        summary=f"Asset registrado {aid} ({source})",
        event="asset_registered",
        project="editorial",
        metadata={"asset_id": aid, "bytes": bytes_len},
    )
    return {"ok": True, "asset_id": aid, "path": str(out), "asset": _serialize(doc)}


def list_assets(
    asset_type: str | None = None,
    source: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    filt: dict[str, Any] = {}
    if asset_type:
        filt["asset_type"] = asset_type
    if source:
        filt["source"] = source
    cursor = db[COL_ASSET_REGISTRY].find(filt).sort("created_at", -1).limit(max(1, min(limit, 100)))
    items = [_serialize(d) for d in cursor]
    return {"ok": True, "count": len(items), "assets": items}


def attach_asset_to_pipeline(asset_id: str, draft_id: str) -> dict[str, Any]:
    db = mongo_store.get_db()
    try:
        oid = ObjectId(asset_id)
    except Exception:
        return {"ok": False, "error": "invalid asset_id"}
    asset = db[COL_ASSET_REGISTRY].find_one({"_id": oid})
    if not asset:
        return {"ok": False, "error": "asset not found"}
    path = asset.get("path", "")
    if not path or not Path(path).is_file():
        return {"ok": False, "error": "asset file missing"}
    source = (asset.get("source") or "chatgpt").lower()
    provider = f"chatgpt_{source}" if not source.startswith("chatgpt") else source
    if provider == "chatgpt":
        provider = "chatgpt_native"
    result = editorial_store.attach_media(
        draft_id,
        media_path=path,
        media_prompt=asset.get("prompt") or f"Asset {asset_id}",
        provider=provider,
    )
    db[COL_ASSET_REGISTRY].update_one(
        {"_id": oid},
        {"$set": {"draft_id": draft_id, "attached_at": _now_iso(), "updated_at": _now_iso()}},
    )
    return {"ok": True, "asset_id": asset_id, "draft_id": draft_id, **result}
