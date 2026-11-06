"""Live Home Assistant bridge for a real physical-light demonstration.

No synthetic device or simulation exists in this runtime path. Only explicit
light.<id> entities can be observed or controlled. Human approval is bound to
an authenticated Switch sender and a single room. This is not a replacement
for HA's own security controls or independent physical sensor confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
from ipaddress import ip_address
import json
import os
import re
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


LIGHT_ID = re.compile(r"^light\.[a-z0-9_]+$")


class LiveHAError(RuntimeError):
    """A live HA request failed; never invent a successful observation."""


def local_ha_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("HA_URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("HA_URL must not include credentials, path or query")
    try:
        host = ip_address(parsed.hostname)
        safe = host.is_private or host.is_loopback
    except ValueError:
        safe = parsed.hostname in {"localhost"} or parsed.hostname.endswith(".local")
    if not safe:
        raise ValueError("Only local Home Assistant addresses are accepted")
    return value.rstrip("/")


class HomeAssistantClient:
    """Direct authenticated HA REST client. Token stays only in process memory."""

    def __init__(self, base_url: str, token: str, timeout: float = 5.0):
        self.base_url = local_ha_url(base_url)
        if not token.strip():
            raise ValueError("HA_TOKEN is required")
        self._token = token
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(self.base_url + path, data=body,
                      method="GET" if body is None else "POST",
                      headers={"Authorization": "Bearer " + self._token,
                               "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                if response.status not in {200, 201}:
                    raise LiveHAError("Unexpected Home Assistant HTTP response")
                return json.load(response)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            # Intentionally do not include host/token/response body in errors.
            raise LiveHAError("Home Assistant live request failed: " + type(exc).__name__) from None

    def ping(self) -> bool:
        data = self._request("/api/")
        return isinstance(data, dict) and data.get("message") == "API running."

    def state(self, entity_id: str) -> dict:
        if not LIGHT_ID.fullmatch(entity_id):
            raise LiveHAError("Entity is not an allowed light")
        raw = self._request("/api/states/" + quote(entity_id, safe=""))
        if not isinstance(raw, dict) or raw.get("entity_id") != entity_id:
            raise LiveHAError("HA returned an unexpected entity")
        value = raw.get("state")
        if value not in {"on", "off"}:
            raise LiveHAError("Light state is unavailable or unknown")
        return {"entity_id": entity_id, "state": value,
                "name": str((raw.get("attributes") or {}).get("friendly_name") or entity_id)[:80],
                "last_updated": str(raw.get("last_updated") or "unknown"),
                "fetched_at": datetime.now(timezone.utc).isoformat()}

    def lights(self, allowed: frozenset[str]) -> list[dict]:
        if not allowed:
            return []
        raw = self._request("/api/states")
        if not isinstance(raw, list):
            raise LiveHAError("Expected an entity list from HA")
        visible = []
        for item in raw:
            if not isinstance(item, dict) or item.get("entity_id") not in allowed:
                continue
            name = str((item.get("attributes") or {}).get("friendly_name") or item["entity_id"])[:80]
            visible.append({"entity_id": item["entity_id"], "name": name,
                            "state": item.get("state"),
                            "fetched_at": datetime.now(timezone.utc).isoformat()})
        return visible

    def turn_light(self, entity_id: str, desired: str) -> None:
        if not LIGHT_ID.fullmatch(entity_id) or desired not in {"on", "off"}:
            raise LiveHAError("Unsupported or unsafe action")
        # Never use toggle or a broad target. Every call acts on one entity.
        self._request("/api/services/light/turn_" + desired, {"entity_id": entity_id})


@dataclass
class LiveRoomPolicy:
    room_id: str
    approver_id: str
    ha: HomeAssistantClient
    allowed_lights: frozenset[str]
    actions_enabled: bool = False
    clock: Callable[[], float] = time.time
    id_factory: Callable[[], str] = lambda: uuid4().hex[:12]
    pending_ttl_seconds: int = 180
    pending: dict | None = None
    processed_messages: set[str] = field(default_factory=set)
    inneros_reader: Callable[[], dict] | None = None

    def handle(self, frame: dict) -> str | None:
        if frame.get("event") != "message":
            return None
        data = frame.get("data") or {}
        payload = data.get("payload") or {}
        if data.get("room_id") != self.room_id or payload.get("addressed") is not True:
            return None
        sender = payload.get("sender")
        body = payload.get("body")
        mid = payload.get("message_id")
        if not all(isinstance(x, str) and x for x in (sender, body, mid)):
            return None
        if mid in self.processed_messages:
            return None
        self.processed_messages.add(mid)
        tokens = body.strip().split()
        while tokens and tokens[0].startswith("@"):
            tokens.pop(0)
        if not tokens:
            return None
        # Voice transcription is ordinary text. Exact entity names are required.
        # This never converts a spoken approval into an authorized action.
        from .voice_input import to_safe_room_command
        tokens = to_safe_room_command(" ".join(tokens)).split()
        cmd = tokens[0].lower()
        try:
            if cmd in {"!lights", "/lights"} and len(tokens) == 1:
                states = self.ha.lights(self.allowed_lights)
                if not states:
                    return "[HA LIVE] No allowlisted light entities found in the current HA registry."
                return "[HA LIVE] " + "; ".join(
                    f"{x['entity_id']}={x['state']} ({x['name']})" for x in states)
            if cmd == "!state" and len(tokens) == 2:
                self._guard_entity(tokens[1])
                value = self.ha.state(tokens[1])
                return (f"[HA LIVE READ] {value['entity_id']}={value['state']}; "
                        f"fetched_at_utc={value['fetched_at']}; HA last_updated={value['last_updated']}")
            if cmd == "!propose" and len(tokens) == 3 and tokens[2].lower() in {"on", "off"}:
                return self._propose(sender, tokens[1], tokens[2].lower())
            if cmd in {"!approve", "!deny"} and len(tokens) == 2:
                return self._decision(sender, cmd, tokens[1])
            if cmd == "!inneros" and len(tokens) == 1:
                if self.inneros_reader is None:
                    return "[INNEROS MCP] Not configured; refusing to claim InnerOS live telemetry."
                try:
                    data = self.inneros_reader()
                except Exception:
                    return "[INNEROS MCP] Live read failed; no data fabricated."
                return (f"[INNEROS LIVE] registered_devices={data['registered_devices']}; "
                        f"observed_at={data['observed_at']}; "
                        f"live_telemetry_verified={data['live_telemetry_verified']}; "
                        f"status_counts={data['status_counts']}")
            if cmd == "!status" and len(tokens) == 1:
                status = "LIVE_HA_WRITES_ENABLED" if self.actions_enabled else "LIVE_HA_READ_ONLY"
                return f"[INNEROS] {status}; allowed_light_count={len(self.allowed_lights)}; pending={bool(self.pending)}"
            return "[HA LIVE] Commands: !inneros, !lights, !state ENTITY, !propose ENTITY on|off, !approve ID, !deny ID, !status."
        except LiveHAError as exc:
            return "[HA LIVE ERROR] " + str(exc) + ". No successful state claimed."

    def _guard_entity(self, entity_id: str) -> None:
        if not LIGHT_ID.fullmatch(entity_id) or entity_id not in self.allowed_lights:
            raise LiveHAError("Entity not in the explicitly allowlisted lights")

    def _propose(self, sender: str, entity: str, desired: str) -> str:
        if not self.actions_enabled:
            return "BLOCKED: live HA actions not enabled; read-only mode."
        if sender != self.approver_id:
            return "BLOCKED: only the configured human operator can propose an action."
        self._guard_entity(entity)
        if self.pending:
            return "BLOCKED: another proposal is awaiting a decision."
        current = self.ha.state(entity)
        if current["state"] == desired:
            return f"[HA LIVE] {entity} is already {desired}; no mutation required."
        action_id = "HA-" + self.id_factory()
        self.pending = {"id": action_id, "entity": entity,
                        "before": current["state"], "desired": desired,
                        "expires": self.clock() + self.pending_ttl_seconds}
        return (f"[INNEROS APPROVAL REQUIRED] LIVE action={action_id}; entity={entity}; "
                f"current={current['state']}; requested={desired}; "
                f"expires_in={self.pending_ttl_seconds}s. Human: !approve {action_id} or !deny {action_id}.")

    def _decision(self, sender: str, cmd: str, action_id: str) -> str:
        if not compare_digest(sender, self.approver_id):
            return "BLOCKED: sender is not the authorized Switch operator."
        p = self.pending
        if p is None or not compare_digest(action_id, p["id"]):
            return "BLOCKED: no matching pending action."
        if self.clock() > p["expires"]:
            self.pending = None
            return "BLOCKED: approval expired; propose again."
        self.pending = None  # single-use; a replay cannot change the device again
        if cmd == "!deny":
            return f"[INNEROS DENIED] {action_id}. No Home Assistant service called."
        self._guard_entity(p["entity"])
        before = self.ha.state(p["entity"])
        # Recover from an interrupted response without repeating an already completed action.
        if before["state"] == p["desired"]:
            return "[HA LIVE] Requested state already observed; no second service call."
        if before["state"] != p["before"]:
            return "BLOCKED: device state changed since proposal; approval invalidated."
        self.ha.turn_light(p["entity"], p["desired"])
        after = None
        for _ in range(4):
            try:
                after = self.ha.state(p["entity"])
            except LiveHAError:
                pass
            if after and after["state"] == p["desired"]:
                break
            time.sleep(.3)
        verified = after is not None and after["state"] == p["desired"]
        receipt = {"source": "home_assistant_live", "entity": p["entity"],
                   "action_id": action_id, "operator_id": sender,
                   "before": p["before"], "desired": p["desired"],
                   "observed_after": after["state"] if after else "UNAVAILABLE",
                   "verified_by_new_read": bool(verified),
                   "completed_at_utc": datetime.now(timezone.utc).isoformat()}
        digest = sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return (f"[HA LIVE {'VERIFIED' if verified else 'UNVERIFIED'}] "
                f"{p['entity']}: {p['before']} -> {receipt['observed_after']}; "
                f"requested={p['desired']}; operator_verified=True; "
                f"readback_verified={verified}; sha256={digest}; "
                "this is an HA state readback, not an independent physical sensor or signature.")

    def snapshot(self) -> dict:
        return {"pending": self.pending,
                "processed_messages": sorted(self.processed_messages)[-1500:]}

    def restore(self, raw: dict) -> None:
        if not isinstance(raw, dict):
            return
        self.processed_messages = set(str(x) for x in raw.get("processed_messages", [])[-1500:])
        p = raw.get("pending")
        self.pending = None
        if isinstance(p, dict):
            try:
                if (p["entity"] in self.allowed_lights
                        and LIGHT_ID.fullmatch(p["entity"])
                        and p["before"] in {"on", "off"}
                        and p["desired"] in {"on", "off"}
                        and float(p["expires"]) >= self.clock()):
                    self.pending = {"id": str(p["id"]), "entity": p["entity"],
                                    "before": p["before"], "desired": p["desired"],
                                    "expires": float(p["expires"])}
            except (KeyError, ValueError, TypeError):
                pass


def policy_from_env(room_id: str, approver_id: str) -> LiveRoomPolicy:
    allowed = frozenset(x.strip() for x in os.getenv("HA_ALLOWED_LIGHTS", "").split(",") if x.strip())
    if not allowed or not all(LIGHT_ID.fullmatch(x) for x in allowed):
        raise ValueError("HA_ALLOWED_LIGHTS must name at least one explicit light.<id> entity")
    url = os.getenv("HA_URL", "")
    token = os.getenv("HA_TOKEN", "")
    reader = None
    mcp_url = os.getenv("INNEROS_MCP_URL", "")
    mcp_token = os.getenv("INNEROS_MCP_TOKEN", "")
    if bool(mcp_url) != bool(mcp_token):
        raise ValueError("INNEROS_MCP_URL and INNEROS_MCP_TOKEN must be set together")
    if mcp_url:
        from .inneros_live import InnerOSLiveReader
        reader = InnerOSLiveReader(mcp_url, mcp_token).read_summary
    return LiveRoomPolicy(room_id, approver_id, HomeAssistantClient(url, token),
                          allowed, actions_enabled=os.getenv("HA_ENABLE_REAL_ACTIONS") == "YES",
                          inneros_reader=reader)