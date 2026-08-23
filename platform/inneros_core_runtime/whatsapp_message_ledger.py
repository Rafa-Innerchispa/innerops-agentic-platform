"""Ledger mínimo y clasificador determinista para evitar eco y bucles WhatsApp."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from raphiia_openai import mongo_store

LEDGER_COLLECTION = "whatsapp_message_ledger"
FINGERPRINT_COLLECTION = "whatsapp_automation_fingerprints"
LOOP_WINDOW_SECONDS = 900

# Huella de la autorespuesta empresarial observada en la prueba física de .5.
# Solo se conserva el SHA-256 normalizado, nunca el contenido personal.
_BUILTIN_AUTOMATION_FINGERPRINTS = {
    "027634a4b23233524220412bd0e157bb32a21520df5a9b6a4e8c7c1760e0e255",
}
_INDEXES_READY = False


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _normalize_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def identity_hash(value: str | None) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").casefold())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24] if normalized else ""


def _ensure_indexes() -> None:
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        db = mongo_store.get_db()
        db[LEDGER_COLLECTION].create_index("ledger_id", unique=True)
        db[LEDGER_COLLECTION].create_index([("direction", 1), ("message_id", 1)])
        db[LEDGER_COLLECTION].create_index([("direction", 1), ("text_fingerprint", 1), ("created_at", -1)])
        db[FINGERPRINT_COLLECTION].create_index("fingerprint", unique=True)
        _INDEXES_READY = True
    except Exception:
        # El canal debe seguir disponible aunque Mongo no permita crear un índice.
        return


def _response_message_id(value: Any) -> str:
    if isinstance(value, dict):
        key = value.get("key")
        if isinstance(key, dict) and key.get("id"):
            return str(key["id"])[:160]
        for name in ("messageId", "message_id", "wamid"):
            if value.get(name):
                return str(value[name])[:160]
        for nested in value.values():
            found = _response_message_id(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _response_message_id(nested)
            if found:
                return found
    return ""


def automation_fingerprints() -> set[str]:
    configured = {
        item.strip().lower()
        for item in os.getenv("WHATSAPP_AUTOMATION_FINGERPRINTS", "").split(",")
        if re.fullmatch(r"[a-fA-F0-9]{64}", item.strip())
    }
    stored: set[str] = set()
    try:
        stored = {
            str(item.get("fingerprint") or "").lower()
            for item in mongo_store.get_db()[FINGERPRINT_COLLECTION].find(
                {"active": {"$ne": False}}, {"_id": 0, "fingerprint": 1}
            )
            if re.fullmatch(r"[a-fA-F0-9]{64}", str(item.get("fingerprint") or ""))
        }
    except Exception:
        pass
    return set(_BUILTIN_AUTOMATION_FINGERPRINTS) | configured | stored


def record_outbound(
    *,
    text: str,
    target: str,
    node: str,
    instance: str,
    response: Any,
    ok: bool,
) -> dict[str, Any]:
    _ensure_indexes()
    fingerprint = text_fingerprint(text)
    message_id = _response_message_id(response)
    target_hash = identity_hash(target)
    minute_bucket = int(_now_dt().timestamp()) // 60
    stable = message_id or hashlib.sha256(
        f"{node}|{instance}|{target_hash}|{fingerprint}|{minute_bucket}".encode()
    ).hexdigest()[:32]
    ledger_id = f"out:{stable}"
    doc = {
        "ledger_id": ledger_id,
        "direction": "outbound",
        "message_id": message_id or None,
        "text_fingerprint": fingerprint,
        "text_length": len(text or ""),
        "target_hash": target_hash,
        "node": node,
        "instance": instance,
        "actor_type": "service_account",
        "status": "sent" if ok else "failed",
        "created_at": _now(),
    }
    try:
        mongo_store.get_db()[LEDGER_COLLECTION].update_one(
            {"ledger_id": ledger_id}, {"$setOnInsert": doc}, upsert=True
        )
    except Exception:
        return {"ok": False, "ledger_id": ledger_id}
    return {"ok": True, "ledger_id": ledger_id, "message_id": message_id or None}


def classify_inbound(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import whatsapp_evolution_parse as evo

    data = evo.evolution_data(payload)
    key = data.get("key") or {} if isinstance(data, dict) else {}
    message_id = str(key.get("id") or payload.get("event_id") or "")[:160]
    text = evo.extract_message(payload)
    fingerprint = text_fingerprint(text)
    author = evo.extract_sender(payload)
    account = str(payload.get("sender") or payload.get("destination") or payload.get("instance") or "")
    result = {
        "actor_type": "human",
        "should_route": True,
        "reason": "human_inbound",
        "message_id": message_id or None,
        "text_fingerprint": fingerprint,
        "author_hash": identity_hash(author),
        "account_hash": identity_hash(account),
    }
    event = evo.evolution_event(payload)
    if event in {"send.message", "connection.update", "qrcode.updated", "presence.update"}:
        return {**result, "actor_type": "automation", "should_route": False, "reason": f"ignored:{event}"}
    if bool(key.get("fromMe")):
        return {**result, "actor_type": "service_account", "should_route": False, "reason": "from_me"}
    if fingerprint in automation_fingerprints():
        return {**result, "actor_type": "automation", "should_route": False, "reason": "automation_template"}
    try:
        db = mongo_store.get_db()
        if message_id and db[LEDGER_COLLECTION].find_one(
            {"direction": "outbound", "message_id": message_id, "status": "sent"}, {"_id": 1}
        ):
            return {**result, "actor_type": "service_account", "should_route": False, "reason": "outbound_message_id"}
        cutoff = (_now_dt() - timedelta(seconds=LOOP_WINDOW_SECONDS)).isoformat()
        if db[LEDGER_COLLECTION].find_one(
            {
                "direction": "outbound",
                "status": "sent",
                "text_fingerprint": fingerprint,
                "target_hash": identity_hash(author),
                "created_at": {"$gte": cutoff},
            },
            {"_id": 1},
        ):
            return {**result, "actor_type": "automation", "should_route": False, "reason": "outbound_fingerprint_echo"}
    except Exception:
        pass
    return result


def record_inbound(classification: dict[str, Any], *, node: str, instance: str) -> dict[str, Any]:
    _ensure_indexes()
    message_id = str(classification.get("message_id") or "")
    stable = message_id or hashlib.sha256(
        f"{classification.get('account_hash')}|{classification.get('author_hash')}|{classification.get('text_fingerprint')}".encode()
    ).hexdigest()[:32]
    ledger_id = f"in:{stable}"
    doc = {
        "ledger_id": ledger_id,
        "direction": "inbound",
        "message_id": message_id or None,
        "text_fingerprint": classification.get("text_fingerprint"),
        "author_hash": classification.get("author_hash"),
        "account_hash": classification.get("account_hash"),
        "actor_type": classification.get("actor_type"),
        "routing_decision": "route" if classification.get("should_route") else "blocked",
        "reason": classification.get("reason"),
        "node": node,
        "instance": instance,
        "created_at": _now(),
    }
    try:
        result = mongo_store.get_db()[LEDGER_COLLECTION].update_one(
            {"ledger_id": ledger_id}, {"$setOnInsert": doc}, upsert=True
        )
        return {"ok": True, "ledger_id": ledger_id, "idempotent": not bool(result.upserted_id)}
    except Exception:
        return {"ok": False, "ledger_id": ledger_id}
