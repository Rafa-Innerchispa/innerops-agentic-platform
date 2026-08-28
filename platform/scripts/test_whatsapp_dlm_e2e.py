#!/usr/bin/env python3
"""Isolated Mongo E2E for WhatsApp/Daily Life Memory using synthetic fixtures only."""

from __future__ import annotations

import json

from raphiia_openai import daily_memory, mongo_store

OWNER = "FIXTURE_WHATSAPP_DLM_E2E"
CONVERSATION = "fixture:whatsapp:dlm:e2e:private_health"
MESSAGE_IDS = ["FIXTURE-WA-DLM-1", "FIXTURE-WA-DLM-1:assistant"]


def cleanup() -> None:
    db = mongo_store.get_db()
    memories = list(db[daily_memory.MEMORIES].find({"owner_id": OWNER}, {"memory_id": 1}))
    memory_ids = [item.get("memory_id") for item in memories if item.get("memory_id")]
    db[daily_memory.VERSIONS].delete_many({"memory_id": {"$in": memory_ids}})
    for collection in (
        daily_memory.MEMORIES,
        daily_memory.CURRENT_STATE,
        daily_memory.ENTITIES,
        daily_memory.PENDING,
        daily_memory.TIMELINE,
    ):
        db[collection].delete_many({"owner_id": OWNER})
    db[daily_memory.MESSAGES].delete_many({"conversation_id": CONVERSATION})
    db[daily_memory.CONVERSATIONS].delete_many({"conversation_id": CONVERSATION})
    db[daily_memory.AUDIT].delete_many(
        {
            "$or": [
                {"subject_id": CONVERSATION},
                {"subject_id": {"$in": memory_ids}},
                {"subject_id": {"$regex": f"^{OWNER}:"}},
            ]
        }
    )


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def main() -> None:
    cleanup()
    report: dict[str, object] = {"fixture_owner": OWNER, "conversation_id": CONVERSATION}
    try:
        payload = {
            "conversation_id": CONVERSATION,
            "owner_id": OWNER,
            "actor": "RAFAEL",
            "privacy_scope": "PRIVATE_HEALTH",
            "source": "whatsapp_fixture",
            "messages": [
                {
                    "message_id": MESSAGE_IDS[0],
                    "role": "user",
                    "content": "FIXTURE: hoy siento ansiedad de prueba y decidí descansar; no son datos reales.",
                    "metadata": {"channel": "whatsapp", "derived_media_is_executable": False},
                },
                {
                    "message_id": MESSAGE_IDS[1],
                    "role": "assistant",
                    "content": "FIXTURE: respuesta sintética de acompañamiento.",
                },
            ],
        }
        first = daily_memory.save_conversation_batch(payload)
        second = daily_memory.save_conversation_batch(payload)
        require(first.get("inserted") == 2, "first_batch_must_insert_two")
        require(second.get("inserted") == 0, "second_batch_must_be_idempotent")
        finalized = daily_memory.finalize_conversation(
            {
                "conversation_id": CONVERSATION,
                "owner_id": OWNER,
                "actor": "RAFAEL",
                "privacy_scope": "PRIVATE_HEALTH",
                "state_key": "whatsapp:private_health",
            }
        )
        finalized_again = daily_memory.finalize_conversation(
            {"conversation_id": CONVERSATION, "owner_id": OWNER, "actor": "RAFAEL"}
        )
        require(finalized.get("ok") is True, "finalize_failed")
        require(finalized_again.get("idempotent") is True, "finalize_not_idempotent")
        pipeline = (finalized.get("result") or {}).get("pipeline") or []
        require(pipeline[-2:] == ["current_state_update", "timeline_update"], "pipeline_incomplete")
        state = daily_memory.get_current_state(
            {"owner_id": OWNER, "state_key": "whatsapp:private_health", "actor": "RAFAEL"}
        )
        search = daily_memory.search_memory(
            {
                "owner_id": OWNER,
                "query": "ansiedad descansar",
                "actor": "RAFAEL",
                "allowed_privacy": ["PRIVATE_HEALTH"],
            }
        )
        timeline = daily_memory.timeline(
            {"owner_id": OWNER, "actor": "RAFAEL", "allowed_privacy": ["PRIVATE_HEALTH"]}
        )
        rejected = daily_memory.search_memory(
            {
                "owner_id": OWNER,
                "query": "ansiedad",
                "actor": "UNAUTHORIZED_FIXTURE_AGENT",
                "allowed_privacy": ["PRIVATE_HEALTH"],
            }
        )
        db = mongo_store.get_db()
        promoted = db[daily_memory.MEMORIES].count_documents(
            {"owner_id": OWNER, "privacy_scope": {"$in": ["PUBLIC", "PROJECT", "DEMO"]}}
        )
        require(state.get("found") is True, "current_state_missing")
        require(search.get("count", 0) >= 1, "private_memory_not_searchable_by_owner")
        require(timeline.get("count", 0) >= 1, "timeline_missing")
        require(rejected.get("count") == 0 and rejected.get("allowed_privacy") == [], "unauthorized_private_read")
        require(promoted == 0, "private_scope_promoted")
        report.update(
            {
                "status": "PASS",
                "first_inserted": first.get("inserted"),
                "retry_inserted": second.get("inserted"),
                "finalize_idempotent": finalized_again.get("idempotent"),
                "pipeline": pipeline,
                "memory_count": search.get("count"),
                "timeline_count": timeline.get("count"),
                "unauthorized_result_count": rejected.get("count"),
                "unauthorized_allowed_privacy": rejected.get("allowed_privacy"),
                "promoted_private_records": promoted,
            }
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        cleanup()


if __name__ == "__main__":
    main()
