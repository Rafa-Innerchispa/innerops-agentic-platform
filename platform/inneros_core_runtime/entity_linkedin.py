"""LinkedIn author URN por entidad (persona vs empresa)."""

from __future__ import annotations

from typing import Any

from raphiia_openai.mongo_store import get_db
from raphiia_openai import config_store
from raphiia_openai.settings import LINKEDIN_AUTHOR_URN


def _default_urn() -> str:
    return config_store.get("LINKEDIN_AUTHOR_URN") or LINKEDIN_AUTHOR_URN or ""


def get_entity(entity_id: str) -> dict[str, Any] | None:
    if not entity_id:
        return None
    return get_db().entities.find_one({"entity_id": entity_id.strip()}, {"_id": 0})


def resolve_author_urn(entity_id: str | None = None) -> tuple[str, dict[str, Any]]:
    """
    Devuelve (urn, meta) para publicar.
    Prioridad: entidad.linkedin_author_urn → LINKEDIN_AUTHOR_URN (.env).
    """
    ent: dict[str, Any] | None = None
    if entity_id:
        ent = get_entity(entity_id)
        urn = (ent or {}).get("linkedin_author_urn", "").strip()
        if urn:
            return urn, {
                "entity_id": entity_id,
                "entity_name": ent.get("name", ""),
                "publish_as": ent.get("linkedin_publish_as", ent.get("kind", "unknown")),
                "source": "entity",
            }
    default = (_default_urn() or "").strip()
    if not default:
        raise RuntimeError("LINKEDIN_AUTHOR_URN no configurado y entidad sin URN")
    ent_name = (ent or {}).get("name", entity_id or "sin entidad")
    return default, {
        "entity_id": entity_id or "",
        "entity_name": ent_name,
        "publish_as": "person",
        "source": "env_default",
        "warning": (
            f"La entidad «{ent_name}» no tiene linkedin_author_urn — "
            f"se publica con el URN default (.env), normalmente tu perfil personal."
        ),
    }


def list_entities_for_editorial() -> list[dict[str, Any]]:
    from raphiia_openai import editorial_social

    rows = list(
        get_db().entities.find({"status": "active"}, {"_id": 0}).sort("name", 1)
    )
    out = []
    for ent in rows:
        eid = ent.get("entity_id", "")
        prev = editorial_social.publish_preview(eid)
        out.append(
            {
                **ent,
                "linkedin_ready": prev.get("can_publish", False),
                "linkedin_label": prev.get("destination_summary", ent.get("name", "")),
                "linkedin_status": prev.get("status", ""),
                "uses_fallback": prev.get("uses_fallback", False),
            }
        )
    return out


def _label(ent: dict[str, Any], urn: str) -> str:
    kind = ent.get("linkedin_publish_as") or ent.get("kind", "")
    if urn:
        short = urn.rsplit(":", 1)[-1][:12]
        return f"{ent.get('name', '')} ({kind}) · …{short}"
    if _default_urn():
        return f"{ent.get('name', '')} → default .env (Rafael)"
    return f"{ent.get('name', '')} — sin URN LinkedIn"
