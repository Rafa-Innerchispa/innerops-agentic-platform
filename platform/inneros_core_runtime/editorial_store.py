"""Mongo editorial pipeline → posts → social publish."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pathlib import Path

from bson import ObjectId

from raphiia_openai.mongo_store import _now_iso, _oid, _serialize, get_db, log_coordination
from raphiia_openai.settings import (
    COL_EDITORIAL_PIPELINE,
    COL_EDITORIAL_POSTS,
    COL_MEDIA_LIBRARY,
    COL_SOCIAL_DESTINATIONS,
)

STATUS_DRAFT = "draft"
STATUS_GENERATING = "generating_image"
STATUS_REVIEW = "ready_for_review"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
VALID_PIPELINE_STATUSES = {
    STATUS_DRAFT,
    STATUS_GENERATING,
    STATUS_REVIEW,
    STATUS_APPROVED,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
    STATUS_FAILED,
    "scheduled",
}


def _parse_id(raw: str) -> ObjectId | None:
    return _oid(raw.strip())


def list_entities(*, active_only: bool = True, limit: int = 50) -> list[dict[str, Any]]:
    db = get_db()
    filt: dict[str, Any] = {"status": "active"} if active_only else {}
    cursor = (
        db.entities.find(filt, {"_id": 0, "entity_id": 1, "name": 1, "kind": 1, "slug": 1})
        .sort("name", 1)
        .limit(max(1, min(limit, 100)))
    )
    return list(cursor)


def list_drafts(
    *,
    channel: str | None = None,
    entity_id: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = get_db()
    filt: dict[str, Any] = {}
    if channel:
        filt["channel"] = channel.strip().lower()
    if entity_id:
        filt["entity_id"] = entity_id.strip()
    if status:
        filt["status"] = status
    elif not include_archived:
        filt["status"] = {"$nin": [STATUS_REJECTED, STATUS_PUBLISHED]}
    cursor = db[COL_EDITORIAL_PIPELINE].find(filt).sort("updated_at", -1).limit(max(1, min(limit, 100)))
    return [_serialize(d) for d in cursor]


def reopen_draft(draft_id: str) -> dict[str, Any]:
    """Devuelve borrador rechazado/aprobado a edición."""
    r = get_draft(draft_id)
    if not r.get("ok"):
        return r
    st = r["draft"].get("status")
    if st == STATUS_PUBLISHED:
        return {"ok": False, "error": "already published — duplica el borrador"}
    return update_draft(
        draft_id,
        {"status": STATUS_DRAFT, "reject_reason": "", "reopened_at": _now_iso()},
    )


def duplicate_draft(draft_id: str) -> dict[str, Any]:
    db = get_db()
    r = get_draft(draft_id)
    if not r.get("ok"):
        return r
    src = r["draft"]
    now = _now_iso()
    doc = {
        "channel": src.get("channel", "linkedin"),
        "markdown": src.get("markdown", src.get("body", "")),
        "body": src.get("body", src.get("markdown", "")),
        "title": (src.get("title") or "Borrador") + " (copia)",
        "status": STATUS_DRAFT,
        "source": "duplicate",
        "metadata": src.get("metadata") or {},
        "localizations": src.get("localizations") or {},
        "publication_lang": src.get("publication_lang", "es"),
        "linkedin_visibility": src.get("linkedin_visibility", "PUBLIC"),
        "entity_id": src.get("entity_id", ""),
        "duplicated_from": draft_id,
        "created_at": now,
        "updated_at": now,
    }
    res = db[COL_EDITORIAL_PIPELINE].insert_one(doc)
    doc["_id"] = res.inserted_id
    return {"ok": True, "draft": _serialize(doc)}


def save_localization(draft_id: str, lang: str, *, title: str, markdown: str) -> dict[str, Any]:
    db = get_db()
    oid = _parse_id(draft_id)
    if not oid:
        return {"ok": False, "error": "invalid id"}
    key = f"localizations.{lang}"
    db[COL_EDITORIAL_PIPELINE].update_one(
        {"_id": oid},
        {
            "$set": {
                key: {"title": title, "markdown": markdown, "updated_at": _now_iso()},
                "updated_at": _now_iso(),
            }
        },
    )
    return get_draft(draft_id)


def switch_publication_lang(draft_id: str, lang: str, *, title: str | None = None, markdown: str | None = None) -> dict[str, Any]:
    """Cambia idioma activo; carga localización guardada si existe."""
    r = get_draft(draft_id)
    if not r.get("ok"):
        return r
    draft = r["draft"]
    locs = draft.get("localizations") or {}
    patch: dict[str, Any] = {"publication_lang": lang, "updated_at": _now_iso()}
    if lang in locs:
        patch["title"] = locs[lang].get("title", draft.get("title", ""))
        patch["markdown"] = locs[lang].get("markdown", draft.get("markdown", ""))
        patch["body"] = patch["markdown"]
    elif title is not None and markdown is not None:
        patch["title"] = title
        patch["markdown"] = markdown
        patch["body"] = markdown
    return update_draft(draft_id, patch)


def get_draft(draft_id: str) -> dict[str, Any]:
    db = get_db()
    oid = _parse_id(draft_id)
    if not oid:
        return {"ok": False, "error": "invalid id"}
    doc = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    if not doc:
        return {"ok": False, "error": "not found"}
    return {"ok": True, "draft": _serialize(doc)}


def update_draft(draft_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    oid = _parse_id(draft_id)
    if not oid:
        return {"ok": False, "error": "invalid id"}
    patch = {k: v for k, v in patch.items() if k != "_id"}
    patch["updated_at"] = _now_iso()
    db[COL_EDITORIAL_PIPELINE].update_one({"_id": oid}, {"$set": patch})
    doc = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    return {"ok": True, "draft": _serialize(doc) if doc else {}}


def update_pipeline_status(draft_id: str, status: str) -> dict[str, Any]:
    normalized = (status or "").strip().lower()
    if normalized not in VALID_PIPELINE_STATUSES:
        return {"ok": False, "error": f"invalid status: {status}"}
    patch = {"status": normalized}
    if normalized == "ready_for_review":
        patch["status"] = STATUS_REVIEW
    return update_draft(draft_id, patch)


def drafts_needing_image(limit: int = 5) -> list[dict[str, Any]]:
    db = get_db()
    filt = {
        "status": {"$in": [STATUS_DRAFT, STATUS_GENERATING]},
        "$or": [{"media_path": {"$exists": False}}, {"media_path": ""}, {"media_path": None}],
    }
    cursor = db[COL_EDITORIAL_PIPELINE].find(filt).sort("created_at", 1).limit(limit)
    return [_serialize(d) for d in cursor]


def attach_media(
    draft_id: str,
    *,
    media_path: str,
    media_prompt: str,
    provider: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    oid = _parse_id(draft_id)
    if not oid:
        return {"ok": False, "error": "invalid id"}
    now = _now_iso()
    draft = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    if not draft:
        return {"ok": False, "error": "not found"}
    meta = dict(metadata or {})
    provider_n = (provider or "").strip()
    media_doc = {
        "path": media_path,
        "prompt": media_prompt,
        "provider": provider_n,
        "model": meta.get("model", ""),
        "backend": meta.get("backend", ""),
        "seed": meta.get("seed"),
        "prompt_effective": meta.get("prompt_effective") or media_prompt,
        "prompt_id": meta.get("prompt_id", ""),
        "request_id": meta.get("request_id", ""),
        "warnings": meta.get("warnings", []),
        "metadata": meta,
        "channel": draft.get("channel", "linkedin"),
        "draft_id": str(oid),
        "created_at": now,
    }
    mres = db[COL_MEDIA_LIBRARY].insert_one(media_doc)
    db[COL_EDITORIAL_PIPELINE].update_one(
        {"_id": oid},
        {
            "$set": {
                "media_path": media_path,
                "media_prompt": media_prompt,
                "image_provider": provider_n,
                "image_model": meta.get("model", ""),
                "image_backend": meta.get("backend", ""),
                "image_seed": meta.get("seed"),
                "image_prompt_effective": meta.get("prompt_effective") or media_prompt,
                "image_prompt_id": meta.get("prompt_id", ""),
                "image_request_id": meta.get("request_id", ""),
                "image_warnings": meta.get("warnings", []),
                "image_generated_at": now,
                "status": STATUS_REVIEW,
                "updated_at": now,
            }
        },
    )
    log_coordination(
        agent="EDITORIAL",
        summary=f"Imagen generada draft {draft_id}",
        event="editorial_image",
        project="editorial",
        metadata={"media_id": str(mres.inserted_id), "provider": provider_n, "model": meta.get("model", "")},
    )
    doc = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    return {"ok": True, "draft": _serialize(doc) if doc else {}}


def attach_video(
    draft_id: str,
    *,
    video_path: str,
    narration_script: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    oid = _parse_id(draft_id)
    if not oid:
        return {"ok": False, "error": "invalid id"}
    now = _now_iso()
    draft = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    if not draft:
        return {"ok": False, "error": "not found"}
    media_doc = {
        "path": video_path,
        "kind": "video",
        "narration_script": narration_script,
        "metadata": metadata or {},
        "channel": draft.get("channel", "linkedin"),
        "draft_id": str(oid),
        "created_at": now,
    }
    mres = db[COL_MEDIA_LIBRARY].insert_one(media_doc)
    db[COL_EDITORIAL_PIPELINE].update_one(
        {"_id": oid},
        {
            "$set": {
                "video_path": video_path,
                "media_path": video_path,
                "narration_script": narration_script,
                "video_metadata": metadata or {},
                "status": STATUS_REVIEW,
                "updated_at": now,
            }
        },
    )
    log_coordination(
        agent="EDITORIAL",
        summary=f"Vídeo generado draft {draft_id}",
        event="editorial_video",
        project="editorial",
        metadata={"media_id": str(mres.inserted_id), "video_path": video_path},
    )
    doc = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    return {"ok": True, "draft": _serialize(doc) if doc else {}}


def drafts_needing_video(limit: int = 3) -> list[dict[str, Any]]:
    db = get_db()
    filt = {
        "status": {"$in": [STATUS_DRAFT, STATUS_REVIEW, STATUS_APPROVED]},
        "$or": [{"video_path": {"$exists": False}}, {"video_path": ""}, {"video_path": None}],
        "generate_video": True,
    }
    cursor = db[COL_EDITORIAL_PIPELINE].find(filt).sort("created_at", 1).limit(limit)
    return [_serialize(d) for d in cursor]


REAL_IMAGE_PROVIDERS = frozenset(
    {
        "google_imagen",
        "google_gemini",
        "chatgpt_dalle",
        "chatgpt_native",
        "chatgpt_url",
        "mcp_upload",
    }
)


def linkedin_media_path(post: dict[str, Any] | None) -> str:
    """Imagen real en disco para LinkedIn; placeholder o archivo ausente → solo texto."""
    if not post:
        return ""
    provider = (post.get("image_provider") or "").strip().lower()
    if provider == "placeholder":
        return ""
    path = (post.get("media_path") or "").strip()
    if not path:
        return ""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return ""
    return path


def approve_draft(draft_id: str, approved_by: str = "rafael") -> dict[str, Any]:
    db = get_db()
    oid = _parse_id(draft_id)
    if not oid:
        return {"ok": False, "error": "invalid id"}
    draft = db[COL_EDITORIAL_PIPELINE].find_one({"_id": oid})
    if not draft:
        return {"ok": False, "error": "not found"}
    now = _now_iso()
    post = {
        "pipeline_id": str(oid),
        "channel": draft.get("channel", "linkedin"),
        "title": draft.get("title", ""),
        "markdown": draft.get("markdown", draft.get("body", "")),
        "body": draft.get("body", draft.get("markdown", "")),
        "media_path": draft.get("media_path", ""),
        "image_provider": draft.get("image_provider", ""),
        "image_model": draft.get("image_model", ""),
        "image_backend": draft.get("image_backend", ""),
        "image_seed": draft.get("image_seed"),
        "image_prompt_effective": draft.get("image_prompt_effective", draft.get("media_prompt", "")),
        "image_prompt_id": draft.get("image_prompt_id", ""),
        "image_request_id": draft.get("image_request_id", ""),
        "image_warnings": draft.get("image_warnings", []),
        "image_generated_at": draft.get("image_generated_at", ""),
        "publication_lang": draft.get("publication_lang", "es"),
        "linkedin_visibility": draft.get("linkedin_visibility", "PUBLIC"),
        "entity_id": draft.get("entity_id", ""),
        "linkedin_author_urn": draft.get("linkedin_author_urn", ""),
        "localizations": draft.get("localizations") or {},
        "status": STATUS_APPROVED,
        "approved_by": approved_by,
        "approved_at": now,
        "created_at": now,
        "updated_at": now,
        "source": draft.get("source", "editorial_hub"),
    }
    pres = db[COL_EDITORIAL_POSTS].insert_one(post)
    post_id = str(pres.inserted_id)
    dest = {
        "post_id": post_id,
        "pipeline_id": str(oid),
        "platform": draft.get("channel", "linkedin"),
        "entity_id": draft.get("entity_id", ""),
        "status": "queued",
        "created_at": now,
        "updated_at": now,
    }
    dres = db[COL_SOCIAL_DESTINATIONS].insert_one(dest)
    db[COL_EDITORIAL_PIPELINE].update_one(
        {"_id": oid},
        {"$set": {"status": STATUS_APPROVED, "post_id": post_id, "updated_at": now}},
    )
    log_coordination(
        agent="EDITORIAL",
        summary=f"Aprobado draft {draft_id} → post {post_id}",
        event="editorial_approve",
        project="editorial",
    )
    return {
        "ok": True,
        "post_id": post_id,
        "destination_id": str(dres.inserted_id),
        "draft_id": str(oid),
    }


def reject_draft(draft_id: str, reason: str = "") -> dict[str, Any]:
    return update_draft(draft_id, {"status": STATUS_REJECTED, "reject_reason": reason})


def list_queued_destinations(limit: int = 10) -> list[dict[str, Any]]:
    db = get_db()
    cursor = (
        db[COL_SOCIAL_DESTINATIONS]
        .find({"status": "queued"})
        .sort("created_at", 1)
        .limit(limit)
    )
    return [_serialize(d) for d in cursor]


def get_post(post_id: str) -> dict[str, Any] | None:
    db = get_db()
    oid = _parse_id(post_id)
    if not oid:
        return None
    doc = db[COL_EDITORIAL_POSTS].find_one({"_id": oid})
    return _serialize(doc) if doc else None


def mark_destination(
    destination_id: str,
    *,
    status: str,
    linkedin_urn: str | None = None,
    error: str | None = None,
) -> None:
    db = get_db()
    oid = _parse_id(destination_id)
    if not oid:
        return
    patch: dict[str, Any] = {"status": status, "updated_at": _now_iso()}
    if linkedin_urn:
        patch["linkedin_post_urn"] = linkedin_urn
    if error:
        patch["error"] = error[:2000]
    db[COL_SOCIAL_DESTINATIONS].update_one({"_id": oid}, {"$set": patch})


def mark_post_published(post_id: str, linkedin_urn: str) -> None:
    db = get_db()
    oid = _parse_id(post_id)
    if not oid:
        return
    now = _now_iso()
    db[COL_EDITORIAL_POSTS].update_one(
        {"_id": oid},
        {"$set": {"status": STATUS_PUBLISHED, "linkedin_post_urn": linkedin_urn, "published_at": now}},
    )
    pid = db[COL_EDITORIAL_POSTS].find_one({"_id": oid})
    if pid and pid.get("pipeline_id"):
        poid = _parse_id(pid["pipeline_id"])
        if poid:
            db[COL_EDITORIAL_PIPELINE].update_one(
                {"_id": poid},
                {"$set": {"status": STATUS_PUBLISHED, "updated_at": now}},
            )
