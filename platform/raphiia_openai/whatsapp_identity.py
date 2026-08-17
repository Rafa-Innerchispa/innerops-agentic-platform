"""Canonical WhatsApp identity registry, independent from CRM and contact books."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.notifications import settings

COLLECTION = "ralfia_whatsapp_identities"
AUDIT_COLLECTION = "ralfia_whatsapp_identity_audit"
OWNER_PRINCIPAL_ID = "principal_rafael_owner"
OPERATIONS_PRINCIPAL_ID = "principal_pcdoctor_operations"
OWNER_SCOPES = (
    "whatsapp:read",
    "whatsapp:memory",
    "whatsapp:maintenance:request",
    "whatsapp:maintenance:confirm",
    "whatsapp:agent_jobs",
)
OPS_SCOPES = (
    "whatsapp:read",
    "whatsapp:maintenance:request",
)
_COLLISION_COLLECTIONS = (
    "clients",
    "parties",
    "operational_parties",
    "whatsapp_contacts",
    "google_contacts",
    "ralfia_party_records",
)
_PHONE_FIELDS = ("phone", "phones", "telefono", "telefonos", "mobile", "whatsapp", "ownerJid")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_e164(value: str) -> str:
    raw = str(value or "").split("@", 1)[0]
    # WhatsApp multi-device JIDs may be `number:device@s.whatsapp.net`.
    raw = raw.split(":", 1)[0]
    digits = "".join(char for char in raw if char.isdigit())
    while digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "593" + digits[1:]
    if len(digits) == 9 and digits.startswith("9"):
        digits = "593" + digits
    if len(digits) < 10 or len(digits) > 15:
        return ""
    return f"+{digits}"


def sender_hash(value: str) -> str:
    normalized = normalize_e164(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else "unknown"


def ensure_indexes() -> None:
    db = mongo_store.get_db()
    db[COLLECTION].create_index([("channel", 1), ("e164", 1)], unique=True)
    db[COLLECTION].create_index([("principal_id", 1), ("status", 1)])


def resolve_identity(sender: str, *, chat_id: str | None = None, is_group: bool = False) -> dict[str, Any]:
    e164 = normalize_e164(sender)
    base = {
        "authenticated": False,
        "principal_id": None,
        "preferred_name": None,
        "roles": [],
        "scopes": [],
        "channel": "whatsapp",
        "sender_hash": sender_hash(sender),
        "chat_binding": hashlib.sha256(str(chat_id or "").encode()).hexdigest()[:16] if chat_id else None,
        "is_group": bool(is_group),
    }
    if not e164:
        return {**base, "reason": "invalid_sender"}
    doc = mongo_store.get_db()[COLLECTION].find_one(
        {"channel": "whatsapp", "e164": e164, "status": "verified"},
        {"_id": 0},
    )
    if not doc:
        # Auto-owner: NOTIFY_WHATSAPP_TO siempre es Rafael (evita silencio si falta bootstrap)
        notify = normalize_e164(settings.NOTIFY_WHATSAPP_TO or os.getenv("RALFIA_ALERTS_TO", ""))
        if notify and e164 == notify:
            try:
                bootstrap_owner_registry([notify.lstrip("+")], include_evolution=False, apply=True)
            except Exception:
                pass
            doc = mongo_store.get_db()[COLLECTION].find_one(
                {"channel": "whatsapp", "e164": e164, "status": "verified"},
                {"_id": 0},
            )
    if not doc:
        return {**base, "reason": "identity_not_registered"}
    return {
        **base,
        "authenticated": True,
        "principal_id": doc.get("principal_id"),
        "preferred_name": doc.get("preferred_name"),
        "roles": list(doc.get("roles") or []),
        "scopes": list(doc.get("scopes") or []),
        "channel_account": doc.get("channel_account"),
        "notify_enabled": bool(doc.get("notify_enabled")),
        "reason": "verified_registry",
    }


def has_scope(identity: dict[str, Any], scope: str) -> bool:
    return bool(identity.get("authenticated") and scope in set(identity.get("scopes") or []))


def is_owner(identity: dict[str, Any]) -> bool:
    return bool(identity.get("authenticated") and "owner" in set(identity.get("roles") or []))


def _evolution_instances(node: str) -> list[dict[str, Any]]:
    base = settings.EVOLUTION_AMD_BASE_URL if node == "amd" else settings.EVOLUTION_BASE_URL
    if not base or not settings.EVOLUTION_API_KEY:
        return []
    try:
        response = httpx.get(
            f"{base}/instance/fetchInstances",
            headers={"apikey": settings.EVOLUTION_API_KEY},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def discover_evolution_owner_lines() -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    expected = {
        "primary": settings.EVOLUTION_INSTANCE,
        "amd": settings.EVOLUTION_AMD_INSTANCE,
    }
    for node in ("primary", "amd"):
        for item in _evolution_instances(node):
            name = str(item.get("name") or (item.get("instance") or {}).get("instanceName") or "")
            if expected[node] and name and name != expected[node]:
                continue
            nested = item.get("instance") or {}
            candidates = [item.get("ownerJid"), item.get("number")]
            if isinstance(nested, dict):
                candidates.append(nested.get("owner"))
            e164 = next(
                (normalized for raw in candidates if (normalized := normalize_e164(str(raw or "")))),
                "",
            )
            if e164:
                discovered.append({"e164": e164, "node": node, "instance": name or expected[node]})
    unique: dict[str, dict[str, str]] = {item["e164"]: item for item in discovered}
    return list(unique.values())


def collision_report(lines: list[str]) -> dict[str, Any]:
    db = mongo_store.get_db()
    available = set(db.list_collection_names())
    report: dict[str, dict[str, int]] = {}
    for line in lines:
        e164 = normalize_e164(line)
        digits = e164.lstrip("+")
        if not digits:
            continue
        counts: dict[str, int] = {}
        for collection in _COLLISION_COLLECTIONS:
            if collection not in available:
                continue
            query = {"$or": [{field: {"$regex": digits[-10:]}} for field in _PHONE_FIELDS]}
            try:
                count = db[collection].count_documents(query, limit=50)
            except Exception:
                count = 0
            if count:
                counts[collection] = int(count)
        report[sender_hash(e164)] = counts
    return {"ok": True, "line_count": len(report), "collisions_by_sender_hash": report}


def bootstrap_owner_registry(
    known_owner_lines: list[str],
    *,
    include_evolution: bool = True,
    apply: bool = False,
) -> dict[str, Any]:
    known = [line for item in known_owner_lines if (line := normalize_e164(item))]
    if not known:
        return {"ok": False, "error": "owner_primary_line_required"}
    sources: dict[str, dict[str, Any]] = {
        known[0]: {
            "source": "owner_confirmation",
            "channel_account": "owner-primary",
            "principal_id": OWNER_PRINCIPAL_ID,
            "preferred_name": "Rafael",
            "roles": ["owner"],
            "scopes": list(OWNER_SCOPES),
            "notify_enabled": True,
        }
    }
    for index, line in enumerate(known[1:]):
        sources.setdefault(
            line,
            {
                "source": "operational_line_confirmation",
                "channel_account": f"pcdoctor-operational-{index + 1}",
                "principal_id": OPERATIONS_PRINCIPAL_ID,
                "preferred_name": "PC Doctor",
                "roles": ["operational_line"],
                "scopes": list(OPS_SCOPES),
                "notify_enabled": False,
            },
        )
    discovered = discover_evolution_owner_lines() if include_evolution else []
    for item in discovered:
        sources.setdefault(
            item["e164"],
            {
                "source": "evolution_instance_metadata",
                "channel_account": f"evolution-{item['node']}",
                "principal_id": f"principal_evolution_{item['node']}",
                "preferred_name": f"Evolution {item['node']}",
                "roles": ["service_principal"],
                "scopes": list(OPS_SCOPES),
                "notify_enabled": False,
            },
        )
    lines = sorted(sources)
    collisions = collision_report(lines)
    preview = [
        {
            "sender_hash": sender_hash(line),
            "principal_id": sources[line]["principal_id"],
            "preferred_name": sources[line]["preferred_name"],
            "roles": sources[line]["roles"],
            "scopes": sources[line]["scopes"],
            "source": sources[line]["source"],
            "channel_account": sources[line]["channel_account"],
            "notify_enabled": sources[line]["notify_enabled"],
        }
        for line in lines
    ]
    if not apply:
        return {
            "ok": True,
            "dry_run": True,
            "candidate_count": len(preview),
            "preview": preview,
            "collisions": collisions,
        }
    ensure_indexes()
    db = mongo_store.get_db()
    now = _now()
    # Revoke any historical owner alias before applying the explicit role map.
    db[COLLECTION].update_many(
        {"principal_id": OWNER_PRINCIPAL_ID, "e164": {"$ne": known[0]}},
        {
            "$set": {
                "status": "revoked",
                "roles": [],
                "scopes": [],
                "notify_enabled": False,
                "revocation_reason": "superseded_by_explicit_primary_owner_policy",
                "updated_at": now,
            }
        },
    )
    for line in lines:
        source = sources[line]
        db[COLLECTION].update_one(
            {"channel": "whatsapp", "e164": line},
            {
                "$set": {
                    "principal_id": source["principal_id"],
                    "preferred_name": source["preferred_name"],
                    "roles": source["roles"],
                    "scopes": source["scopes"],
                    "status": "verified",
                    "channel_account": source["channel_account"],
                    "verification_source": source["source"],
                    "notify_enabled": source["notify_enabled"],
                    "revocation_reason": None,
                    "updated_at": now,
                },
                "$setOnInsert": {"channel": "whatsapp", "e164": line, "created_at": now},
            },
            upsert=True,
        )
    db[AUDIT_COLLECTION].insert_one(
        {
            "action": "whatsapp_identity_role_migration",
            "principal_id": OWNER_PRINCIPAL_ID,
            "line_hashes": [sender_hash(line) for line in lines],
            "role_map": {
                sender_hash(line): sources[line]["roles"] for line in lines
            },
            "count": len(lines),
            "at": now,
            "source": "explicit_owner_authorization",
        }
    )
    return {
        "ok": True,
        "dry_run": False,
        "registered_count": len(lines),
        "line_hashes": [sender_hash(line) for line in lines],
        "collisions": collisions,
    }


def notification_destinations() -> list[str]:
    rows = mongo_store.get_db()[COLLECTION].find(
        {
            "principal_id": OWNER_PRINCIPAL_ID,
            "status": "verified",
            "notify_enabled": True,
        },
        {"_id": 0, "e164": 1},
    )
    return [str(row.get("e164") or "").lstrip("+") for row in rows if row.get("e164")]


def configured_owner_lines_from_env() -> list[str]:
    raw = os.getenv("WHATSAPP_OWNER_LINES", "")
    return [item.strip() for item in raw.split(",") if item.strip()]
