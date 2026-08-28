"""Daily Life Memory: versioned, evidence-backed memories over existing MCP storage."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

MEMORIES = "ralfia_memory_items"
VERSIONS = "ralfia_memory_versions"
CONVERSATIONS = "daily_life_conversations"
MESSAGES = "raphiia_openai_messages"
CURRENT_STATE = "daily_life_current_state"
ENTITIES = "daily_life_entities"
PENDING = "daily_life_pending_items"
TIMELINE = "daily_life_timeline"
AUDIT = "daily_life_memory_audit"

PRIVACY_SCOPES = frozenset(
    {
        "PRIVATE_PERSONAL",
        "PRIVATE_HEALTH",
        "PRIVATE_RELATIONSHIPS",
        "PRIVATE_FAMILY",
        "PRIVATE_FINANCIAL",
        "INTERNAL_WORK",
        "PROJECT",
        "PUBLIC",
    }
)
PRIVATE_SCOPES = frozenset(scope for scope in PRIVACY_SCOPES if scope.startswith("PRIVATE_"))
SAFE_DEFAULT_READ = frozenset({"INTERNAL_WORK", "PROJECT", "PUBLIC"})
MEMORY_KINDS = frozenset(
    {
        "fact",
        "opinion",
        "hypothesis",
        "interpretation",
        "decision",
        "emotion",
        "intention",
        "context_rule",
        "pattern",
        "summary",
    }
)
ENTITY_TYPES = frozenset({"PERSON", "PROJECT", "PLACE"})

_DEFAULT_CONFIDENCE = {
    "fact": 0.75,
    "opinion": 0.9,
    "hypothesis": 0.35,
    "interpretation": 0.4,
    "decision": 0.9,
    "emotion": 0.9,
    "intention": 0.85,
    "context_rule": 1.0,
    "pattern": 0.7,
    "summary": 0.55,
}

_EPISTEMIC_STATUS = {
    "fact": "asserted",
    "opinion": "self_reported",
    "hypothesis": "uncertain",
    "interpretation": "inferred",
    "decision": "committed",
    "emotion": "self_reported",
    "intention": "intended",
    "context_rule": "validated_context",
    "pattern": "longitudinal_observation",
    "summary": "synthesized",
}

_SENSITIVE_HINTS = {
    "PRIVATE_HEALTH": ("salud", "médic", "diagnóst", "medicina", "terapia", "hospital"),
    "PRIVATE_RELATIONSHIPS": ("pareja", "relación", "novi", "espos"),
    "PRIVATE_FAMILY": ("familia", "madre", "padre", "hijo", "herman"),
    "PRIVATE_FINANCIAL": ("deuda", "saldo", "sueldo", "banco", "financ", "pago personal"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9áéíóúñ]+", (value or "").lower()))


def _fingerprint(*, owner_id: str, privacy_scope: str, kind: str, body: str, project: str | None) -> str:
    return _hash("|".join([owner_id.lower(), privacy_scope, kind, project or "", _normalized_text(body)]))


def _privacy(value: str | None) -> str:
    aliases = {"PRIVATE": "PRIVATE_PERSONAL", "INTERNAL": "INTERNAL_WORK", "TEAM": "PROJECT"}
    scope = aliases.get((value or "").strip().upper(), (value or "").strip().upper())
    if scope not in PRIVACY_SCOPES:
        raise ValueError(f"invalid privacy_scope: {value}; allowed={sorted(PRIVACY_SCOPES)}")
    return scope


def _privacy_guard(body: str, scope: str) -> None:
    if scope not in {"PUBLIC", "PROJECT"}:
        return
    text = (body or "").lower()
    detected = [private for private, hints in _SENSITIVE_HINTS.items() if any(hint in text for hint in hints)]
    if detected:
        raise ValueError(f"privacy_mismatch: content suggests {detected}; refusing {scope}")


def _allowed(actor: str, requested: list[str] | None = None) -> set[str]:
    if (actor or "").strip().upper() == "RAFAEL":
        return set(PRIVACY_SCOPES if requested is None else (_privacy(value) for value in requested))
    requested_set = set(SAFE_DEFAULT_READ if requested is None else (_privacy(value) for value in requested))
    return requested_set & set(SAFE_DEFAULT_READ)


def _clamp_confidence(value: Any, default: float) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return default


def _epistemic_values(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    owner_validated = bool(payload.get("owner_validated") or payload.get("owner_confirmed"))
    confidence = _clamp_confidence(payload.get("confidence"), _DEFAULT_CONFIDENCE[kind])
    basis = str(payload.get("confidence_basis") or "").strip() or (
        "owner_confirmation" if owner_validated else "linguistic_marker"
    )
    if owner_validated:
        confidence = 1.0
    label = "owner_confirmed" if owner_validated else ("high" if confidence >= 0.75 else "medium" if confidence >= 0.5 else "low")
    return {
        "confidence": confidence,
        "confidence_label": label,
        "confidence_basis": basis,
        "owner_validated": owner_validated,
        "epistemic_status": str(payload.get("epistemic_status") or _EPISTEMIC_STATUS[kind]),
    }


def _pattern_is_supported(payload: dict[str, Any]) -> bool:
    conversation_ids = {
        str(value).strip()
        for value in [payload.get("conversation_id"), *(payload.get("source_conversation_ids") or [])]
        if str(value or "").strip()
    }
    return bool(payload.get("owner_validated") or payload.get("owner_confirmed") or len(conversation_ids) >= 2)


def ensure_indexes() -> dict[str, Any]:
    db = mongo_store.get_db()
    db[CONVERSATIONS].create_index("conversation_id", unique=True)
    db[MESSAGES].create_index(
        [("conversation_id", 1), ("message_id", 1)],
        name="daily_conversation_message_unique",
        unique=True,
        partialFilterExpression={"message_id": {"$type": "string"}},
    )
    db[MEMORIES].create_index("memory_id", unique=True, sparse=True)
    db[MEMORIES].create_index("fingerprint", unique=True, sparse=True)
    db[MEMORIES].create_index([("owner_id", 1), ("privacy_scope", 1), ("status", 1)])
    db[MEMORIES].create_index([("owner_id", 1), ("kind", 1), ("status", 1), ("updated_at", -1)])
    db[MEMORIES].create_index("source_conversation_ids")
    db[VERSIONS].create_index([("memory_id", 1), ("version", -1)])
    db[CURRENT_STATE].create_index([("owner_id", 1), ("state_key", 1)], unique=True)
    db[ENTITIES].create_index([("owner_id", 1), ("entity_type", 1), ("normalized_name", 1)], unique=True)
    db[PENDING].create_index("pending_id", unique=True)
    db[TIMELINE].create_index([("owner_id", 1), ("occurred_at", -1)])
    return {"ok": True, "collections": [CONVERSATIONS, MESSAGES, MEMORIES, VERSIONS, CURRENT_STATE, ENTITIES, PENDING, TIMELINE, AUDIT]}


def _audit(action: str, *, actor: str, subject_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    mongo_store.get_db()[AUDIT].insert_one(
        {"audit_id": _id("audit"), "action": action, "actor": actor, "subject_id": subject_id, "metadata": metadata or {}, "at": _now()}
    )


def save_conversation_batch(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_indexes()
    db = mongo_store.get_db()
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not conversation_id:
        return {"ok": False, "error": "conversation_id_required"}
    owner_id = str(payload.get("owner_id") or "RAFAEL").strip().upper()
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    scope = _privacy(str(payload.get("privacy_scope") or "PRIVATE_PERSONAL"))
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return {"ok": False, "error": "messages_required"}
    now = _now()
    inserted = 0
    ids: list[str] = []
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict):
            return {"ok": False, "error": "invalid_message", "index": index}
        role = str(raw.get("role") or "").strip().lower()
        content = str(raw.get("content") or "").strip()
        if role not in {"user", "assistant", "system", "tool"} or not content:
            return {"ok": False, "error": "invalid_message_fields", "index": index}
        _privacy_guard(content, scope)
        message_id = str(raw.get("message_id") or "").strip() or f"dlm_{_hash(f'{conversation_id}|{index}|{role}|{content}')[:20]}"
        doc = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "privacy_scope": scope,
            "owner_id": owner_id,
            "source": str(raw.get("source") or payload.get("source") or "chatgpt_mcp"),
            "source_timestamp": raw.get("timestamp"),
            "metadata": raw.get("metadata") or {},
            "created_at": now,
        }
        result = db[MESSAGES].update_one(
            {"conversation_id": conversation_id, "message_id": message_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        inserted += int(result.upserted_id is not None)
        ids.append(message_id)
    db[CONVERSATIONS].update_one(
        {"conversation_id": conversation_id},
        {
            "$set": {
                "owner_id": owner_id,
                "privacy_scope": scope,
                "project": payload.get("project"),
                "person_ids": payload.get("person_ids") or [],
                "place_ids": payload.get("place_ids") or [],
                "participants": [
                    participant
                    for participant in (payload.get("participants") or [])
                    if isinstance(participant, dict)
                ],
                "metadata": payload.get("metadata") or {},
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "status": "open"},
        },
        upsert=True,
    )
    _audit("conversation_batch_saved", actor=actor, subject_id=conversation_id, metadata={"inserted": inserted, "received": len(messages)})
    return {"ok": True, "conversation_id": conversation_id, "received": len(messages), "inserted": inserted, "message_ids": ids, "privacy_scope": scope}


def _sentences(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(message.get("content") or "")):
            if sentence.strip():
                output.append((sentence.strip(), str(message.get("message_id") or "")))
    return output


def _deterministic_analysis(messages: list[dict[str, Any]]) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    opinions: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    interpretations: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    intentions: list[dict[str, Any]] = []
    context_rules: list[dict[str, Any]] = []
    pattern_candidates: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    emotions: list[dict[str, Any]] = []
    for text, message_id in _sentences(messages):
        lowered = text.lower()
        base = {"text": text, "source_message_ids": [message_id]}
        is_context_rule = any(
            marker in lowered
            for marker in (
                "entre nosotros",
                "cuando hablamos",
                "es humor interno",
                "es una broma",
                "no significa",
                "no es agresión",
                "no es agresion",
                "corrijo",
                "en realidad",
            )
        )
        is_decision = any(marker in lowered for marker in ("decidí", "decidi", "decidimos", "acordamos", "se hará", "se hara"))
        is_intention = any(marker in lowered for marker in ("quiero ", "planeo ", "intento ", "mi intención", "mi intencion", "me gustaría", "me gustaria", "voy a "))
        is_pattern_candidate = any(
            marker in lowered
            for marker in ("he notado un patrón", "he notado un patron", "siempre me pasa", "suele pasarme", "repetidamente")
        )
        emotion = next(
            (
                name
                for name in ("feliz", "triste", "ansioso", "ansiosa", "preocupado", "preocupada", "enojado", "enojada", "motivado", "motivada", "cansado", "cansada")
                if name in lowered
            ),
            None,
        )
        if is_context_rule:
            context_rules.append(
                {
                    **base,
                    "confidence": 1.0,
                    "confidence_basis": "explicit_user_correction",
                    "owner_validated": True,
                    "metadata": {"rule_type": "relational_language_or_correction"},
                }
            )
        elif any(marker in lowered for marker in ("quizá", "quizas", "tal vez", "podría", "podria", "posiblemente")):
            hypotheses.append({**base, "confidence": 0.35, "confidence_basis": "uncertainty_marker"})
        elif any(marker in lowered for marker in ("interpreto", "parece que", "significa que", "entiendo que")):
            interpretations.append({**base, "confidence": 0.4, "confidence_basis": "interpretation_marker"})
        elif any(marker in lowered for marker in ("creo", "pienso", "opino", "prefiero", "me gusta")):
            opinions.append({**base, "confidence": 0.9, "confidence_basis": "explicit_opinion"})
        elif is_decision:
            decisions.append({**base, "confidence": 0.9, "confidence_basis": "explicit_decision"})
        elif is_intention:
            intentions.append({**base, "confidence": 0.85, "confidence_basis": "explicit_intention"})
        elif is_pattern_candidate:
            pattern_candidates.append(
                {
                    **base,
                    "confidence": 0.35,
                    "confidence_basis": "single_conversation_pattern_candidate",
                    "metadata": {"pattern_candidate": True, "requires_review": True, "not_a_diagnosis": True},
                }
            )
        elif emotion or any(marker in lowered for marker in ("me siento", "siento que", "me preocupa", "me alegra")):
            emotions.append(
                {
                    **base,
                    "confidence": 0.9,
                    "confidence_basis": "first_person_experience",
                    "metadata": {"emotion_label": emotion, "not_a_diagnosis": True},
                }
            )
        elif any(marker in lowered for marker in ("hoy ", "ayer ", "ocurrió", "ocurrio", "fui ", "hice ", "recibí", "recibi", "terminé", "termine")):
            facts.append({**base, "confidence": 0.75, "confidence_basis": "concrete_event_marker"})
        else:
            interpretations.append(
                {
                    **base,
                    "confidence": 0.3,
                    "confidence_basis": "ambiguous_unmarked_statement",
                    "metadata": {"requires_review": True},
                }
            )
        if is_decision and not any(item.get("text") == text for item in decisions):
            decisions.append({**base, "confidence": 0.9, "confidence_basis": "explicit_decision"})
        if is_intention and not any(item.get("text") == text for item in intentions):
            intentions.append({**base, "confidence": 0.85, "confidence_basis": "explicit_intention"})
        if any(marker in lowered for marker in ("pendiente", "falta ", "debo ", "tenemos que", "recordar ", "por resolver")):
            pending.append({**base, "confidence": 0.85, "confidence_basis": "explicit_pending_marker"})
        if emotion and not any(item.get("text") == text for item in emotions):
            emotions.append({**base, "confidence": 0.9, "confidence_basis": "emotion_word", "metadata": {"emotion_label": emotion, "not_a_diagnosis": True}})
    summary = " ".join(str(message.get("content") or "") for message in messages[-6:])[:2000]
    return {
        "summary": summary,
        "facts": facts,
        "opinions": opinions,
        "hypotheses": hypotheses,
        "interpretations": interpretations,
        "decisions": decisions,
        "intentions": intentions,
        "context_rules": context_rules,
        "pattern_candidates": pattern_candidates,
        "pending": pending,
        "emotions": emotions,
        "entities": [],
    }


def _analysis_items(analysis: dict[str, Any], key: str, fallback_ids: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in analysis.get(key) or []:
        if isinstance(raw, str):
            output.append({"text": raw.strip(), "source_message_ids": fallback_ids})
        elif isinstance(raw, dict) and str(raw.get("text") or "").strip():
            output.append({**raw, "text": str(raw["text"]).strip(), "source_message_ids": raw.get("source_message_ids") or fallback_ids})
    return output


def _similarity(left: str, right: str) -> float:
    a = set(_normalized_text(left).split())
    b = set(_normalized_text(right).split())
    return len(a & b) / max(1, len(a | b))


def save_memory(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_indexes()
    db = mongo_store.get_db()
    body = str(payload.get("body") or payload.get("content") or "").strip()
    if not body:
        return {"ok": False, "error": "memory_body_required"}
    kind = str(payload.get("kind") or payload.get("type") or "fact").strip().lower()
    if kind not in MEMORY_KINDS:
        return {"ok": False, "error": "invalid_memory_kind", "allowed": sorted(MEMORY_KINDS)}
    if kind == "pattern" and not _pattern_is_supported(payload):
        return {
            "ok": False,
            "error": "pattern_requires_longitudinal_evidence",
            "required": "two_source_conversations_or_owner_validation",
        }
    scope = _privacy(str(payload.get("privacy_scope") or payload.get("visibility") or "PRIVATE_PERSONAL"))
    _privacy_guard(body, scope)
    owner_id = str(payload.get("owner_id") or "RAFAEL").strip().upper()
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    project = str(payload.get("project") or "").strip() or None
    fingerprint = _fingerprint(owner_id=owner_id, privacy_scope=scope, kind=kind, body=body, project=project)
    existing = db[MEMORIES].find_one({"fingerprint": fingerprint, "status": "active"})
    evidence = sorted(set(str(value) for value in (payload.get("source_message_ids") or []) if value))
    source_conversation_ids = sorted(
        {
            str(value).strip()
            for value in [payload.get("conversation_id"), *(payload.get("source_conversation_ids") or [])]
            if str(value or "").strip()
        }
    )
    epistemic = _epistemic_values(kind, payload)
    now = _now()
    if existing:
        epistemic_patch: dict[str, Any] = {}
        if epistemic["owner_validated"] or epistemic["confidence"] > float(existing.get("confidence") or 0):
            epistemic_patch = epistemic
        db[MEMORIES].update_one(
            {"_id": existing["_id"]},
            {
                "$addToSet": {
                    "source_message_ids": {"$each": evidence},
                    "source_conversation_ids": {"$each": source_conversation_ids},
                },
                "$set": {"updated_at": now, "last_seen_at": now, **epistemic_patch},
            },
        )
        return {"ok": True, "created": False, "duplicate": True, "memory_id": existing.get("memory_id"), "version": existing.get("version", 1)}

    candidates = list(db[MEMORIES].find({"owner_id": owner_id, "privacy_scope": scope, "kind": kind, "project": project, "status": "active"}).limit(100))
    similar = max(candidates, key=lambda item: _similarity(body, str(item.get("body") or "")), default=None)
    if similar and _similarity(body, str(similar.get("body") or "")) >= float(payload.get("duplicate_threshold") or 0.82):
        return update_memory(
            {
                "memory_id": similar["memory_id"],
                "body": body,
                "title": payload.get("title"),
                "source_message_ids": evidence,
                "source_conversation_ids": source_conversation_ids,
                "actor": actor,
                "reason": "similar_memory_update",
                **epistemic,
            }
        )

    memory_id = _id("mem")
    doc = {
        "memory_id": memory_id,
        "owner_id": owner_id,
        "kind": kind,
        "type": kind,
        "title": str(payload.get("title") or body[:120]).strip(),
        "body": body,
        "privacy_scope": scope,
        "visibility": scope,
        "project": project,
        "entities": payload.get("entities") or [],
        "tags": payload.get("tags") or [],
        "source_conversation_id": payload.get("conversation_id"),
        "source_conversation_ids": source_conversation_ids,
        "source_message_ids": evidence,
        "evidence_count": len(evidence),
        "fingerprint": fingerprint,
        "version": 1,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "last_seen_at": now,
        "metadata": payload.get("metadata") or {},
        **epistemic,
    }
    db[MEMORIES].insert_one(doc)
    _audit("memory_created", actor=actor, subject_id=memory_id, metadata={"kind": kind, "privacy_scope": scope})
    return {"ok": True, "created": True, "duplicate": False, "memory_id": memory_id, "version": 1, "memory": mongo_store._serialize(doc)}


def update_memory(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    memory_id = str(payload.get("memory_id") or "").strip()
    current = db[MEMORIES].find_one({"memory_id": memory_id, "status": {"$ne": "forgotten"}})
    if not current:
        return {"ok": False, "error": "memory_not_found"}
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    new_kind = str(payload.get("kind") or current.get("kind") or "fact").strip().lower()
    if new_kind not in MEMORY_KINDS:
        return {"ok": False, "error": "invalid_memory_kind", "allowed": sorted(MEMORY_KINDS)}
    pattern_payload = {**current, **payload}
    if new_kind == "pattern" and not _pattern_is_supported(pattern_payload):
        return {"ok": False, "error": "pattern_requires_longitudinal_evidence"}
    db[VERSIONS].insert_one(
        {
            "memory_id": memory_id,
            "version": int(current.get("version") or 1),
            "snapshot": {
                key: current.get(key)
                for key in (
                    "title",
                    "body",
                    "kind",
                    "privacy_scope",
                    "entities",
                    "tags",
                    "source_message_ids",
                    "source_conversation_ids",
                    "confidence",
                    "confidence_label",
                    "confidence_basis",
                    "owner_validated",
                    "epistemic_status",
                    "metadata",
                    "fingerprint",
                )
            },
            "reason": payload.get("reason") or "update",
            "changed_by": actor,
            "archived_at": _now(),
        }
    )
    body = str(payload.get("body") if payload.get("body") is not None else current.get("body") or "").strip()
    scope = _privacy(str(payload.get("privacy_scope") or current.get("privacy_scope")))
    _privacy_guard(body, scope)
    evidence = sorted(set([*(current.get("source_message_ids") or []), *(payload.get("source_message_ids") or [])]))
    source_conversation_ids = sorted(
        {
            str(value).strip()
            for value in [
                current.get("source_conversation_id"),
                payload.get("conversation_id"),
                *(current.get("source_conversation_ids") or []),
                *(payload.get("source_conversation_ids") or []),
            ]
            if str(value or "").strip()
        }
    )
    epistemic = _epistemic_values(new_kind, {**current, **payload})
    patch = {
        "title": str(payload.get("title") or current.get("title") or body[:120]).strip(),
        "body": body,
        "kind": new_kind,
        "type": new_kind,
        "privacy_scope": scope,
        "visibility": scope,
        "entities": payload.get("entities") if payload.get("entities") is not None else current.get("entities", []),
        "tags": payload.get("tags") if payload.get("tags") is not None else current.get("tags", []),
        "source_message_ids": evidence,
        "source_conversation_ids": source_conversation_ids,
        "evidence_count": len(evidence),
        "metadata": payload.get("metadata") if payload.get("metadata") is not None else current.get("metadata", {}),
        "version": int(current.get("version") or 1) + 1,
        "updated_at": _now(),
        "fingerprint": _fingerprint(owner_id=current["owner_id"], privacy_scope=scope, kind=new_kind, body=body, project=current.get("project")),
        **epistemic,
    }
    db[MEMORIES].update_one({"_id": current["_id"]}, {"$set": patch})
    _audit("memory_updated", actor=actor, subject_id=memory_id, metadata={"version": patch["version"], "reason": payload.get("reason")})
    return {"ok": True, "memory_id": memory_id, "version": patch["version"], "updated": True}


def update_current_state(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    owner_id = str(payload.get("owner_id") or "RAFAEL").strip().upper()
    state_key = str(payload.get("state_key") or "global").strip()
    scope = _privacy(str(payload.get("privacy_scope") or "PRIVATE_PERSONAL"))
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    now = _now()
    current = db[CURRENT_STATE].find_one({"owner_id": owner_id, "state_key": state_key}) or {}
    version = int(current.get("version") or 0) + 1
    doc = {
        "owner_id": owner_id,
        "state_key": state_key,
        "privacy_scope": scope,
        "summary": payload.get("summary"),
        "active_decisions": payload.get("active_decisions") or [],
        "active_intentions": payload.get("active_intentions") or [],
        "pattern_candidates": payload.get("pattern_candidates") or [],
        "pending_ids": payload.get("pending_ids") or [],
        "emotions": payload.get("emotions") or [],
        "entity_refs": payload.get("entity_refs") or [],
        "source_conversation_id": payload.get("conversation_id"),
        "version": version,
        "updated_at": now,
        "updated_by": actor,
    }
    db[CURRENT_STATE].update_one({"owner_id": owner_id, "state_key": state_key}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    _audit("current_state_updated", actor=actor, subject_id=f"{owner_id}:{state_key}", metadata={"version": version})
    return {"ok": True, "state_key": state_key, "version": version, "state": doc}


def get_current_state(payload: dict[str, Any]) -> dict[str, Any]:
    owner_id = str(payload.get("owner_id") or "RAFAEL").strip().upper()
    state_key = str(payload.get("state_key") or "global").strip()
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    doc = mongo_store.get_db()[CURRENT_STATE].find_one({"owner_id": owner_id, "state_key": state_key}, {"_id": 0})
    if not doc:
        return {"ok": True, "found": False, "state": None}
    if doc.get("privacy_scope") not in _allowed(actor, payload.get("allowed_privacy")):
        return {"ok": False, "error": "privacy_forbidden"}
    return {"ok": True, "found": True, "state": doc}


def _upsert_entities(owner_id: str, entities: list[dict[str, Any]], privacy_scope: str, conversation_id: str) -> list[str]:
    db = mongo_store.get_db()
    refs: list[str] = []
    for raw in entities:
        entity_type = str(raw.get("type") or raw.get("entity_type") or "").strip().upper()
        name = str(raw.get("name") or "").strip()
        if entity_type not in ENTITY_TYPES or not name:
            continue
        normalized = _normalized_text(name)
        existing = db[ENTITIES].find_one({"owner_id": owner_id, "entity_type": entity_type, "normalized_name": normalized})
        entity_id = existing.get("entity_id") if existing else _id("ent")
        relationship_context = {
            key: raw.get(key)
            for key in ("role", "relationship", "aliases")
            if raw.get(key) not in (None, "", [])
        }
        db[ENTITIES].update_one(
            {"owner_id": owner_id, "entity_type": entity_type, "normalized_name": normalized},
            {
                "$set": {
                    "name": name,
                    "privacy_scope": privacy_scope,
                    "relationship_context": relationship_context,
                    "updated_at": _now(),
                },
                "$setOnInsert": {"entity_id": entity_id, "created_at": _now()},
                "$addToSet": {"source_conversation_ids": conversation_id},
            },
            upsert=True,
        )
        refs.append(str(entity_id))
    return refs


def finalize_conversation(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_indexes()
    db = mongo_store.get_db()
    conversation_id = str(payload.get("conversation_id") or "").strip()
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    conversation = db[CONVERSATIONS].find_one({"conversation_id": conversation_id})
    if not conversation:
        return {"ok": False, "error": "conversation_not_found"}
    messages = list(db[MESSAGES].find({"conversation_id": conversation_id}, {"_id": 0}).sort("created_at", 1))
    if not messages:
        return {"ok": False, "error": "conversation_empty"}
    digest = _hash("|".join(f"{item.get('message_id')}:{item.get('content')}" for item in messages))
    if conversation.get("finalized_digest") == digest:
        return {"ok": True, "idempotent": True, "conversation_id": conversation_id, "result": conversation.get("finalization_result")}
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else _deterministic_analysis(messages)
    fallback_ids = [str(message.get("message_id")) for message in messages if message.get("message_id")]
    scope = _privacy(str(payload.get("privacy_scope") or conversation.get("privacy_scope") or "PRIVATE_PERSONAL"))
    owner_id = str(conversation.get("owner_id") or payload.get("owner_id") or "RAFAEL").upper()
    project = str(payload.get("project") or conversation.get("project") or "").strip() or None
    participants = [item for item in (conversation.get("participants") or []) if isinstance(item, dict)]
    entity_refs = _upsert_entities(owner_id, [*(analysis.get("entities") or []), *participants], scope, conversation_id)
    relationship_context = [
        {
            key: participant.get(key)
            for key in ("name", "role", "relationship")
            if participant.get(key) not in (None, "")
        }
        for participant in participants
    ]
    memory_ids: list[str] = []
    counts: dict[str, int] = {}
    for key, kind in (
        ("facts", "fact"),
        ("opinions", "opinion"),
        ("hypotheses", "hypothesis"),
        ("interpretations", "interpretation"),
        ("decisions", "decision"),
        ("intentions", "intention"),
        ("context_rules", "context_rule"),
        ("patterns", "pattern"),
        ("pattern_candidates", "interpretation"),
    ):
        items = _analysis_items(analysis, key, fallback_ids)
        counts[key] = len(items)
        for item in items:
            saved = save_memory(
                {
                    "owner_id": owner_id,
                    "kind": kind,
                    "title": item.get("title"),
                    "body": item["text"],
                    "privacy_scope": item.get("privacy_scope") or scope,
                    "project": project,
                    "entities": item.get("entities") or entity_refs,
                    "conversation_id": conversation_id,
                    "source_message_ids": item.get("source_message_ids") or fallback_ids,
                    "source_conversation_ids": item.get("source_conversation_ids") or [conversation_id],
                    "confidence": item.get("confidence"),
                    "confidence_basis": item.get("confidence_basis"),
                    "owner_validated": item.get("owner_validated", kind == "context_rule"),
                    "epistemic_status": item.get("epistemic_status"),
                    "metadata": {
                        **(item.get("metadata") or {}),
                        "relationship_context": relationship_context,
                        **({"not_a_diagnosis": True} if key in {"patterns", "pattern_candidates"} else {}),
                    },
                    "actor": actor,
                }
            )
            if saved.get("memory_id"):
                memory_ids.append(saved["memory_id"])
    emotion_items = _analysis_items(analysis, "emotions", fallback_ids)
    counts["emotions"] = len(emotion_items)
    for item in emotion_items:
        saved = save_memory(
            {
                "owner_id": owner_id,
                "kind": "emotion",
                "body": item["text"],
                "privacy_scope": scope,
                "project": project,
                "entities": item.get("entities") or entity_refs,
                "conversation_id": conversation_id,
                "source_message_ids": item.get("source_message_ids") or fallback_ids,
                "confidence": item.get("confidence"),
                "confidence_basis": item.get("confidence_basis"),
                "owner_validated": item.get("owner_validated", False),
                "metadata": {
                    **(item.get("metadata") or {}),
                    "relationship_context": relationship_context,
                    "not_a_diagnosis": True,
                },
                "actor": actor,
            }
        )
        if saved.get("memory_id"):
            memory_ids.append(saved["memory_id"])

    pending_ids: list[str] = []
    for item in _analysis_items(analysis, "pending", fallback_ids):
        pending_id = _id("pending")
        db[PENDING].insert_one(
            {
                "pending_id": pending_id,
                "owner_id": owner_id,
                "text": item["text"],
                "status": "open",
                "privacy_scope": item.get("privacy_scope") or scope,
                "project": project,
                "entity_refs": item.get("entities") or entity_refs,
                "source_conversation_id": conversation_id,
                "source_message_ids": item.get("source_message_ids") or fallback_ids,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
        pending_ids.append(pending_id)
    counts["pending"] = len(pending_ids)
    summary = str(analysis.get("summary") or "").strip()
    state = update_current_state(
        {
            "owner_id": owner_id,
            "state_key": str(payload.get("state_key") or (f"project:{project}" if project else "global")),
            "privacy_scope": scope,
            "summary": summary,
            "active_decisions": [item["text"] for item in _analysis_items(analysis, "decisions", fallback_ids)],
            "active_intentions": [item["text"] for item in _analysis_items(analysis, "intentions", fallback_ids)],
            "pattern_candidates": [item["text"] for item in _analysis_items(analysis, "pattern_candidates", fallback_ids)],
            "pending_ids": pending_ids,
            "emotions": [item["text"] for item in emotion_items],
            "entity_refs": entity_refs,
            "conversation_id": conversation_id,
            "actor": actor,
        }
    )
    timeline_id = _id("time")
    db[TIMELINE].insert_one(
        {
            "timeline_id": timeline_id,
            "owner_id": owner_id,
            "event_type": "conversation_finalized",
            "title": f"Conversation {conversation_id} finalized",
            "summary": summary,
            "privacy_scope": scope,
            "project": project,
            "entity_refs": entity_refs,
            "memory_ids": sorted(set(memory_ids)),
            "pending_ids": pending_ids,
            "source_conversation_id": conversation_id,
            "occurred_at": payload.get("occurred_at") or _now(),
            "created_at": _now(),
        }
    )
    result = {
        "summary": summary,
        "counts": counts,
        "memory_ids": sorted(set(memory_ids)),
        "pending_ids": pending_ids,
        "entity_refs": entity_refs,
        "current_state_key": state.get("state_key"),
        "timeline_id": timeline_id,
        "pipeline": ["session_summary", "entity_extraction", "emotion_analysis", "decision_extraction", "intention_extraction", "context_rule_learning", "pending_detection", "duplicate_search", "memory_builder", "current_state_update", "timeline_update"],
    }
    db[CONVERSATIONS].update_one(
        {"conversation_id": conversation_id},
        {"$set": {"status": "finalized", "finalized_at": _now(), "finalized_by": actor, "finalized_digest": digest, "finalization_result": result, "updated_at": _now()}},
    )
    _audit("conversation_finalized", actor=actor, subject_id=conversation_id, metadata={"counts": counts, "memory_count": len(set(memory_ids))})
    return {"ok": True, "idempotent": False, "conversation_id": conversation_id, "result": result}


def search_memory(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    query = str(payload.get("query") or "").strip()
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    allowed = _allowed(actor, payload.get("allowed_privacy"))
    filt: dict[str, Any] = {"status": "active", "privacy_scope": {"$in": sorted(allowed)}}
    if payload.get("owner_id"):
        filt["owner_id"] = str(payload["owner_id"]).strip().upper()
    if payload.get("kind") or payload.get("type"):
        filt["kind"] = str(payload.get("kind") or payload.get("type")).strip().lower()
    if payload.get("project"):
        filt["project"] = str(payload["project"]).strip()
    if payload.get("entity_id"):
        filt["entities"] = str(payload["entity_id"]).strip()
    candidates = list(db[MEMORIES].find(filt, {"_id": 0}).limit(500))
    scored: list[dict[str, Any]] = []
    tokens = set(_normalized_text(query).split())
    for item in candidates:
        text = _normalized_text(" ".join([str(item.get("title") or ""), str(item.get("body") or ""), " ".join(item.get("tags") or [])]))
        words = set(text.split())
        score = (len(tokens & words) / max(1, len(tokens))) if tokens else 1.0
        if query.lower() in str(item.get("body") or "").lower():
            score += 1.0
        if score > 0:
            if item.get("kind") == "context_rule":
                score += 0.35
            if item.get("owner_validated"):
                score += 0.2
            if item.get("kind") == "pattern":
                score += 0.1
        if score >= float(payload.get("min_score") or 0.01):
            item["score"] = round(score, 4)
            scored.append(item)
    scored.sort(key=lambda item: (item["score"], item.get("updated_at") or ""), reverse=True)
    limit = max(1, min(int(payload.get("limit") or 10), 50))
    return {"ok": True, "count": len(scored[:limit]), "items": scored[:limit], "allowed_privacy": sorted(allowed)}


def get_person_context(payload: dict[str, Any]) -> dict[str, Any]:
    person_id = str(payload.get("person_id") or "").strip()
    if not person_id:
        return {"ok": False, "error": "person_id_required"}
    db = mongo_store.get_db()
    entity = db[ENTITIES].find_one({"entity_id": person_id, "entity_type": "PERSON"}, {"_id": 0})
    if not entity:
        return {"ok": False, "error": "person_not_found"}
    memories = search_memory({**payload, "query": payload.get("query") or "", "entity_id": person_id, "limit": payload.get("limit") or 20})
    pending = list(db[PENDING].find({"entity_refs": person_id, "status": "open", "privacy_scope": {"$in": memories.get("allowed_privacy", [])}}, {"_id": 0}).limit(20))
    items = memories.get("items", [])
    return {
        "ok": True,
        "person": entity,
        "memories": items,
        "interpretation_guidance": [item for item in items if item.get("kind") == "context_rule"],
        "observed_patterns": [item for item in items if item.get("kind") == "pattern"],
        "pending": pending,
    }


def correct_memory(payload: dict[str, Any]) -> dict[str, Any]:
    correction_at = _now()
    evidence = sorted(set(str(value) for value in (payload.get("source_message_ids") or []) if value))
    payload = {
        **payload,
        "reason": payload.get("reason") or "correction",
        "confidence": 1.0,
        "confidence_basis": "owner_correction",
        "owner_validated": True,
        "epistemic_status": "corrected",
    }
    result = update_memory(payload)
    if result.get("ok"):
        db = mongo_store.get_db()
        note = payload.get("correction_note") or payload.get("reason")
        db[MEMORIES].update_one(
            {"memory_id": payload["memory_id"]},
            {
                "$set": {"corrected_at": correction_at, "correction_note": note},
                "$push": {
                    "correction_history": {
                        "at": correction_at,
                        "note": note,
                        "source_message_ids": evidence,
                        "changed_by": str(payload.get("actor") or "RAFAEL").strip().upper(),
                    }
                },
            },
        )
        learned_rule = payload.get("learned_rule")
        if learned_rule:
            current = db[MEMORIES].find_one({"memory_id": payload["memory_id"]}) or {}
            rule = learned_rule if isinstance(learned_rule, dict) else {"body": str(learned_rule)}
            rule_result = save_memory(
                {
                    **rule,
                    "owner_id": current.get("owner_id") or "RAFAEL",
                    "kind": "context_rule",
                    "privacy_scope": rule.get("privacy_scope") or current.get("privacy_scope") or "PRIVATE_PERSONAL",
                    "project": rule.get("project") or current.get("project"),
                    "entities": rule.get("entities") or current.get("entities") or [],
                    "conversation_id": rule.get("conversation_id") or payload.get("conversation_id"),
                    "source_message_ids": rule.get("source_message_ids") or evidence,
                    "owner_validated": True,
                    "confidence_basis": "owner_correction",
                    "metadata": {**(rule.get("metadata") or {}), "learned_from_memory_id": payload["memory_id"]},
                    "actor": payload.get("actor") or "RAFAEL",
                }
            )
            result["learned_rule_memory_id"] = rule_result.get("memory_id")
    return result


def forget_memory(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    memory_id = str(payload.get("memory_id") or "").strip()
    current = db[MEMORIES].find_one({"memory_id": memory_id})
    if not current:
        return {"ok": False, "error": "memory_not_found"}
    actor = str(payload.get("actor") or "RAFAEL").strip().upper()
    if actor != "RAFAEL":
        return {"ok": False, "error": "forget_requires_owner"}
    now = _now()
    db[VERSIONS].delete_many({"memory_id": memory_id})
    db[MEMORIES].update_one(
        {"memory_id": memory_id},
        {"$set": {"title": "[FORGOTTEN]", "body": "[FORGOTTEN]", "status": "forgotten", "fingerprint": f"forgotten:{memory_id}", "entities": [], "tags": [], "forgotten_at": now, "forget_reason": payload.get("reason"), "updated_at": now}},
    )
    if payload.get("purge_source_messages") is True:
        db[MESSAGES].delete_many({"message_id": {"$in": current.get("source_message_ids") or []}})
    _audit("memory_forgotten", actor=actor, subject_id=memory_id, metadata={"purged_sources": bool(payload.get("purge_source_messages"))})
    return {"ok": True, "memory_id": memory_id, "status": "forgotten", "versions_deleted": True}


def resolve_pending_item(payload: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    pending_id = str(payload.get("pending_id") or "").strip()
    status = str(payload.get("status") or "resolved").strip().lower()
    if status not in {"resolved", "cancelled"}:
        return {"ok": False, "error": "invalid_pending_status"}
    now = _now()
    result = db[PENDING].update_one(
        {"pending_id": pending_id, "status": "open"},
        {"$set": {"status": status, "resolution": payload.get("resolution"), "resolved_at": now, "updated_at": now, "resolved_by": payload.get("actor") or "RAFAEL"}},
    )
    if result.modified_count != 1:
        return {"ok": False, "error": "pending_not_open"}
    item = db[PENDING].find_one({"pending_id": pending_id}, {"_id": 0}) or {}
    db[TIMELINE].insert_one({"timeline_id": _id("time"), "owner_id": item.get("owner_id"), "event_type": "pending_resolved", "title": item.get("text"), "summary": payload.get("resolution"), "privacy_scope": item.get("privacy_scope"), "project": item.get("project"), "pending_ids": [pending_id], "occurred_at": now, "created_at": now})
    return {"ok": True, "pending_id": pending_id, "status": status}


def timeline(payload: dict[str, Any]) -> dict[str, Any]:
    actor = str(payload.get("actor") or "CHATGPT").strip().upper()
    allowed = _allowed(actor, payload.get("allowed_privacy"))
    filt: dict[str, Any] = {"privacy_scope": {"$in": sorted(allowed)}}
    if payload.get("owner_id"):
        filt["owner_id"] = str(payload["owner_id"]).strip().upper()
    if payload.get("project"):
        filt["project"] = str(payload["project"]).strip()
    if payload.get("entity_id"):
        filt["entity_refs"] = str(payload["entity_id"]).strip()
    limit = max(1, min(int(payload.get("limit") or 50), 200))
    items = list(mongo_store.get_db()[TIMELINE].find(filt, {"_id": 0}).sort("occurred_at", -1).limit(limit))
    return {"ok": True, "count": len(items), "items": items, "allowed_privacy": sorted(allowed)}


def review_queue(*, actor: str, status: str = "active", limit: int = 50) -> dict[str, Any]:
    if actor.strip().upper() != "RAFAEL":
        return {"ok": False, "error": "review_requires_owner"}
    db = mongo_store.get_db()
    memories = list(db[MEMORIES].find({"status": status}, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 100))))
    pending = list(db[PENDING].find({"status": "open"}, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 100))))
    return {"ok": True, "memories": memories, "pending": pending, "privacy_scopes": sorted(PRIVACY_SCOPES)}


def migrate_schema(*, dry_run: bool = True, limit: int = 1000) -> dict[str, Any]:
    """Backfill legacy ralfia_memory_items in place; never changes content classification."""
    db = mongo_store.get_db()
    cursor = db[MEMORIES].find(
        {"$or": [{"memory_id": {"$exists": False}}, {"privacy_scope": {"$exists": False}}, {"version": {"$exists": False}}, {"status": {"$exists": False}}]}
    ).limit(max(1, min(int(limit), 5000)))
    scanned = 0
    migrated = 0
    preview: list[dict[str, Any]] = []
    for doc in cursor:
        scanned += 1
        memory_id = str(doc.get("memory_id") or f"mem_legacy_{str(doc['_id'])}")
        scope = _privacy(str(doc.get("privacy_scope") or doc.get("visibility") or "PRIVATE_PERSONAL"))
        kind = str(doc.get("kind") or doc.get("type") or "fact").lower()
        if kind not in MEMORY_KINDS:
            kind = "fact"
        body = str(doc.get("body") or doc.get("content") or "")
        owner_id = str(doc.get("owner_id") or "RAFAEL").upper()
        fingerprint = _fingerprint(owner_id=owner_id, privacy_scope=scope, kind=kind, body=body, project=doc.get("project"))
        if db[MEMORIES].find_one({"fingerprint": fingerprint, "_id": {"$ne": doc["_id"]}}):
            fingerprint = f"{fingerprint}:legacy:{str(doc['_id'])}"
        patch = {
            "memory_id": memory_id,
            "owner_id": owner_id,
            "privacy_scope": scope,
            "visibility": scope,
            "kind": kind,
            "type": kind,
            "version": int(doc.get("version") or 1),
            "status": str(doc.get("status") or "active"),
            "source_message_ids": doc.get("source_message_ids") or [],
            "entities": doc.get("entities") or [],
            "source_conversation_ids": [str(doc.get("source_conversation_id"))] if doc.get("source_conversation_id") else [],
            "evidence_count": len(doc.get("source_message_ids") or []),
            "fingerprint": fingerprint,
            **_epistemic_values(kind, doc),
            "updated_at": doc.get("updated_at") or _now(),
        }
        preview.append({"_id": str(doc["_id"]), "memory_id": memory_id, "privacy_scope": scope, "kind": kind})
        if not dry_run:
            db[MEMORIES].update_one({"_id": doc["_id"]}, {"$set": patch})
            migrated += 1
    if not dry_run:
        ensure_indexes()
        _audit("memory_schema_migrated", actor="SYSTEM", metadata={"migrated": migrated})
    return {"ok": True, "dry_run": dry_run, "scanned": scanned, "migrated": migrated, "preview": preview[:50]}
