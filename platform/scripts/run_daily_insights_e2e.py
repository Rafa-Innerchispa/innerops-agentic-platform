"""Synthetic, self-cleaning E2E for Daily Life Memory insights."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from raphiia_openai import daily_memory, mongo_store


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
conv_one = f"fixture-dlm-insights-a-{stamp}"
conv_two = f"fixture-dlm-insights-b-{stamp}"
state_key = f"fixture:dlm-insights:{stamp}"
person_name = f"Persona Sintética {stamp}"
memory_ids: list[str] = []
db = mongo_store.get_db()
result: dict[str, object] = {"fixture": stamp}

try:
    batch = {
        "conversation_id": conv_one,
        "owner_id": "RAFAEL",
        "actor": "CODEX_E2E",
        "privacy_scope": "PRIVATE_RELATIONSHIPS",
        "participants": [
            {
                "type": "PERSON",
                "name": person_name,
                "role": "fixture_participant",
                "relationship": "synthetic_test",
            }
        ],
        "metadata": {"test_fixture": True},
        "messages": [
            {"role": "user", "message_id": f"{stamp}-m1", "content": "Hoy fui a una reunión sintética."},
            {
                "role": "user",
                "message_id": f"{stamp}-m2",
                "content": "Entre nosotros, código azul es humor interno y no significa agresión.",
            },
            {"role": "user", "message_id": f"{stamp}-m3", "content": "Quiero revisar el diario mañana."},
            {
                "role": "user",
                "message_id": f"{stamp}-m4",
                "content": "He notado un patrón: siempre me pasa al final del día.",
            },
        ],
    }
    first = daily_memory.save_conversation_batch(batch)
    second = daily_memory.save_conversation_batch(batch)
    require(first.get("inserted") == 4, "first batch did not insert four messages")
    require(second.get("inserted") == 0, "batch idempotency failed")

    finalized = daily_memory.finalize_conversation(
        {"conversation_id": conv_one, "actor": "CODEX_E2E", "state_key": state_key}
    )
    require(finalized.get("ok") and not finalized.get("idempotent"), "first finalization failed")
    again = daily_memory.finalize_conversation(
        {"conversation_id": conv_one, "actor": "CODEX_E2E", "state_key": state_key}
    )
    require(again.get("idempotent") is True, "finalization idempotency failed")

    docs_one = list(db[daily_memory.MEMORIES].find({"source_conversation_ids": conv_one}))
    memory_ids.extend(str(item["memory_id"]) for item in docs_one)
    kinds = {str(item.get("kind")) for item in docs_one}
    require({"fact", "intention", "context_rule", "interpretation"}.issubset(kinds), "claim types missing")
    require("pattern" not in kinds, "single-session candidate was promoted to pattern")
    rule = next(item for item in docs_one if item.get("kind") == "context_rule")
    require(rule.get("owner_validated") is True and rule.get("confidence") == 1.0, "context rule not validated")
    candidate = next(item for item in docs_one if (item.get("metadata") or {}).get("pattern_candidate"))
    require((candidate.get("metadata") or {}).get("not_a_diagnosis") is True, "pattern disclaimer missing")
    person = db[daily_memory.ENTITIES].find_one(
        {"owner_id": "RAFAEL", "normalized_name": daily_memory._normalized_text(person_name)}
    ) or {}
    person_context = daily_memory.get_person_context(
        {"person_id": person.get("entity_id"), "owner_id": "RAFAEL", "actor": "RAFAEL", "query": "código azul"}
    )
    require(person_context.get("ok"), "person context retrieval failed")
    require(person_context.get("interpretation_guidance"), "person context rule missing")

    fact = next(item for item in docs_one if item.get("kind") == "fact")
    corrected = daily_memory.correct_memory(
        {
            "memory_id": fact["memory_id"],
            "body": "Ayer fui a una reunión sintética.",
            "actor": "RAFAEL",
            "correction_note": "Fixture: corregir referencia temporal",
            "source_message_ids": [f"{stamp}-m2"],
            "conversation_id": conv_one,
            "learned_rule": {
                "body": "En este fixture, la referencia temporal corregida por el owner prevalece.",
                "metadata": {"test_fixture": True, "rule_type": "owner_correction"},
            },
        }
    )
    require(corrected.get("ok") and corrected.get("learned_rule_memory_id"), "correction learning failed")
    memory_ids.append(str(corrected["learned_rule_memory_id"]))
    corrected_doc = db[daily_memory.MEMORIES].find_one({"memory_id": fact["memory_id"]}) or {}
    require(corrected_doc.get("version") == 2, "correction was not versioned")
    require(len(corrected_doc.get("correction_history") or []) == 1, "correction history missing")

    batch_two = daily_memory.save_conversation_batch(
        {
            "conversation_id": conv_two,
            "owner_id": "RAFAEL",
            "actor": "CODEX_E2E",
            "privacy_scope": "PRIVATE_RELATIONSHIPS",
            "metadata": {"test_fixture": True},
            "messages": [
                {"role": "user", "message_id": f"{stamp}-m5", "content": "Hoy repetí la observación sintética."}
            ],
        }
    )
    require(batch_two.get("inserted") == 1, "second conversation save failed")
    finalized_two = daily_memory.finalize_conversation(
        {
            "conversation_id": conv_two,
            "actor": "CODEX_E2E",
            "state_key": state_key,
            "analysis": {
                "summary": "Segunda sesión sintética.",
                "patterns": [
                    {
                        "text": "En dos sesiones sintéticas aparece la misma observación al final del día.",
                        "source_message_ids": [f"{stamp}-m4", f"{stamp}-m5"],
                        "source_conversation_ids": [conv_one, conv_two],
                        "confidence": 0.7,
                    }
                ],
                "entities": [],
            },
        }
    )
    require(finalized_two.get("ok"), "longitudinal finalization failed")
    docs_two = list(db[daily_memory.MEMORIES].find({"source_conversation_ids": conv_two}))
    memory_ids.extend(str(item["memory_id"]) for item in docs_two)
    pattern = next(item for item in docs_two if item.get("kind") == "pattern")
    require((pattern.get("metadata") or {}).get("not_a_diagnosis") is True, "longitudinal disclaimer missing")

    search = daily_memory.search_memory(
        {"owner_id": "RAFAEL", "actor": "RAFAEL", "query": "código azul humor", "limit": 5}
    )
    require(any(item.get("kind") == "context_rule" for item in search.get("items") or []), "context retrieval failed")
    denied = daily_memory.search_memory(
        {"owner_id": "RAFAEL", "actor": "UNAUTHORIZED_FIXTURE", "query": "código azul", "limit": 5}
    )
    require(not denied.get("items"), "private memory leaked to non-owner actor")
    timeline = daily_memory.timeline(
        {"owner_id": "RAFAEL", "actor": "RAFAEL", "allowed_privacy": ["PRIVATE_RELATIONSHIPS"]}
    )
    require(
        any(item.get("source_conversation_id") in {conv_one, conv_two} for item in timeline.get("items") or []),
        "timeline fixture missing",
    )
    fixture_docs = list(
        db[daily_memory.MEMORIES].find(
            {"source_conversation_ids": {"$in": [conv_one, conv_two]}},
            {"privacy_scope": 1, "memory_id": 1},
        )
    )
    require(
        all(item.get("privacy_scope") == "PRIVATE_RELATIONSHIPS" for item in fixture_docs),
        "private fixture changed classification",
    )
    result.update(
        {
            "status": "PASS",
            "conversation_ids": [conv_one, conv_two],
            "message_idempotency": True,
            "finalization_idempotency": True,
            "claim_kinds": sorted(kinds),
            "context_rule_owner_validated": True,
            "person_context_guidance": True,
            "correction_version": corrected_doc.get("version"),
            "longitudinal_pattern": pattern.get("memory_id"),
            "private_non_owner_results": denied.get("count"),
            "privacy_preserved": True,
        }
    )
except Exception as exc:
    result.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
finally:
    fixture_memories = list(
        db[daily_memory.MEMORIES].find(
            {"source_conversation_ids": {"$in": [conv_one, conv_two]}}, {"memory_id": 1}
        )
    )
    memory_ids.extend(str(item.get("memory_id")) for item in fixture_memories if item.get("memory_id"))
    memory_ids = sorted(set(memory_ids))
    cleanup = {
        "messages": db[daily_memory.MESSAGES].delete_many({"conversation_id": {"$in": [conv_one, conv_two]}}).deleted_count,
        "conversations": db[daily_memory.CONVERSATIONS].delete_many({"conversation_id": {"$in": [conv_one, conv_two]}}).deleted_count,
        "memories": db[daily_memory.MEMORIES].delete_many({"memory_id": {"$in": memory_ids}}).deleted_count,
        "versions": db[daily_memory.VERSIONS].delete_many({"memory_id": {"$in": memory_ids}}).deleted_count,
        "pending": db[daily_memory.PENDING].delete_many({"source_conversation_id": {"$in": [conv_one, conv_two]}}).deleted_count,
        "timeline": db[daily_memory.TIMELINE].delete_many({"source_conversation_id": {"$in": [conv_one, conv_two]}}).deleted_count,
        "state": db[daily_memory.CURRENT_STATE].delete_many({"owner_id": "RAFAEL", "state_key": state_key}).deleted_count,
        "entities": db[daily_memory.ENTITIES].delete_many({"owner_id": "RAFAEL", "normalized_name": daily_memory._normalized_text(person_name)}).deleted_count,
    }
    result["cleanup"] = cleanup

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
sys.exit(0 if result.get("status") == "PASS" else 1)
