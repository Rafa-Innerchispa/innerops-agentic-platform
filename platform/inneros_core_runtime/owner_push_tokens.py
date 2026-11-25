"""Tokens HMAC para enlaces de aprobación OPS (ntfy actions / PWA)."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any


def _secret() -> bytes:
    raw = (os.getenv("INNEROS_OWNER_PUSH_SECRET") or os.getenv("MCP_API_KEY") or "").strip()
    if not raw:
        raw = "inneros-owner-push-dev-only-change-me"
    return raw.encode()


def sign_decision(*, task_id: str, nonce: str, decision: str) -> str:
    msg = f"{task_id}|{nonce}|{decision}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]


def verify_decision(*, task_id: str, nonce: str, decision: str, token: str) -> bool:
    if not token:
        return False
    expected = sign_decision(task_id=task_id, nonce=nonce, decision=decision)
    return hmac.compare_digest(expected, token.strip())


def public_base_url() -> str:
    import os

    return (
        os.getenv("INNEROS_OWNER_PUSH_PUBLIC_URL")
        or os.getenv("OPS_PANEL_PUBLIC_URL")
        or "http://192.168.1.4:8244"
    ).rstrip("/")