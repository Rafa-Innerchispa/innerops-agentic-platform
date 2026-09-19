"""Reusable Boson Higgs provider for InnerOS Resource Fabric.

The provider owns Boson authentication and realtime client-secret minting.
Product projects request voice capabilities through Resource Fabric instead of
copying permanent Boson API keys into project-specific environments.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

from raphiia_openai import owner_vault

PROVIDER_ID = "boson-higgs"
LABEL = "Boson AI Higgs Realtime"
VAULT_CATEGORY = "voice_ai_provider"
VAULT_KEY = "boson_api_key"
API_BASE = "https://api.boson.ai/v1"
CLIENT_SECRETS_URL = API_BASE + "/realtime/client_secrets"
REALTIME_WS = "wss://api.boson.ai/v1/realtime"
MODEL = "higgs-realtime"
CAPABILITIES = [
    "realtime_s2s",
    "realtime_stt",
    "tts",
    "voice_agent_session",
    "barge_in",
    "tool_calling",
    "multilingual_voice",
    "realtime_client_secret",
]


def manifest_document() -> dict[str, Any]:
    return {
        "id": PROVIDER_ID,
        "label": LABEL,
        "endpoints": [CLIENT_SECRETS_URL, REALTIME_WS],
        "cli": "",
        "sdk": "",
        "auth_mode": "owner_vault",
        "secret_category": VAULT_CATEGORY,
        "scopes": [],
        "capabilities": ["status", "preflight", "dry_run", "audit", *CAPABILITIES],
        "risk_level": "moderate_write",
        "allowed_resources": ["realtime_voice_sessions", "realtime_client_secrets"],
        "allowed_domains": ["api.boson.ai"],
        "rate_limits": {"session_starts_per_minute": 10, "api_requests_per_minute": 60},
    }


def resource_provider_document() -> dict[str, Any]:
    configured = _credential_metadata().get("ok") is True
    return {
        "provider_id": PROVIDER_ID,
        "label": LABEL,
        "kind": "external_voice_provider",
        "capabilities": list(CAPABILITIES),
        "local_first": False,
        "status": "active" if configured else "configured_needs_credential",
        "auth_mode": "owner_vault",
        "credential_ref": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}",
        "cost_policy": "external_voice_provider_credit_governed",
        "funding_provider": "Boson AI",
        "credit_governor": "AG-54_FUNDING_CREDITS",
        "governance": "server-side permanent credential; short-lived realtime client secrets; funding tracked by AG-54; consuming workflow owns approval/evidence gates",
    }


def store_api_key_server_side(secret: str, actor: str = "RAFAEL") -> dict[str, Any]:
    """Store or rotate the permanent Boson key without returning the raw value."""
    value = str(secret or "").strip()
    if not value:
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "boson_api_key_required"}
    result = owner_vault.save_owner_credential(
        key=VAULT_KEY,
        secret=value,
        category=VAULT_CATEGORY,
        label="Boson AI API key",
        metadata={
            "provider_id": PROVIDER_ID,
            "usage": "InnerOS reusable Higgs Realtime voice provider",
            "funding_provider": "Boson AI",
        },
        actor=actor,
    )
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "credential_ref": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}",
        "vault_id": result.get("vault_id"),
        "raw_secret_exposed": False,
    }


def provider_status() -> dict[str, Any]:
    credential = _credential_metadata()
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "label": LABEL,
        "configured": credential.get("ok") is True,
        "credential_ref": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}",
        "capabilities": list(CAPABILITIES),
        "model": MODEL,
        "endpoints": {"client_secrets": CLIENT_SECRETS_URL, "realtime": REALTIME_WS},
        "funding_provider": "Boson AI",
        "credit_governor": "AG-54_FUNDING_CREDITS",
        "raw_secret_exposed": False,
    }


def provider_preflight(live: bool = False, timeout_seconds: float = 8.0) -> dict[str, Any]:
    status = provider_status()
    checks: dict[str, Any] = {
        "credential_configured": status["configured"],
        "secret_server_side": True,
        "manifest_capabilities": len(CAPABILITIES),
        "funding_governor": "AG-54_FUNDING_CREDITS",
    }
    if not live:
        return {"ok": bool(status["configured"]), "provider_id": PROVIDER_ID, "live": False, "checks": checks}
    if not status["configured"]:
        return {"ok": False, "provider_id": PROVIDER_ID, "live": True, "checks": checks, "error": "credential_not_configured"}
    try:
        secret = _mint_client_secret(30, timeout_seconds=timeout_seconds)
        checks["realtime_client_secret_mint"] = bool(secret)
        return {"ok": bool(secret), "provider_id": PROVIDER_ID, "live": True, "checks": checks}
    except Exception as exc:
        return {
            "ok": False,
            "provider_id": PROVIDER_ID,
            "live": True,
            "checks": checks,
            "error": type(exc).__name__,
            "message": str(exc)[:240],
        }


def create_realtime_client_secret(expires_in_seconds: int = 120, timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Mint a short-lived Realtime credential for a consuming project/session."""
    ttl = max(10, min(int(expires_in_seconds), 7200))
    token = _mint_client_secret(ttl, timeout_seconds=timeout_seconds)
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "token": token,
        "expires_in_seconds": ttl,
        "ws_url": REALTIME_WS,
        "model": MODEL,
        "subprotocol_prefix": "bai-client-secret.",
        "permanent_secret_exposed": False,
    }


def _credential_metadata() -> dict[str, Any]:
    return owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=False, actor="RAFAEL")


def _api_key() -> str:
    credential = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True, actor="RAFAEL")
    secret = str(credential.get("secret") or "") if credential.get("ok") else ""
    if not secret:
        raise RuntimeError("boson_credential_not_configured")
    return secret


def _mint_client_secret(expires_in_seconds: int, timeout_seconds: float = 8.0) -> str:
    payload = json.dumps({"expires_after": {"seconds": max(10, min(int(expires_in_seconds), 7200))}}).encode("utf-8")
    req = request.Request(
        CLIENT_SECRETS_URL,
        data=payload,
        headers={"Authorization": "Bearer " + _api_key(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - fixed Boson provider domain
            data = json.loads(response.read().decode("utf-8") or "{}")
    except error.HTTPError as exc:
        raise RuntimeError(f"boson_http_{exc.code}") from exc
    value = data.get("value") or (data.get("client_secret") or {}).get("value")
    if not value:
        raise RuntimeError("boson_realtime_client_secret_missing")
    return str(value)
