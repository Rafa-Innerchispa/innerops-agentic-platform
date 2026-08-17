"""Advance an existing RACB task through the canonical MCP lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8102/mcp")
    parser.add_argument("--actor", default="codex")
    args = parser.parse_args()
    evidence: dict[str, Any] = json.loads(args.evidence.read_text(encoding="utf-8"))
    headers = {"X-API-Key": os.environ["MCP_API_KEY"]} if os.getenv("MCP_API_KEY") else {}
    output: list[dict[str, Any]] = []

    async with streamablehttp_client(args.url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            poll = await session.call_tool("poll_agent_inbox", {"agent": args.actor, "limit": 20, "auto_ack": True})
            output.append({"poll": poll.structuredContent})
            revision = 1
            for status in ("accepted", "in_progress"):
                result = await session.call_tool("update_ops_task_state", {"task_id": args.task_id, "status": status, "actor": args.actor, "expected_revision": revision})
                data = result.structuredContent or {}
                if not data.get("ok"):
                    raise AssertionError(data or result.content)
                revision = int(data["revision"])
                output.append(data)
            heartbeat = await session.call_tool("heartbeat_ops_task", {"task_id": args.task_id, "actor": args.actor, "next_action": "Final verification and evidence closure"})
            output.append(heartbeat.structuredContent or {})
            verification = await session.call_tool("update_ops_task_state", {"task_id": args.task_id, "status": "verification", "actor": args.actor, "expected_revision": revision})
            data = verification.structuredContent or {}
            if not data.get("ok"):
                raise AssertionError(data or verification.content)
            revision = int(data["revision"])
            output.append(data)
            completed = await session.call_tool("update_ops_task_state", {"task_id": args.task_id, "status": "completed", "actor": args.actor, "expected_revision": revision, "evidence": evidence})
            data = completed.structuredContent or {}
            if not data.get("ok"):
                raise AssertionError(data or completed.content)
            output.append(data)
    print(json.dumps({"ok": True, "task_id": args.task_id, "steps": output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
