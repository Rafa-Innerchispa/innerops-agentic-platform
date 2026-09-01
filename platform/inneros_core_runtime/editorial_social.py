"""Destinos LinkedIn por entidad — separa marca editorial vs cuenta real."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from raphiia_openai import config_store, mongo_store
from raphiia_openai.settings import LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN

COL = "editorial_linkedin_accounts"

DEFAULT_ACCOUNTS = [
    {
        "entity_id": "ent_rafael_personal",
        "label": "Rafael López — perfil personal",
        "account_type": "personal",
        "platform": "linkedin",
        "allow_env_fallback": True,
        "is_default": True,
    },
    {
        "entity_id": "ent_innerchispa",
        "label": "InnerChispa — página LinkedIn",
        "account_type": "organization",
        "platform": "linkedin",
        "allow_env_fallback": False,
        "is_default": False,
    },
    {
        "entity_id": "ent_innerspark",
        "label": "InnerSpark — página LinkedIn",
        "account_type": "organization",
        "platform": "linkedin",
        "allow_env_fallback": False,
        "is_default": False,
    },
    {
        "entity_id": "ent_pcdoctor",
        "label": "PC Doctor S.A. — página LinkedIn",
        "account_type": "organization",
        "platform": "linkedin",
        "allow_env_fallback": False,
        "is_default": False,
    },
]

STANDARD_ENTITIES = [
    {
        "entity_id": "ent_rafael_personal",
        "name": "Rafael López",
        "slug": "rafael-lopez",
        "kind": "person",
        "status": "active",
        "linkedin_publish_as": "person",
    },
    {
        "entity_id": "ent_innerchispa",
        "name": "InnerChispa",
        "slug": "innerchispa",
        "kind": "organization",
        "status": "active",
        "linkedin_publish_as": "organization",
    },
    {
        "entity_id": "ent_pcdoctor",
        "name": "PC Doctor",
        "slug": "pcdoctor",
        "kind": "organization",
        "status": "active",
        "linkedin_publish_as": "organization",
    },
    {
        "entity_id": "ent_innerspark",
        "name": "InnerSpark",
        "slug": "innerspark",
        "kind": "organization",
        "status": "active",
        "linkedin_publish_as": "organization",
        "setup_status": "linkedin_page_pending_creation",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_urn() -> str:
    return (config_store.get("LINKEDIN_AUTHOR_URN") or LINKEDIN_AUTHOR_URN or "").strip()


def _token_ok() -> bool:
    return bool(config_store.get("LINKEDIN_ACCESS_TOKEN") or LINKEDIN_ACCESS_TOKEN)


def seed_standard_entities() -> dict[str, Any]:
    db = mongo_store.get_db()
    changed = 0
    now = _now_iso()
    for row in STANDARD_ENTITIES:
        res = db.entities.update_one(
            {"entity_id": row["entity_id"]},
            {
                "$setOnInsert": {**row, "created_at": now},
                "$set": {
                    "status": row["status"],
                    "kind": row["kind"],
                    "slug": row["slug"],
                    "linkedin_publish_as": row["linkedin_publish_as"],
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        if res.upserted_id or res.modified_count:
            changed += 1
    return {"ok": True, "changed": changed, "entities": [row["entity_id"] for row in STANDARD_ENTITIES]}


def _urn_short(urn: str) -> str:
    if not urn:
        return "—"
    tail = urn.rsplit(":", 1)[-1]
    return f"…{tail[-8:]}" if len(tail) > 8 else tail


def _entity_doc(entity_id: str) -> dict[str, Any] | None:
    if not entity_id:
        return None
    return mongo_store.get_db().entities.find_one({"entity_id": entity_id.strip()}, {"_id": 0})


def _effective_urn(entity_id: str, ent: dict[str, Any] | None, acct: dict[str, Any]) -> str:
    urn = (ent or {}).get("linkedin_author_urn", "").strip()
    if urn:
        return urn
    if acct.get("allow_env_fallback"):
        return _default_urn()
    return ""


def _account_status(urn: str, acct: dict[str, Any]) -> str:
    if not _token_ok():
        return "missing_token"
    if urn:
        return "connected"
    if acct.get("allow_env_fallback") and _default_urn():
        return "connected_fallback"
    return "missing_config"


def seed_linkedin_accounts() -> dict[str, Any]:
    db = mongo_store.get_db()
    seed_standard_entities()
    n = 0
    for row in DEFAULT_ACCOUNTS:
        ent = _entity_doc(row["entity_id"]) or {}
        urn = _effective_urn(row["entity_id"], ent, row)
        doc = {**row, "author_urn": urn, "status": _account_status(urn, row), "updated_at": _now_iso()}
        res = db[COL].update_one(
            {"entity_id": row["entity_id"], "platform": "linkedin"},
            {"$set": doc, "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True,
        )
        if res.upserted_id or res.modified_count:
            n += 1
    return {"ok": True, "seeded": n}


def sync_account_from_entity(entity_id: str) -> None:
    db = mongo_store.get_db()
    ent = _entity_doc(entity_id)
    acct = db[COL].find_one({"entity_id": entity_id, "platform": "linkedin"})
    if not ent or not acct:
        return
    urn = _effective_urn(entity_id, ent, acct)
    db[COL].update_one(
        {"entity_id": entity_id, "platform": "linkedin"},
        {"$set": {"author_urn": urn, "status": _account_status(urn, acct), "updated_at": _now_iso()}},
    )


def list_linkedin_accounts(*, refresh: bool = True) -> list[dict[str, Any]]:
    if refresh:
        seed_linkedin_accounts()
    db = mongo_store.get_db()
    rows = list(db[COL].find({"platform": "linkedin"}, {"_id": 0}).sort("label", 1))
    out = []
    for acct in rows:
        ent = _entity_doc(acct.get("entity_id", "")) or {}
        urn = _effective_urn(acct["entity_id"], ent, acct)
        status = _account_status(urn, acct)
        out.append(
            {
                **acct,
                "entity_name": ent.get("name", acct.get("label", "")),
                "author_urn": urn,
                "author_urn_display": _urn_short(urn),
                "status": status,
                "can_publish": status in ("connected", "connected_fallback"),
                "uses_fallback": status == "connected_fallback",
                "token_configured": _token_ok(),
                "destination_summary": _destination_summary(
                    {**acct, "status": status, "author_urn_display": _urn_short(urn)}, ent
                ),
            }
        )
    return out


def _destination_summary(acct: dict[str, Any], ent: dict[str, Any]) -> str:
    name = ent.get("name") or acct.get("label", "")
    st = acct.get("status", "")
    if st == "connected":
        return f"LinkedIn {acct.get('account_type', 'personal')}: {name} ({acct.get('author_urn_display', '')})"
    if st == "connected_fallback":
        return f"Perfil personal (fallback) — entidad «{name}» sin URN de página"
    if st == "missing_token":
        return "Token LinkedIn no configurado — Panel :2002 → Configuración"
    return f"Cuenta no configurada para «{name}» — falta urn:li:organization:…"


def _warnings(acct: dict[str, Any], ent: dict[str, Any]) -> list[str]:
    warns: list[str] = []
    if acct.get("uses_fallback"):
        warns.append("Publicará en perfil personal — esta entidad no tiene URN de página.")
    if acct.get("status") == "missing_config":
        warns.append("Bloqueado hasta configurar linkedin_author_urn de la página.")
    if not acct.get("token_configured"):
        warns.append("Falta LINKEDIN_ACCESS_TOKEN.")
    return warns


def publish_preview(entity_id: str | None) -> dict[str, Any]:
    eid = (entity_id or "").strip() or "ent_rafael_personal"
    accounts = {a["entity_id"]: a for a in list_linkedin_accounts()}
    acct = accounts.get(eid)
    ent = _entity_doc(eid) or {}
    if not acct:
        return {"ok": False, "entity_id": eid, "can_publish": False, "error": "sin cuenta LinkedIn"}
    return {
        "ok": True,
        "entity_id": eid,
        "entity_name": ent.get("name", acct.get("label", "")),
        "platform": "linkedin",
        "account_type": acct.get("account_type", "personal"),
        "label": acct.get("label", ""),
        "author_urn_display": acct.get("author_urn_display", ""),
        "status": acct.get("status", ""),
        "can_publish": acct.get("can_publish", False),
        "uses_fallback": acct.get("uses_fallback", False),
        "token_configured": acct.get("token_configured", False),
        "destination_summary": _destination_summary(acct, ent),
        "warnings": _warnings(acct, ent),
        "allow_fallback_option": acct.get("status") == "missing_config" and bool(_default_urn()),
    }


class PublishBlockedError(RuntimeError):
    def __init__(self, preview: dict[str, Any]):
        self.preview = preview
        super().__init__(preview.get("destination_summary") or "publicación bloqueada")


def resolve_for_publish(
    entity_id: str | None,
    *,
    allow_personal_fallback: bool = False,
) -> tuple[str, dict[str, Any]]:
    preview = publish_preview(entity_id)
    if not preview.get("ok"):
        raise PublishBlockedError(preview)
    status = preview.get("status", "")
    eid = preview.get("entity_id", "")
    if status == "connected":
        urn = next(a["author_urn"] for a in list_linkedin_accounts(refresh=False) if a["entity_id"] == eid)
        if not urn:
            raise PublishBlockedError(preview)
        return urn, {
            "entity_id": eid,
            "entity_name": preview.get("entity_name", ""),
            "publish_as": preview.get("account_type", "personal"),
            "source": "entity_account",
            "destination_summary": preview.get("destination_summary", ""),
            "author_urn_display": preview.get("author_urn_display", ""),
        }
    if status == "connected_fallback":
        urn = _default_urn()
        if not urn:
            raise PublishBlockedError(preview)
        return urn, {
            "entity_id": eid,
            "entity_name": preview.get("entity_name", ""),
            "publish_as": "person",
            "source": "env_fallback",
            "warning": preview["warnings"][0] if preview.get("warnings") else "",
            "destination_summary": preview.get("destination_summary", ""),
            "author_urn_display": _urn_short(urn),
        }
    if status == "missing_config" and allow_personal_fallback and _default_urn():
        urn = _default_urn()
        return urn, {
            "entity_id": eid,
            "entity_name": preview.get("entity_name", ""),
            "publish_as": "person",
            "source": "explicit_personal_fallback",
            "warning": f"Fallback personal confirmado — elegiste «{preview.get('entity_name')}».",
            "destination_summary": f"Perfil personal ({_urn_short(urn)})",
            "author_urn_display": _urn_short(urn),
        }
    raise PublishBlockedError(preview)


def patch_entity_linkedin(
    entity_id: str,
    *,
    linkedin_author_urn: str | None = None,
    linkedin_publish_as: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    db = mongo_store.get_db()
    if not db.entities.find_one({"entity_id": entity_id}):
        return {"ok": False, "error": "entidad no encontrada"}
    ent_patch: dict[str, Any] = {"updated_at": _now_iso()}
    if linkedin_author_urn is not None:
        ent_patch["linkedin_author_urn"] = linkedin_author_urn.strip()
    if linkedin_publish_as is not None:
        ent_patch["linkedin_publish_as"] = linkedin_publish_as.strip()
    db.entities.update_one({"entity_id": entity_id}, {"$set": ent_patch})
    acct_patch: dict[str, Any] = {"updated_at": _now_iso()}
    if label:
        acct_patch["label"] = label.strip()
    if linkedin_publish_as:
        acct_patch["account_type"] = linkedin_publish_as
    db[COL].update_one({"entity_id": entity_id, "platform": "linkedin"}, {"$set": acct_patch})
    sync_account_from_entity(entity_id)
    return {"ok": True, "preview": publish_preview(entity_id)}
