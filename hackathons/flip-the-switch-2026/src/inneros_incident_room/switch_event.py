"""Hackathon-period Switch room adapter. Synthetic-only operations, no devices.

The policy engine is independent of the WebSocket transport so it can be
unit-tested without credentials, Docker or any network traffic. Only Switch's
server-authenticated sender IDs are accepted for approvals. Room membership
must still be configured correctly on the Switch server.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, asdict
import json
import os
from pathlib import Path
import sys
import time
from typing import Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from .core import HumanApproval, Incident, PolicyDenied, execute_fixture, propose_actions
from .evidence import verify_receipt_integrity
from .local_reasoner import LocalReasoner


@dataclass
class RoomPolicy:
    room_id: str
    approver_id: str
    clock: Callable[[], float] = time.time
    id_factory: Callable[[], str] = lambda: uuid4().hex[:10]
    pending_ttl_seconds: int = 600
    model_reasoner: Callable[[str], str] | None = None
    state: dict[str, str] = field(default_factory=lambda: {"synthetic-camera-a": "degraded"})
    pending: dict | None = None
    processed_messages: set[str] = field(default_factory=set)

    def handle(self, frame: dict) -> str | None:
        """Turn one Switch *message* frame into a room reply, if addressed.

        The input must originate from the Switch connection, not from an
        arbitrary HTTP callback supplied by a stranger. This only controls an
        in-memory fixture; it does NOT authenticate a physical-world action.
        """
        if frame.get("event") != "message":
            return None
        data = frame.get("data") or {}
        payload = data.get("payload") or {}
        if data.get("room_id") != self.room_id or payload.get("addressed") is not True:
            return None
        sender = payload.get("sender")
        body = payload.get("body")
        message_id = payload.get("message_id")
        if not isinstance(sender, str) or not sender or not isinstance(body, str):
            return None
        if not isinstance(message_id, str) or not message_id:
            return None
        if message_id in self.processed_messages:
            return None
        self.processed_messages.add(message_id)
        tokens = body.strip().split()
        if not tokens:
            return None
        while tokens and tokens[0].startswith("@"):
            tokens.pop(0)
        if not tokens:
            return None
        command = tokens[0].lower()
        if command in {"!incident", "/incident"} and len(tokens) == 1:
            return self._open_incident()
        if command in {"!approve", "!deny"} and len(tokens) == 2:
            return self._decide(command, tokens[1], sender)
        if command == "!status" and len(tokens) == 1:
            return ("SYNTHETIC room demo only. camera=" + self.state["synthetic-camera-a"]
                    + ("; pending action=" + self.pending["action"].action_id if self.pending else "; no pending action"))
        return "Incident Room: commands !incident, !status, !approve ACTION_ID, !deny ACTION_ID. Synthetic only."

    def _open_incident(self) -> str:
        if self.pending is not None:
            return "An incident is already awaiting a decision; resolve it before opening another."
        self.state["synthetic-camera-a"] = "degraded"
        incident_id = "DEMO-" + self.id_factory()
        incident = Incident(incident_id, "synthetic-building", "Synthetic camera unavailable",
                            "synthetic-camera-a", "synthetic", "2026-11-06T00:00:00Z")
        action = propose_actions(incident)[1]
        self.pending = {"incident": incident, "action": action,
                        "expires_at": self.clock() + self.pending_ttl_seconds}
        reasoned = ""
        if self.model_reasoner is not None:
            try:
                reasoned = " " + self.model_reasoner(incident_id)[:520]
            except Exception:
                reasoned = " Local model unavailable; deterministic synthetic triage remains active."
        return (f"[SYNTHETIC] RalphiIA triage: incident {incident_id}. "
                "Camera source: unavailable; separate synthetic network source: switch-port UP. "
                "Cause remains UNVERIFIED. FieldOps review: only simulated restart is allowlisted. "
                + reasoned + " "
                f"Human decision needed within {self.pending_ttl_seconds}s: "
                f"!approve {action.action_id} or !deny {action.action_id}. "
                "No real devices accessed.")

    def _decide(self, command: str, action_id: str, sender: str) -> str:
        # Exact Switch participant ID, not sender_name or claimed username text.
        if not self.approver_id or sender != self.approver_id:
            return "BLOCKED: sender is not the configured human approver. No state change."
        current = self.pending
        if current is None:
            return "BLOCKED: no pending incident/action."
        if self.clock() > current["expires_at"]:
            self.pending = None
            return "BLOCKED: human decision expired; open a new incident."
        if action_id != current["action"].action_id:
            return "BLOCKED: action ID mismatch. No state change."
        self.pending = None  # One-time action: replay cannot execute it again.
        if command == "!deny":
            return f"DENIED by authorized human for {action_id}. Synthetic state unchanged."
        incident, action = current["incident"], current["action"]
        approval = HumanApproval(action.action_id, action.target_alias, sender, True)
        try:
            receipt = execute_fixture(action, incident, self.state, approval,
                                      readback=lambda alias: self.state.get(alias, "unknown"))
        except PolicyDenied:
            return "BLOCKED by code-level policy. No physical execution."
        integrity = verify_receipt_integrity(receipt)
        return (f"[SYNTHETIC] FieldOps receipt: incident={receipt.incident_id}; "
                f"outcome={receipt.outcome}; post_state={receipt.post_state}; "
                f"verified_fixture_readback={receipt.independent_verification}; "
                f"digest_sha256={receipt.evidence_sha256}; digest_valid={integrity}. "
                "A digest is NOT a cryptographic signature. No production device touched.")

    def snapshot(self) -> dict:
        """Serialize the synthetic-only policy; never records any credential."""
        pending = None
        if self.pending is not None:
            pending = {
                "incident": asdict(self.pending["incident"]),
                "action": asdict(self.pending["action"]),
                "expires_at": self.pending["expires_at"],
            }
        return {"state": dict(self.state), "pending": pending,
                "processed_messages": list(self.processed_messages)[-1500:]}

    def restore(self, raw: dict) -> None:
        """Restore decisions after a network drop without re-executing approvals."""
        if not isinstance(raw, dict):
            return
        stored_state = raw.get("state")
        if isinstance(stored_state, dict):
            self.state.update({k: v for k, v in stored_state.items()
                               if k == "synthetic-camera-a" and v in {"degraded", "healthy"}})
        self.processed_messages = set(str(x) for x in raw.get("processed_messages", [])[-1500:])
        pending = raw.get("pending")
        if pending is None:
            self.pending = None
            return
        try:
            from .core import Action
            incident = Incident(**pending["incident"])
            action = Action(**pending["action"])
            if (incident.device_alias != "synthetic-camera-a"
                    or action.target_alias != incident.device_alias
                    or action.scope != "synthetic_fixture"
                    or action.operation != "simulate_restart"):
                return
            expires = float(pending["expires_at"])
            if expires >= self.clock():
                self.pending = {"incident": incident, "action": action, "expires_at": expires}
        except (TypeError, ValueError, KeyError):
            self.pending = None


@dataclass(frozen=True)
class SwitchConfig:
    base_url: str
    agent_id: str
    api_key: str
    room_id: str
    approver_id: str
    state_path: Path

    @classmethod
    def from_env(cls) -> "SwitchConfig":
        required = ["SWITCH_URL", "SWITCH_AGENT_ID", "SWITCH_AGENT_API_KEY",
                    "SWITCH_ROOM_ID", "SWITCH_APPROVER_ID"]
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ValueError("Missing environment variables: " + ", ".join(missing))
        base = os.environ["SWITCH_URL"].rstrip("/")
        parsed = urlparse(base)
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_local):
            raise ValueError("Remote Switch connections must use HTTPS; HTTP only loopback")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Switch URL must not contain credentials, query or fragment")
        state_path = Path(os.getenv("SWITCH_STATE_PATH", "~/.local/state/inneros-switch-demo/connection.json")).expanduser()
        return cls(base, os.environ["SWITCH_AGENT_ID"], os.environ["SWITCH_AGENT_API_KEY"],
                   os.environ["SWITCH_ROOM_ID"], os.environ["SWITCH_APPROVER_ID"], state_path)


class PermanentSwitchError(RuntimeError):
    """Authentication, takeover or configuration error requiring manual repair."""


class ConnectionState:
    def __init__(self, config: SwitchConfig):
        self.config = config
        self.cursor = 0
        self.generation: int | None = None
        self.connection_id = str(uuid4())
        self.pending_replies: dict[str, str] = {}
        self.policy_snapshot: dict | None = None
        try:
            data = json.loads(config.state_path.read_text(encoding="utf-8"))
            if data.get("agent_id") == config.agent_id and data.get("room_id") == config.room_id:
                self.connection_id = data["connection_id"]
                self.cursor = int(data.get("cursor") or 0)
                gen = data.get("generation")
                self.generation = int(gen) if gen is not None else None
                self.pending_replies = dict(data.get("pending_replies") or {})
                self.policy_snapshot = data.get("policy_snapshot")
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def persist(self) -> None:
        path = self.config.state_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = dict(agent_id=self.config.agent_id, room_id=self.config.room_id,
                    connection_id=self.connection_id, cursor=self.cursor, generation=self.generation,
                    pending_replies=self.pending_replies, policy_snapshot=self.policy_snapshot)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as out:
            json.dump(data, out)
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def ws_url(self) -> str:
        base = self.config.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        query = {"connection_id": self.connection_id, "rooms": self.config.room_id,
                 "filter": "all", "start_from": str(self.cursor) if self.cursor else "head"}
        if self.generation is not None:
            query["expected_generation"] = str(self.generation)
        return base + f"/agents/{self.config.agent_id}/connection/ws?" + urlencode(query)


def post_room_message(config: SwitchConfig, content: str) -> None:
    """Send room message via Switch's documented HTTP endpoint, not Mattermost."""
    url = f"{config.base_url}/agents/{config.agent_id}/message"
    body = json.dumps({"room_id": config.room_id, "content": content}).encode("utf-8")
    req = Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"})
    with urlopen(req, timeout=5) as result:
        if result.status not in (200, 201, 202):
            raise RuntimeError("Switch message rejected")


async def serve(config: SwitchConfig, *, policy_factory=None) -> None:
    """Real transport. Requires Switch running and websocket credentials.

    A dedicated queue processes each domain event while the receiving coroutine
    answers Switch's frequent ping frames without waiting on HTTP I/O.
    """
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise RuntimeError("Install websockets>=14 for a live Switch connection") from exc
    state = ConnectionState(config)
    local_reasoner = LocalReasoner.from_env()
    policy = (policy_factory() if policy_factory is not None else
              RoomPolicy(config.room_id, config.approver_id,
                         model_reasoner=(local_reasoner.diagnose if local_reasoner else None)))
    if state.policy_snapshot:
        policy.restore(state.policy_snapshot)
    backoff = 1
    while True:
        try:
            async with connect(state.ws_url(), additional_headers={
                "Authorization": f"Bearer {config.api_key}"}, open_timeout=10, ping_interval=None) as sock:
                backoff = 1
                queue: asyncio.Queue[dict | None] = asyncio.Queue()

                async def worker() -> None:
                    while True:
                        frame = await queue.get()
                        try:
                            if frame is None:
                                return
                            mid = str((frame.get("data") or {}).get("payload", {}).get("message_id") or "")
                            response = state.pending_replies.get(mid) if mid else None
                            if response is None:
                                response = await asyncio.to_thread(policy.handle, frame)
                                if response is not None and mid:
                                    # Atomic intent journal BEFORE HTTP delivery. No credentials.
                                    state.pending_replies[mid] = response
                                state.policy_snapshot = policy.snapshot()
                                state.persist()
                            if response is not None:
                                await asyncio.to_thread(post_room_message, config, response)
                            seq = frame.get("id")
                            if isinstance(seq, int) and seq > state.cursor:
                                state.cursor = seq
                            if mid:
                                state.pending_replies.pop(mid, None)
                            state.policy_snapshot = policy.snapshot()
                            state.persist()
                        except Exception:
                            # Force a reconnect so replay can retry unsent replies.
                            # An accepted action is not executed again; policy is journaled.
                            await sock.close(code=1011, reason="response_delivery_failed")
                            return
                        finally:
                            queue.task_done()
                task = asyncio.create_task(worker())
                try:
                    # Flush an earlier unsent reply before processing more events.
                    # If the HTTP call succeeded before a crash, replay may cause a
                    # duplicate chat *reply*, never a second simulated action.
                    for mid, content in list(state.pending_replies.items()):
                        await asyncio.to_thread(post_room_message, config, content)
                        state.pending_replies.pop(mid, None)
                        state.persist()
                    async for raw in sock:
                        frame = json.loads(raw)
                        kind = frame.get("event") or frame.get("type")
                        if kind == "ping":
                            await sock.send(json.dumps({"type": "pong", "cursor": state.cursor}))
                        elif kind == "connection_state":
                            meta = frame.get("data") if isinstance(frame.get("data"), dict) else frame
                            if str(meta.get("agent_id", config.agent_id)) != config.agent_id:
                                raise RuntimeError("Wrong agent_id in connection_state")
                            rooms = meta.get("rooms", [])
                            if config.room_id not in rooms:
                                raise RuntimeError("Switch room not covered by agent connection")
                            state.generation = meta.get("generation")
                            state.cursor = max(state.cursor, int(meta.get("cursor") or 0))
                            state.persist()
                        elif kind == "message":
                            await queue.put(frame)
                        elif kind in {"refused", "evicted"}:
                            code = str(frame.get("code", frame.get("status", "unknown")))
                            if code in {"taken_over", "managed_by_controller", "401", "403", "409"}:
                                raise PermanentSwitchError("Switch refused connection: " + code)
                            raise RuntimeError("Switch refused/evicted connection: " + code)
                        elif kind == "gap":
                            # A data gap invalidates context for further human approvals.
                            raise PermanentSwitchError("Switch history gap requires human resync")
                finally:
                    await queue.put(None)
                    await task
        except KeyboardInterrupt:
            raise
        except PermanentSwitchError:
            raise
        except Exception as exc:
            # Never expose bearer credentials or raw exception details.
            print("Switch disconnected:", type(exc).__name__, file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def main() -> int:
    try:
        config = SwitchConfig.from_env()
    except ValueError as exc:
        print("Not connected:", exc, file=sys.stderr)
        return 2
    asyncio.run(serve(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())