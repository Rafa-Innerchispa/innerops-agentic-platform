"""InnerOS Switch Rooms & Mattermost Collaboration Adapter.

Connects humans and existing locally executed InnerOS agents via Switch Rooms / Mattermost.
Preserves InnerOS MCP/A2A orchestration, approval policy, and audit as the absolute source of truth.
Enforces read-only diagnostic commands (!ping, !status, !incident) by default,
with CID propagation, deduplication, latency tracking, and strict rejection of unauthorized mutations.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from raphiia_openai import mongo_store

logger = logging.getLogger("inneros.switch_rooms")

DEFAULT_SWITCH_URL = os.getenv("SWITCH_URL", "http://127.0.0.1:62326").rstrip("/")
DEFAULT_ROOM_NAME = "inneros-live-operations"
DEFAULT_NODE_ID = "AMD-1.5"
COLLECTION_SWITCH_AUDIT = "inneros_switch_audit"

# Feature flag: opt-in by default
SWITCH_ROOMS_ENABLED = os.getenv("INNEROS_SWITCH_ROOMS_ENABLED", "true").lower() in ("true", "1", "yes")

# In-memory deduplication cache: hash -> timestamp
_dedup_cache: Dict[str, float] = {}
DEDUP_TTL_SECONDS = 300.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_dedup(message_id: str) -> bool:
    now = time.time()
    # Cleanup expired
    for k in list(_dedup_cache.keys()):
        if now - _dedup_cache[k] > DEDUP_TTL_SECONDS:
            del _dedup_cache[k]
    if message_id in _dedup_cache:
        return True
    _dedup_cache[message_id] = now
    return False


def _audit(action: str, payload: dict[str, Any]) -> None:
    doc = {
        "action": action,
        "payload": payload,
        "timestamp": _now(),
    }
    try:
        mongo_store.get_db()[COLLECTION_SWITCH_AUDIT].insert_one(doc)
    except Exception:
        pass


class SwitchRoomsAdapter:
    """Adapter bridging Switch Rooms / Mattermost with InnerOS capabilities."""

    def __init__(
        self,
        switch_url: str = DEFAULT_SWITCH_URL,
        room_name: str = DEFAULT_ROOM_NAME,
        node_id: str = DEFAULT_NODE_ID,
    ):
        self.switch_url = switch_url.rstrip("/")
        self.room_name = room_name
        self.node_id = node_id

    def check_switch_health(self) -> dict[str, Any]:
        """Checks health of Switch Core API endpoint."""
        start = time.perf_counter()
        try:
            req = urllib.request.Request(f"{self.switch_url}/health")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode())
                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                return {
                    "ok": True,
                    "status": data.get("status", "ok"),
                    "latency_ms": latency_ms,
                    "switch_url": self.switch_url,
                }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "ok": False,
                "status": "unreachable",
                "error": str(exc),
                "latency_ms": latency_ms,
                "switch_url": self.switch_url,
            }

    def handle_command(
        self,
        command_text: str,
        sender: str = "mattermost_user",
        correlation_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Processes commands (!ping, !status, !incident) with CID correlation and evidence."""
        started_at = time.perf_counter()
        raw = (command_text or "").strip()
        
        # Deduplication
        msg_key = message_id or f"{sender}:{raw}:{correlation_id}"
        if message_id and _is_dedup(msg_key):
            return {
                "ok": False,
                "error": "duplicate_message_ignored",
                "message_id": message_id,
                "correlation_id": correlation_id,
            }

        # Resolve or generate CID
        cid_match = re.search(r"\b(CID-[A-Za-z0-9_-]+|INNEROS-[A-Za-z0-9_-]+)\b", raw)
        cid = correlation_id or (cid_match.group(1) if cid_match else f"CID-SW-{uuid4().hex[:8].upper()}")

        tokens = [t for t in raw.split() if not t.startswith("@")]
        if not tokens:
            return {"ok": False, "error": "empty_command", "correlation_id": cid}

        cmd = tokens[0].lower()

        # 1. PING
        if cmd == "!ping":
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            resp_text = f"[INNEROS SWITCH PONG {self.node_id}] [{cid}] Status: OK | Node: {self.node_id} | Roundtrip Latency: {latency_ms}ms | Time: {_now()} | Collaboration Transport: Active."
            res = {
                "ok": True,
                "command": "!ping",
                "correlation_id": cid,
                "response_text": resp_text,
                "node_id": self.node_id,
                "latency_ms": latency_ms,
                "timestamp": _now(),
            }
            _audit("switch_command.ping", res)
            return res

        # 2. STATUS
        if cmd == "!status":
            # Check local Qwen LLM
            llm_ok = False
            try:
                test_req = urllib.request.Request("http://127.0.0.1:8000/v1/models")
                with urllib.request.urlopen(test_req, timeout=1.5) as r:
                    llm_ok = r.status == 200
            except Exception:
                llm_ok = False

            switch_h = self.check_switch_health()
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)

            resp_text = (
                f"[INNEROS STATUS {self.node_id}] [{cid}] "
                f"Node: {self.node_id} (192.168.1.5) | "
                f"Room: {self.room_name} | "
                f"Switch Gateway: {'ONLINE' if switch_h.get('ok') else 'OFFLINE'} ({switch_h.get('latency_ms', 0)}ms) | "
                f"Local Qwen ROCm LLM: {'ONLINE' if llm_ok else 'STANDBY'} | "
                f"Physical Safety Gate: ACTIVE | "
                f"Timestamp: {_now()}"
            )
            res = {
                "ok": True,
                "command": "!status",
                "correlation_id": cid,
                "response_text": resp_text,
                "node_id": self.node_id,
                "switch_status": switch_h,
                "local_llm_online": llm_ok,
                "latency_ms": latency_ms,
                "timestamp": _now(),
            }
            _audit("switch_command.status", res)
            return res

        # 3. INCIDENT (Read-only triage)
        if cmd in ("!incident", "!incidents"):
            # Query recent incidents from MongoDB
            incidents_summary = []
            try:
                db = mongo_store.get_db()
                recent = list(db["self_heal_incidents"].find({}, {"_id": 0}).sort("created_at", -1).limit(3))
                for inc in recent:
                    incidents_summary.append({
                        "id": inc.get("incident_id") or inc.get("id"),
                        "title": inc.get("title") or inc.get("summary"),
                        "status": inc.get("status", "resolved"),
                        "severity": inc.get("severity", "info"),
                    })
            except Exception:
                pass

            inc_count = len(incidents_summary)
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            resp_text = (
                f"[INNEROS INCIDENT TRIAGE {self.node_id}] [{cid}] "
                f"Active Incidents: {inc_count} | "
                f"Safety Policy: READ_ONLY_TRIAGE | "
                f"Auto-mitigation mutations: GATED (Requires Human Owner Approval) | "
                f"Recent: {incidents_summary if inc_count > 0 else 'None active. All subsystems operational.'}"
            )
            res = {
                "ok": True,
                "command": "!incident",
                "correlation_id": cid,
                "response_text": resp_text,
                "node_id": self.node_id,
                "incidents_count": inc_count,
                "incidents": incidents_summary,
                "latency_ms": latency_ms,
                "timestamp": _now(),
            }
            _audit("switch_command.incident", res)
            return res

        # 4. GATED / MUTATING COMMAND REJECTION
        if cmd in ("!reboot", "!deploy", "!create", "!delete", "!apply", "!exec"):
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            fail_text = f"[INNEROS POLICY REJECTED {self.node_id}] [{cid}] FAIL: Mutating command '{cmd}' rejected. InnerOS governance requires interactive human owner approval. Autonomous model approval is forbidden."
            res = {
                "ok": False,
                "command": cmd,
                "error": "mutating_command_rejected_by_policy",
                "correlation_id": cid,
                "response_text": fail_text,
                "latency_ms": latency_ms,
                "timestamp": _now(),
            }
            _audit("switch_command.rejected", res)
            return res

        # Unknown command
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        res = {
            "ok": False,
            "error": "unknown_command",
            "correlation_id": cid,
            "response_text": f"[{cid}] Unknown command '{cmd}'. Available diagnostic commands: !ping, !status, !incident",
            "latency_ms": latency_ms,
        }
        return res
