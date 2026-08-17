"""Real MCP transport drill for message -> task -> inbox/HUB -> ACK -> lifecycle -> recovery."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def payload(result: Any) -> dict[str, Any]:
    return result.structuredContent or {}


async def call(session: ClientSession, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(name, args)
    data = payload(result)
    if data.get("ok") is not True:
        raise AssertionError(f"{name} failed: {data or result.content}")
    return data


async def main() -> None:
    url = os.getenv("COORD_E2E_MCP_URL", "http://127.0.0.1:18112/mcp")
    headers = {"X-API-Key": os.environ["MCP_API_KEY"]} if os.getenv("MCP_API_KEY") else {}
    run_id = os.getenv("COORD_E2E_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    correlation_id = f"coord-e2e-{run_id}"
    project = "coordination-mcp-audit"
    conversation_ref = f"chatgpt-daily-life-memory-{run_id}"

    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {
                "create_agent_message",
                "poll_agent_inbox",
                "get_coordination_live",
                "update_ops_task_state",
                "heartbeat_ops_task",
                "search",
                "list_agent_messages",
            }
            missing = sorted(required - names)
            if missing:
                raise AssertionError(f"missing tools: {missing}")

            created = await call(
                session,
                "create_agent_message",
                {
                    "from_agent": "CHATGPT",
                    "target_agent": "codex",
                    "title": "[P0 E2E] Coordinación recuperable",
                    "body": (
                        f"correlation_id: {correlation_id}\n"
                        f"project: {project}\n"
                        f"conversation_ref: {conversation_ref}\n"
                        "- Confirmar normalización automática\n"
                        "- Confirmar trazabilidad y recuperación semántica"
                    ),
                    "priority": "critical",
                    "message_type": "task",
                    "payload": {
                        "auto_create_ops_task": True,
                        "project": project,
                        "conversation_ref": conversation_ref,
                        "checklist": ["Normalizar", "Distribuir", "ACK", "Heartbeat", "Recuperar"],
                        "evidence_required": ["IDs", "timestamps", "search results"],
                    },
                    "correlation_id": correlation_id,
                    "idempotency_key": correlation_id,
                },
            )
            normalization = created.get("normalization") or {}
            task_id = normalization.get("task_id")
            source_message_id = created.get("message_id")
            if not task_id or normalization.get("correlation_id") != correlation_id:
                raise AssertionError(f"normalization missing linkage: {created}")

            live = await call(session, "get_coordination_live", {})
            open_task_ids = {task.get("task_id") for task in live.get("open_ops_tasks", [])}
            if task_id not in open_task_ids:
                raise AssertionError(f"task not visible in HUB/live state: {task_id}")

            polled = await call(session, "poll_agent_inbox", {"agent": "codex", "limit": 10, "auto_ack": True})
            if source_message_id not in set(polled.get("acknowledged") or []):
                raise AssertionError(f"automatic ACK missing for {source_message_id}: {polled}")

            accepted = await call(
                session,
                "update_ops_task_state",
                {"task_id": task_id, "status": "accepted", "actor": "codex", "expected_revision": 1},
            )
            started = await call(
                session,
                "update_ops_task_state",
                {"task_id": task_id, "status": "in_progress", "actor": "codex", "expected_revision": accepted["revision"]},
            )
            heartbeat = await call(
                session,
                "heartbeat_ops_task",
                {"task_id": task_id, "actor": "codex", "next_action": "Verificar recuperación", "files_touched": []},
            )
            verification = await call(
                session,
                "update_ops_task_state",
                {"task_id": task_id, "status": "verification", "actor": "codex", "expected_revision": started["revision"]},
            )

            by_task = await call(session, "search", {"query": task_id, "collection": "ralfia_ops_tasks", "limit": 10})
            by_correlation = await call(session, "search", {"query": correlation_id, "collection": "ralfia_ops_tasks", "limit": 10})
            by_project = await call(session, "search", {"query": project, "collection": "ralfia_ops_tasks", "limit": 10})
            semantic = await call(
                session,
                "search",
                {"query": "normalización trazabilidad recuperación", "collection": "ralfia_ops_tasks", "limit": 10},
            )
            if min(by_task["count"], by_correlation["count"], by_project["count"], semantic["count"]) < 1:
                raise AssertionError("one or more recovery paths returned zero results")

            completed = await call(
                session,
                "update_ops_task_state",
                {
                    "task_id": task_id,
                    "status": "completed",
                    "actor": "codex",
                    "expected_revision": verification["revision"],
                    "evidence": {"status": "PASS", "run_id": run_id, "source_message_id": source_message_id},
                },
            )
            output = {
                "status": "PASS",
                "run_id": run_id,
                "mcp_url": url,
                "source_message_id": source_message_id,
                "task_id": task_id,
                "correlation_id": correlation_id,
                "project": project,
                "conversation_ref": conversation_ref,
                "created_at": created.get("message", {}).get("created_at"),
                "hub_revision_at_distribution": live.get("revision"),
                "ack_count": polled.get("ack_count"),
                "accepted_revision": accepted.get("revision"),
                "started_revision": started.get("revision"),
                "last_heartbeat_at": heartbeat.get("last_heartbeat_at"),
                "verification_revision": verification.get("revision"),
                "completed_revision": completed.get("revision"),
                "recovery_counts": {
                    "task_id": by_task.get("count"),
                    "correlation_id": by_correlation.get("count"),
                    "project": by_project.get("count"),
                    "semantic": semantic.get("count"),
                },
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
