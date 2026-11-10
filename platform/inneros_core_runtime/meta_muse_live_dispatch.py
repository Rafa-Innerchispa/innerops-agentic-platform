"""Fail-closed Meta Muse live-call adapter for the governed InnerOS gateway.

This module deliberately does not register or bypass an MCP capability. The host
must use a trusted, atomic grant store and secret resolver when wiring it in.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Any

API_URL = "https://api.meta.ai/v1/responses"
SUPPORTED_MODELS = ("muse-wonder-1.0", "muse-spark-1.3")
DEFAULT_MODEL = "muse-wonder-1.0"
MODEL = DEFAULT_MODEL


class MuseDispatchError(RuntimeError):
    """Public-safe error (never includes credentials or provider response body)."""


@dataclass(frozen=True)
class MuseGrant:
    grant_id: str
    project_id: str
    provider: str
    model: str
    expires_at: datetime
    max_output_tokens: int
    max_prompt_chars: int
    max_cost_usd: float
    owner_approved: bool
    billing_hard_limit_verified: bool
    prompt_sha256: str = ""


class TrustedGrantStore(Protocol):
    def redeem_once(self, grant_id: str) -> MuseGrant:
        """Atomically consume a validated grant; reject missing/used grants."""


def _output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    fragments: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                fragments.append(str(part.get("text", "")))
    return "".join(fragments)


def invoke_muse(
    *,
    prompt: str,
    grant_id: str,
    grant_store: TrustedGrantStore,
    resolve_api_key: Callable[[], str],
    requested_output_tokens: int = 128,
    timeout_seconds: int = 45,
    transport: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Invoke exactly one Meta response; no retries or production write tools.

    Secrets must be supplied by the server-side Vault resolver. A trusted grant
    store must atomically redeem a single-use, owner-approved grant. Billing
    limits must be enforced outside this adapter at the Meta account level;
    a prompt or max_output_tokens alone is not a dollar-denominated hard cap.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 6000:
        raise MuseDispatchError("invalid_prompt")
    if not isinstance(grant_id, str) or not grant_id:
        raise MuseDispatchError("missing_grant")
    if not isinstance(requested_output_tokens, int) or not 1 <= requested_output_tokens <= 2048:
        raise MuseDispatchError("invalid_output_limit")
    if not 1 <= timeout_seconds <= 120:
        raise MuseDispatchError("invalid_timeout")

    # Validation and atomic consumption are responsibility of trusted store.
    # Never accept a raw authorization dictionary from an end-user request.
    try:
        grant = grant_store.redeem_once(grant_id)
    except Exception as exc:
        raise MuseDispatchError("grant_unavailable_or_consumed") from None

    now = datetime.now(timezone.utc)
    if (
        not isinstance(grant, MuseGrant)
        or not grant.owner_approved
        or not grant.billing_hard_limit_verified
        or not grant.project_id
        or grant.provider != "meta"
        or (grant.model != MODEL and grant.model not in SUPPORTED_MODELS)
        or grant.max_cost_usd <= 0
        or grant.max_prompt_chars < len(prompt)
        or requested_output_tokens > grant.max_output_tokens
        or grant.expires_at.tzinfo is None
        or grant.expires_at <= now
    ):
        raise MuseDispatchError("grant_policy_denied")

    if grant.prompt_sha256:
        import hashlib
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if prompt_sha != grant.prompt_sha256:
            raise MuseDispatchError("prompt_hash_mismatch")

    key = resolve_api_key()
    if not isinstance(key, str) or not key.strip():
        raise MuseDispatchError("meta_credential_unavailable")
    target_model = grant.model or MODEL
    payload = {
        "model": target_model,
        "input": prompt,
        "max_output_tokens": requested_output_tokens,
    }
    req = urllib.request.Request(
        API_URL,
        method="POST",
        headers={
            "Authorization": "Bearer " + key.strip(),
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with (transport or urllib.request.urlopen)(req, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as exc:
        raise MuseDispatchError("meta_http_" + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise MuseDispatchError("meta_connection_failed") from None
    if len(raw) > 1_000_000:
        raise MuseDispatchError("meta_response_oversized")
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        raise MuseDispatchError("meta_response_invalid") from None
    if not isinstance(result, dict) or result.get("error"):
        raise MuseDispatchError("meta_response_error")
    return {
        "status": result.get("status", "unknown"),
        "response_id": result.get("id"),
        "model": result.get("model", target_model),
        "output_text": _output_text(result),
        "usage": result.get("usage", {}),
        "grant_id": grant.grant_id,
        "project_id": grant.project_id,
        "provider": "meta",
    }
