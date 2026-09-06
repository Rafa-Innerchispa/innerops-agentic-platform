"""Stable actor identities for the shared InnerOS coordination bus."""

from __future__ import annotations

import re
from typing import Any


CANONICAL_MAILBOXES = frozenset(
    {
        "antigravity",
        "chatgpt",
        "chatgpt_a",
        "chatgpt_b",
        "codex",
        "cursor",
        "dev_swarm",
        "gemini",
        "notion",
        "rafael",
        "ralfia",
    }
)

ALIASES = {
    "chatgpta": "chatgpt_a",
    "chatgpt-a": "chatgpt_a",
    "chatgpt_a": "chatgpt_a",
    "chatgptb": "chatgpt_b",
    "chatgpt-b": "chatgpt_b",
    "chatgpt_b": "chatgpt_b",
    "anti-gravity": "antigravity",
    "anti_gravity": "antigravity",
    "google-antigravity": "antigravity",
    "cursor-ide": "cursor",
    "codex-cli": "codex",
    "devswarm": "dev_swarm",
    "dev-swarm": "dev_swarm",
}


def _slug(value: str, *, default: str = "") -> str:
    text = re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_.-")
    return text or default


def canonical_mailbox(value: str, *, default: str = "chatgpt") -> str:
    key = _slug(value, default=default).replace("_", "-")
    normalized = ALIASES.get(key) or ALIASES.get(key.replace("-", "_")) or key.replace("-", "_")
    if normalized in CANONICAL_MAILBOXES:
        return normalized
    base = normalized.split("_", 1)[0]
    if base in CANONICAL_MAILBOXES:
        return base
    return _slug(default, default="chatgpt")


def normalize_actor(
    agent: str,
    *,
    account: str | None = None,
    host: str | None = None,
    lane: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    mailbox = canonical_mailbox(agent)
    raw_agent = str(agent or "").strip() or mailbox
    account_n = _slug(account or "")
    host_n = _slug(host or "")
    lane_n = _slug(lane or "")
    parts = [mailbox]
    if account_n:
        parts.append(account_n)
    if host_n:
        parts.append(host_n)
    if lane_n:
        parts.append(lane_n)
    instance_id = "_".join(parts)
    return {
        "actor_id": instance_id,
        "mailbox": mailbox,
        "raw_agent": raw_agent,
        "display": raw_agent,
        "account": account_n or None,
        "host": host_n or None,
        "lane": lane_n or None,
        "role": _slug(role or "") or None,
    }


def identity_from_payload(agent: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    identity = payload.get("actor_identity") if isinstance(payload.get("actor_identity"), dict) else {}
    return normalize_actor(
        agent,
        account=identity.get("account") or payload.get("actor_account") or payload.get("account"),
        host=identity.get("host") or payload.get("actor_host") or payload.get("host"),
        lane=identity.get("lane") or payload.get("actor_lane") or payload.get("lane"),
        role=identity.get("role") or payload.get("actor_role") or payload.get("role"),
    )

