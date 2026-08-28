"""MCP transport E2E for Daily Life Memory with synthetic private data."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def unpack(result: Any) -> dict[str, Any]:
    return result.structuredContent or {}


async def call(session: ClientSession, name: str, args: dict[str, Any], *, ok: bool = True) -> dict[str, Any]:
    result = await session.call_tool(name, args)
    data = unpack(result)
    if bool(data.get("ok")) is not ok:
        raise AssertionError(f"{name}: expected ok={ok}, got {data or result.content}")
    if not ok and not data:
        text = " ".join(str(getattr(block, "text", "")) for block in result.content)
        return {"ok": False, "error": text}
    return data


async def main() -> None:
    url = os.getenv("DAILY_MEMORY_MCP_URL", "http://127.0.0.1:18112/mcp")
    headers = {"X-API-Key": os.environ["MCP_API_KEY"]} if os.getenv("MCP_API_KEY") else {}
    run_id = os.getenv("DAILY_MEMORY_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    conversation_id = f"dlm-e2e-{run_id}"
    project = f"daily-memory-e2e-{run_id}"
    messages = [
        {"message_id": f"{conversation_id}-1", "role": "user", "content": "Hoy revisé el diseño sintético de Daily Life Memory."},
        {"message_id": f"{conversation_id}-2", "role": "user", "content": "Creo que la separación de privacidad es correcta."},
        {"message_id": f"{conversation_id}-3", "role": "user", "content": "Tal vez debamos mejorar el extractor después."},
        {"message_id": f"{conversation_id}-4", "role": "user", "content": "Decidí ejecutar pruebas automáticas. Queda pendiente revisar el panel."},
    ]
    analysis = {
        "summary": "Sesión sintética para validar memoria privada, deduplicación, estado y timeline.",
        "facts": [{"text": "Se ejecutó una prueba sintética de Daily Life Memory.", "source_message_ids": [messages[0]["message_id"]]}],
        "opinions": [{"text": "La separación de privacidad parece correcta.", "source_message_ids": [messages[1]["message_id"]]}],
        "hypotheses": [{"text": "El extractor podría mejorarse después.", "source_message_ids": [messages[2]["message_id"]]}],
        "interpretations": [{"text": "La evidencia indica que el pipeline está conectado.", "source_message_ids": [messages[0]["message_id"]]}],
        "decisions": [{"text": "Ejecutar pruebas automáticas.", "source_message_ids": [messages[3]["message_id"]]}],
        "pending": [{"text": "Revisar el panel privado.", "source_message_ids": [messages[3]["message_id"]]}],
        "emotions": [{"text": "motivado", "source_message_ids": [messages[3]["message_id"]]}],
        "entities": [
            {"type": "PERSON", "name": "Persona E2E Sintética"},
            {"type": "PROJECT", "name": project},
            {"type": "PLACE", "name": "Laboratorio E2E"},
        ],
    }

    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            required = {
                "save_conversation_batch", "finalize_conversation", "save_memory", "update_memory", "search_memory",
                "get_current_state", "update_current_state", "get_person_context", "correct_memory", "forget_memory",
                "resolve_pending_item", "timeline", "get_memory_review_queue", "migrate_daily_memory",
            }
            if required - tools:
                raise AssertionError(f"missing tools: {sorted(required - tools)}")

            saved = await call(session, "save_conversation_batch", {"payload": {"conversation_id": conversation_id, "owner_id": "RAFAEL", "actor": "CHATGPT", "privacy_scope": "PRIVATE_PERSONAL", "project": project, "messages": messages}})
            if saved.get("inserted") != 4:
                raise AssertionError(saved)
            finalized = await call(session, "finalize_conversation", {"payload": {"conversation_id": conversation_id, "actor": "CHATGPT", "project": project, "state_key": f"project:{project}", "analysis": analysis}})
            result = finalized["result"]
            if len(result.get("memory_ids") or []) < 6 or len(result.get("entity_refs") or []) != 3:
                raise AssertionError(result)
            repeated = await call(session, "finalize_conversation", {"payload": {"conversation_id": conversation_id, "actor": "CHATGPT", "analysis": analysis}})
            if repeated.get("idempotent") is not True:
                raise AssertionError(repeated)

            private_search = await call(session, "search_memory", {"query": "prueba sintética", "actor": "RAFAEL", "owner_id": "RAFAEL", "allowed_privacy": ["PRIVATE_PERSONAL"], "project": project, "limit": 20})
            agent_search = await call(session, "search_memory", {"query": "prueba sintética", "actor": "CODEX", "owner_id": "RAFAEL", "allowed_privacy": ["PRIVATE_PERSONAL"], "project": project, "limit": 20})
            if private_search.get("count", 0) < 1 or agent_search.get("count") != 0:
                raise AssertionError({"private": private_search, "agent": agent_search})

            memory_id = result["memory_ids"][0]
            updated = await call(session, "update_memory", {"payload": {"memory_id": memory_id, "body": "Se ejecutó una prueba sintética versionada de Daily Life Memory.", "actor": "RAFAEL", "reason": "e2e update"}})
            corrected = await call(session, "correct_memory", {"payload": {"memory_id": memory_id, "body": "Se ejecutó y verificó una prueba sintética versionada de Daily Life Memory.", "actor": "RAFAEL", "correction_note": "E2E correction"}})
            if updated.get("version") != 2 or corrected.get("version") != 3:
                raise AssertionError({"updated": updated, "corrected": corrected})

            state = await call(session, "get_current_state", {"payload": {"owner_id": "RAFAEL", "actor": "RAFAEL", "state_key": f"project:{project}", "allowed_privacy": ["PRIVATE_PERSONAL"]}})
            if not state.get("found") or not state["state"].get("pending_ids"):
                raise AssertionError(state)
            pending_id = state["state"]["pending_ids"][0]
            resolved = await call(session, "resolve_pending_item", {"payload": {"pending_id": pending_id, "status": "resolved", "resolution": "Panel revisado en E2E", "actor": "RAFAEL"}})
            if resolved.get("status") != "resolved":
                raise AssertionError(resolved)

            person_id = result["entity_refs"][0]
            person = await call(session, "get_person_context", {"payload": {"person_id": person_id, "actor": "RAFAEL", "allowed_privacy": ["PRIVATE_PERSONAL"], "limit": 20}})
            timeline = await call(session, "timeline", {"payload": {"owner_id": "RAFAEL", "actor": "RAFAEL", "allowed_privacy": ["PRIVATE_PERSONAL"], "project": project, "limit": 20}})
            if not person.get("person") or timeline.get("count", 0) < 2:
                raise AssertionError({"person": person, "timeline": timeline})

            public_rejected = await call(session, "save_memory", {"type": "personal", "title": "Invalid public health memory", "body": "Mi diagnóstico médico sintético", "visibility": "PUBLIC", "actor": "RAFAEL"}, ok=False)
            forgotten_id = result["memory_ids"][-1]
            forgotten = await call(session, "forget_memory", {"payload": {"memory_id": forgotten_id, "actor": "RAFAEL", "reason": "E2E forget test"}})
            migration = await call(session, "migrate_daily_memory", {"dry_run": True, "limit": 100})
            review = await call(session, "get_memory_review_queue", {"actor": "RAFAEL", "status": "active", "limit": 10})

            print(json.dumps({
                "status": "PASS",
                "run_id": run_id,
                "conversation_id": conversation_id,
                "privacy_scope": "PRIVATE_PERSONAL",
                "messages_inserted": saved.get("inserted"),
                "pipeline": result.get("pipeline"),
                "memory_count": len(result.get("memory_ids") or []),
                "memory_version_after_correction": corrected.get("version"),
                "entity_count": len(result.get("entity_refs") or []),
                "pending_id": pending_id,
                "pending_status": resolved.get("status"),
                "current_state_version": state["state"].get("version"),
                "timeline_count": timeline.get("count"),
                "private_owner_search_count": private_search.get("count"),
                "private_agent_search_count": agent_search.get("count"),
                "public_sensitive_rejection": public_rejected.get("error"),
                "forgotten_memory_id": forgotten.get("memory_id"),
                "migration_dry_run_scanned": migration.get("scanned"),
                "review_queue_counts": {"memories": len(review.get("memories") or []), "pending": len(review.get("pending") or [])},
            }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
