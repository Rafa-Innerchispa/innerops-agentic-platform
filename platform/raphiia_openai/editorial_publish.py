"""Publicar cola social → LinkedIn."""

from __future__ import annotations

from bson import ObjectId

from raphiia_openai import editorial_store, linkedin_client
from raphiia_openai.editorial_social import PublishBlockedError, resolve_for_publish
from raphiia_openai.mongo_store import get_db, log_coordination
from raphiia_openai.settings import COL_SOCIAL_DESTINATIONS


def publish_destination(destination_id: str, *, allow_personal_fallback: bool = False) -> dict:
    db = get_db()
    try:
        oid = ObjectId(destination_id)
    except Exception:
        return {"ok": False, "error": "invalid destination id"}
    dest = db[COL_SOCIAL_DESTINATIONS].find_one({"_id": oid})
    if not dest:
        return {"ok": False, "error": "destination not found"}
    post = editorial_store.get_post(dest.get("post_id", ""))
    if not post:
        return {"ok": False, "error": "post not found"}
    text = post.get("markdown") or post.get("body") or ""
    media = editorial_store.linkedin_media_path(post)
    visibility = post.get("linkedin_visibility") or "PUBLIC"
    media_title = post.get("title") or "Ralphi IA"
    entity_id = post.get("entity_id") or dest.get("entity_id") or ""
    try:
        author_urn, author_meta = resolve_for_publish(
            entity_id or None,
            allow_personal_fallback=allow_personal_fallback,
        )
    except PublishBlockedError as exc:
        p = exc.preview
        return {
            "ok": False,
            "error": p.get("destination_summary") or "destino no configurado",
            "blocked": True,
            "preview": p,
            "hint": "Configura URN en Destinos LinkedIn del panel editorial o confirma fallback personal.",
        }
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        if not linkedin_client.config_status().get("ready") and not author_urn:
            editorial_store.mark_destination(destination_id, status="pending_linkedin_config")
            return {"ok": False, "error": "LinkedIn no configurado — post en cola", "queued": True}
        if media:
            pub = linkedin_client.publish_with_image(
                text, media, media_title=media_title, visibility=visibility, author_urn=author_urn
            )
            publish_mode = "with_image"
        else:
            raw = linkedin_client.publish_post(
                text=text, media_title=media_title, visibility=visibility, author_urn=author_urn
            )
            pub = {"ok": True, "linkedin_urn": raw.get("id", ""), "raw": raw}
            publish_mode = "text_only"
        urn = pub.get("linkedin_urn", "")
        editorial_store.mark_destination(destination_id, status="published", linkedin_urn=urn)
        if entity_id:
            db[COL_SOCIAL_DESTINATIONS].update_one(
                {"_id": oid}, {"$set": {"entity_id": entity_id, "linkedin_author_urn": author_urn}}
            )
        editorial_store.mark_post_published(dest["post_id"], urn)
        log_coordination(
            agent="EDITORIAL",
            summary=f"LinkedIn publicado {urn} ({publish_mode}) como {author_meta.get('entity_name', '?')}",
            event="linkedin_publish",
            metadata={
                "publish_mode": publish_mode,
                "image_provider": post.get("image_provider"),
                "entity_id": entity_id,
                "author_meta": author_meta,
                "destination_summary": author_meta.get("destination_summary"),
                "author_urn_display": author_meta.get("author_urn_display"),
            },
        )
        return {
            "ok": True,
            "linkedin_urn": urn,
            "publish_mode": publish_mode,
            "author": author_meta,
            "warning": author_meta.get("warning"),
        }
    except Exception as exc:
        err = str(exc)
        # Si falló imagen pero hay texto, intentar solo texto (ChatGPT a veces deja media_path inválido)
        if media and (
            "registerUpload" in err or "upload" in err.lower() or "imagen" in err.lower()
        ):
            try:
                raw = linkedin_client.publish_post(
                    text=text, media_title=media_title, visibility=visibility, author_urn=author_urn
                )
                urn = raw.get("id", "")
                editorial_store.mark_destination(destination_id, status="published", linkedin_urn=urn)
                editorial_store.mark_post_published(dest["post_id"], urn)
                log_coordination(
                    agent="EDITORIAL",
                    summary=f"LinkedIn publicado {urn} (text_only_fallback) — imagen falló: {err[:120]}",
                    event="linkedin_publish",
                    metadata={"publish_mode": "text_only_fallback", "image_error": err[:300], "entity_id": entity_id},
                )
                return {
                    "ok": True,
                    "linkedin_urn": urn,
                    "publish_mode": "text_only_fallback",
                    "author": author_meta,
                    "image_error": err[:300],
                    "warning": "Publicado sin imagen — revisa media_path o permisos LinkedIn upload",
                }
            except Exception as exc2:
                err = f"{err}; fallback: {exc2}"
        editorial_store.mark_destination(destination_id, status="failed", error=err)
        return {"ok": False, "error": err}
