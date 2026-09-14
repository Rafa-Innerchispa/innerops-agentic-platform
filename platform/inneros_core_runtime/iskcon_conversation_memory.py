"""ISKCON conversation capture over Daily Life Memory.

This module keeps ISKCON-specific routing in the shared InnerOS memory plane:
project=iskcon, entity=ent_iskcon, explicit provenance, and fail-closed
backfill. It does not invent missing conversations.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from raphiia_openai import daily_memory, mongo_store
from raphiia_openai.agents.iskcon_capabilities import ENTITY_ID, PROJECT

TASK_ID = "ops_6a1f394e5b9c"
CORRELATION_ID = "iskcon-conversation-memory-20260913"

KEYWORDS = (
    "iskcon",
    "hare krishna",
    "krishna",
    "bhakti",
    "bhagavad",
    "gita",
    "gītā",
    "templo",
    "panihati",
    "vive india",
    "food for life",
    "ffl",
    "prasadam",
    "prasada",
    "vaishnava",
    "vaisnava",
    "devoto",
    "devota",
    "yoga",
)

PRIVATE_HINTS = (
    "privado",
    "personal",
    "familia",
    "salud",
    "médic",
    "medic",
    "relación",
    "relacion",
    "pareja",
    "dinero",
    "deuda",
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _message_text(message: dict[str, Any]) -> str:
    return str(message.get("content") or message.get("text") or message.get("body") or "").strip()


def _matched_keywords(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({keyword for keyword in KEYWORDS if keyword in lowered})


def relevant_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only source messages that carry an ISKCON signal.

    Historical ChatGPT conversations can mix ISKCON with private or unrelated
    life context. Backfill must not pull the whole conversation into the
    ISKCON project just because one turn matched.
    """
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        text = _message_text(message)
        if not _matched_keywords(text):
            continue
        key = str(message.get("message_id") or message.get("id") or f"{index}:{_hash(text)[:12]}")
        if key in seen:
            continue
        seen.add(key)
        output.append(message)
    return output


def classify_messages(messages: list[dict[str, Any]], *, force: bool = False) -> dict[str, Any]:
    """Return deterministic ISKCON routing metadata for a message batch."""
    text = "\n".join(_message_text(message) for message in messages if isinstance(message, dict))
    matched = _matched_keywords(text)
    privacy_scope = "PRIVATE_PERSONAL" if any(hint in text.lower() for hint in PRIVATE_HINTS) else "PROJECT"
    return {
        "ok": True,
        "is_iskcon": force or bool(matched),
        "matched_keywords": matched,
        "project": PROJECT,
        "entity_id": ENTITY_ID,
        "privacy_scope": privacy_scope,
    }


def build_conversation_payload(
    *,
    conversation_id: str,
    messages: list[dict[str, Any]],
    privacy_scope: str | None = None,
    source: str = "chatgpt",
    provenance: str = "chatgpt_conversation_backfill",
    source_conversation_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    route = classify_messages(messages, force=force)
    if not route["is_iskcon"]:
        return {**route, "ok": False, "error": "not_iskcon_conversation"}
    scoped = privacy_scope or route["privacy_scope"]
    out_messages: list[dict[str, Any]] = []
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict):
            continue
        content = _message_text(raw)
        role = str(raw.get("role") or "user").strip().lower()
        if role not in {"user", "assistant", "system", "tool"}:
            role = "user"
        if not content:
            continue
        original_message_id = str(raw.get("message_id") or raw.get("id") or "").strip()
        stable_id = original_message_id or f"iskcon_msg_{_hash(f'{conversation_id}|{index}|{role}|{content}')[:16]}"
        out_messages.append(
            {
                "message_id": stable_id,
                "source_message_id": original_message_id or stable_id,
                "role": role,
                "content": content,
                "turn_index": raw.get("turn_index", index),
                "timestamp": raw.get("timestamp") or raw.get("created_at"),
                "source": str(raw.get("source") or source),
                "provenance": str(raw.get("provenance") or provenance),
                "metadata": {
                    **(raw.get("metadata") or {}),
                    "project": PROJECT,
                    "entity_id": ENTITY_ID,
                    "source_conversation_id": source_conversation_id or conversation_id,
                    "matched_keywords": route["matched_keywords"],
                },
            }
        )
    if not out_messages:
        return {**route, "ok": False, "error": "no_messages_after_normalization"}
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "owner_id": "RAFAEL",
        "actor": "AG-52_ISKCON_OPS",
        "privacy_scope": scoped,
        "project": PROJECT,
        "participants": [{"type": "PROJECT", "name": "ISKCON", "role": "community_project", "aliases": ["ent_iskcon"]}],
        "metadata": {
            "project": PROJECT,
            "entity_id": ENTITY_ID,
            "matched_keywords": route["matched_keywords"],
            "source_conversation_id": source_conversation_id or conversation_id,
            "task_id": TASK_ID,
            "correlation_id": CORRELATION_ID,
        },
        "source": source,
        "provenance": provenance,
        "idempotency_key": f"{CORRELATION_ID}:{conversation_id}",
        "task_id": TASK_ID,
        "correlation_id": CORRELATION_ID,
        "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        "messages": out_messages,
    }


def _analysis_for(messages: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = daily_memory._deterministic_analysis(messages)
    analysis["entities"] = [{"type": "PROJECT", "name": "ISKCON", "role": "community_project", "aliases": ["ent_iskcon"]}]
    for key in (
        "facts",
        "opinions",
        "hypotheses",
        "interpretations",
        "decisions",
        "intentions",
        "context_rules",
        "patterns",
        "pattern_candidates",
        "pending",
        "emotions",
    ):
        for item in analysis.get(key) or []:
            if isinstance(item, dict):
                item.setdefault("entities", [ENTITY_ID])
                item.setdefault("metadata", {})
                item["metadata"].setdefault("project", PROJECT)
                item["metadata"].setdefault("entity_id", ENTITY_ID)
    return analysis


def save_and_finalize_conversation(
    *,
    conversation_id: str,
    messages: list[dict[str, Any]],
    privacy_scope: str | None = None,
    source: str = "chatgpt",
    provenance: str = "chatgpt_conversation_backfill",
    source_conversation_id: str | None = None,
    dry_run: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    payload = build_conversation_payload(
        conversation_id=conversation_id,
        messages=messages,
        privacy_scope=privacy_scope,
        source=source,
        provenance=provenance,
        source_conversation_id=source_conversation_id,
        force=force,
    )
    if not payload.get("ok"):
        return payload
    if dry_run:
        return {"ok": True, "dry_run": True, "would_save": payload}
    saved = daily_memory.save_conversation_batch(payload)
    if not saved.get("ok"):
        return {"ok": False, "stage": "save_conversation_batch", "save": saved}
    finalized = daily_memory.finalize_conversation(
        {
            "conversation_id": conversation_id,
            "actor": "AG-52_ISKCON_OPS",
            "project": PROJECT,
            "privacy_scope": payload["privacy_scope"],
            "state_key": f"project:{PROJECT}",
            "analysis": _analysis_for(payload["messages"]),
            "task_id": TASK_ID,
            "correlation_id": CORRELATION_ID,
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
        }
    )
    return {"ok": bool(finalized.get("ok")), "conversation_id": conversation_id, "save": saved, "finalize": finalized}


def search_iskcon_memory(query: str, *, actor: str = "RAFAEL", limit: int = 10) -> dict[str, Any]:
    result = daily_memory.search_memory(
        {
            "query": query,
            "owner_id": "RAFAEL",
            "actor": actor,
            "allowed_privacy": ["PRIVATE_PERSONAL", "PROJECT", "PUBLIC", "INTERNAL_WORK"],
            "project": PROJECT,
            "entity_id": ENTITY_ID,
            "limit": limit,
        }
    )
    if result.get("count", 0) > 0:
        return {"ok": True, "project": PROJECT, "entity_id": ENTITY_ID, "query": query, **result}
    fallback = daily_memory.search_memory(
        {
            "query": query,
            "owner_id": "RAFAEL",
            "actor": actor,
            "allowed_privacy": ["PRIVATE_PERSONAL", "PROJECT", "PUBLIC", "INTERNAL_WORK"],
            "project": PROJECT,
            "limit": limit,
        }
    )
    return {
        "ok": True,
        "project": PROJECT,
        "entity_id": ENTITY_ID,
        "query": query,
        "count": fallback.get("count", 0),
        "items": fallback.get("items") or [],
        "fallback_without_entity_filter": True,
    }


def hector_context_status() -> dict[str, Any]:
    result = search_iskcon_memory("Héctor Hector ISKCON templo comunidad", actor="RAFAEL", limit=5)
    if result.get("count", 0) > 0:
        return {"ok": True, "status": "FOUND", "result": result}
    return {
        "ok": True,
        "status": "GAP",
        "message": "No se encontró fuente local recuperable sobre Héctor en memoria ISKCON; no se fabrica contenido.",
        "result": result,
    }


def audit_historical_coverage(limit: int = 200) -> dict[str, Any]:
    db = mongo_store.get_db()
    regex = re.compile("|".join(re.escape(keyword) for keyword in KEYWORDS), re.IGNORECASE)
    source_filter = {"content": {"$regex": regex}, "conversation_id": {"$not": re.compile("^iskcon-backfill-")}}
    candidates = list(
        db[daily_memory.MESSAGES]
        .find(source_filter, {"_id": 0, "conversation_id": 1, "message_id": 1, "content": 1, "source": 1, "created_at": 1})
        .limit(max(1, min(limit, 1000)))
    )
    conversations = sorted({str(item.get("conversation_id")) for item in candidates if item.get("conversation_id")})
    indexed = db[daily_memory.CONVERSATIONS].count_documents({"project": PROJECT})
    memories = db[daily_memory.MEMORIES].count_documents({"project": PROJECT, "status": "active"})
    return {
        "ok": True,
        "project": PROJECT,
        "entity_id": ENTITY_ID,
        "candidate_messages_sampled": len(candidates),
        "candidate_conversations": len(conversations),
        "candidate_conversation_ids": conversations[:50],
        "indexed_conversations": indexed,
        "active_project_memories": memories,
        "limit": limit,
    }


def backfill_historical_iskcon(limit: int = 50, *, dry_run: bool = True) -> dict[str, Any]:
    db = mongo_store.get_db()
    regex = re.compile("|".join(re.escape(keyword) for keyword in KEYWORDS), re.IGNORECASE)
    source_filter = {"content": {"$regex": regex}, "conversation_id": {"$not": re.compile("^iskcon-backfill-")}}
    seeds = list(
        db[daily_memory.MESSAGES]
        .find(source_filter, {"_id": 0, "conversation_id": 1})
        .limit(max(1, min(limit, 200)))
    )
    source_ids = []
    for seed in seeds:
        cid = str(seed.get("conversation_id") or "").strip()
        if cid and cid not in source_ids:
            source_ids.append(cid)
    processed: list[dict[str, Any]] = []
    for source_id in source_ids:
        target_id = f"iskcon-backfill-{_hash(source_id)[:16]}"
        if db[daily_memory.CONVERSATIONS].find_one({"conversation_id": target_id}):
            processed.append({"source_conversation_id": source_id, "conversation_id": target_id, "status": "already_indexed"})
            continue
        raw_messages = list(
            db[daily_memory.MESSAGES]
            .find({"conversation_id": source_id}, {"_id": 0})
            .sort("turn_index", 1)
            .limit(200)
        )
        selected_messages = relevant_messages(raw_messages)
        if not selected_messages:
            processed.append({"source_conversation_id": source_id, "conversation_id": target_id, "status": "no_relevant_messages"})
            continue
        result = save_and_finalize_conversation(
            conversation_id=target_id,
            messages=selected_messages,
            source="chatgpt_historical",
            provenance="iskcon_historical_backfill",
            source_conversation_id=source_id,
            dry_run=dry_run,
            force=True,
        )
        processed.append({"source_conversation_id": source_id, "conversation_id": target_id, "status": "dry_run" if dry_run else "processed", "result": result})
    return {"ok": True, "dry_run": dry_run, "processed_count": len(processed), "processed": processed}
