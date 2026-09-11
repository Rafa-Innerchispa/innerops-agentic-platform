"""Reusable AssemblyAI provider for InnerOS Resource Fabric.

The provider owns AssemblyAI authentication and protocol calls. Product modules
such as VoiceOps, Physical Guardian and Workforce consume capabilities; they do
not own or persist the API credential.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from raphiia_openai import owner_vault

PROVIDER_ID = "assemblyai"
LABEL = "AssemblyAI Voice AI"
VAULT_CATEGORY = "voice_ai_provider"
VAULT_KEY = "assemblyai_api_key"
REST_BASE = "https://api.assemblyai.com"
TOKEN_URL = "https://agents.assemblyai.com/v1/token"
VOICE_AGENT_WS = "wss://agents.assemblyai.com/v1/ws"
STREAMING_WS = "wss://streaming.assemblyai.com/v3/ws"
LLM_GATEWAY = "https://llm-gateway.assemblyai.com/v1/chat/completions"
CAPABILITIES = [
    "voice_note_stt",
    "realtime_stt",
    "voice_agent_session",
    "tts",
    "semantic_turn_detection",
    "barge_in",
    "tool_calling",
    "session_resume",
    "keyterms",
    "agent_context",
    "entity_detection",
    "pii_redaction",
    "content_moderation",
    "llm_gateway",
]


def manifest_document() -> dict[str, Any]:
    return {
        "id": PROVIDER_ID,
        "label": LABEL,
        "endpoints": [VOICE_AGENT_WS, STREAMING_WS, REST_BASE, LLM_GATEWAY],
        "cli": "",
        "sdk": "",
        "auth_mode": "owner_vault",
        "secret_category": VAULT_CATEGORY,
        "scopes": [],
        "capabilities": ["status", "preflight", "dry_run", "audit", *CAPABILITIES],
        "risk_level": "moderate_write",
        "allowed_resources": [
            "voice_agent_sessions",
            "streaming_transcription",
            "speech_synthesis",
            "speech_understanding",
            "guardrails",
            "llm_gateway",
        ],
        "allowed_domains": [
            "agents.assemblyai.com",
            "streaming.assemblyai.com",
            "api.assemblyai.com",
            "llm-gateway.assemblyai.com",
        ],
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
        "cost_policy": "external_voice_provider_explicit_or_policy_routed",
        "governance": "server-side credential; capability routing; approval/evidence handled by consuming workflow",
    }


def store_api_key_server_side(secret: str, actor: str = "RAFAEL") -> dict[str, Any]:
    """Store or rotate the provider credential without returning the raw value."""
    result = owner_vault.save_owner_credential(
        key=VAULT_KEY,
        secret=secret,
        category=VAULT_CATEGORY,
        label="AssemblyAI API key",
        metadata={"provider_id": PROVIDER_ID, "usage": "InnerOS reusable voice provider"},
        actor=actor,
    )
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "credential_ref": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}",
        "vault_id": result.get("vault_id"),
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
        "endpoints": {
            "voice_agent": VOICE_AGENT_WS,
            "streaming": STREAMING_WS,
            "rest": REST_BASE,
            "llm_gateway": LLM_GATEWAY,
        },
        "raw_secret_exposed": False,
    }


def provider_preflight(live: bool = False, timeout_seconds: float = 8.0) -> dict[str, Any]:
    status = provider_status()
    checks: dict[str, Any] = {
        "credential_configured": status["configured"],
        "secret_server_side": True,
        "manifest_capabilities": len(CAPABILITIES),
    }
    if not live:
        return {"ok": bool(status["configured"]), "provider_id": PROVIDER_ID, "live": False, "checks": checks}
    if not status["configured"]:
        return {"ok": False, "provider_id": PROVIDER_ID, "live": True, "checks": checks, "error": "credential_not_configured"}
    try:
        token = _mint_temporary_token(60, timeout_seconds=timeout_seconds)
        checks["temporary_token_mint"] = bool(token)
        return {"ok": bool(token), "provider_id": PROVIDER_ID, "live": True, "checks": checks}
    except Exception as exc:
        return {
            "ok": False,
            "provider_id": PROVIDER_ID,
            "live": True,
            "checks": checks,
            "error": type(exc).__name__,
            "message": str(exc)[:240],
        }


def create_browser_token(expires_in_seconds: int = 120, timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Mint a short-lived browser token. The permanent API key never leaves the provider."""
    ttl = max(1, min(int(expires_in_seconds), 600))
    token = _mint_temporary_token(ttl, timeout_seconds=timeout_seconds)
    return {"ok": True, "provider_id": PROVIDER_ID, "token": token, "expires_in_seconds": ttl}


def transcribe_audio_url(
    audio_url: str,
    language_code: str = "es",
    keyterms: list[str] | None = None,
    enable_guardrails: bool = True,
    redact_audio: bool = False,
    timeout_seconds: int = 75,
) -> dict[str, Any]:
    """Transcribe a remote audio asset and optionally apply post-session guardrails.

    This is intended for channels such as WhatsApp voice notes. The audio URL is
    never returned in the result so signed media URLs are not copied into audit
    evidence by default.
    """
    if not str(audio_url or "").startswith(("https://", "http://")):
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "audio_url_required"}
    payload: dict[str, Any] = {
        "audio_url": audio_url,
        "speech_models": ["universal-3-pro", "universal-2"],
        "language_code": language_code or "es",
    }
    if keyterms:
        payload["keyterms_prompt"] = [str(term)[:50] for term in keyterms if str(term).strip()][:100]
    if enable_guardrails:
        payload.update(
            {
                "redact_pii": True,
                "redact_pii_policies": ["person_name", "phone_number", "email_address"],
                "redact_pii_sub": "entity_name",
                "entity_detection": True,
                "content_safety": True,
            }
        )
        if redact_audio:
            payload["redact_pii_audio"] = True
            payload["redact_pii_audio_quality"] = "mp3"

    api_key = _api_key()
    created = _json_request(
        REST_BASE + "/v2/transcript",
        method="POST",
        api_key=api_key,
        payload=payload,
        timeout=10.0,
    )
    transcript_id = str(created.get("id") or "")
    if not transcript_id:
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "transcript_id_missing"}

    deadline = time.monotonic() + max(5, min(int(timeout_seconds), 180))
    result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = _json_request(
            REST_BASE + "/v2/transcript/" + parse.quote(transcript_id),
            method="GET",
            api_key=api_key,
            timeout=10.0,
        )
        state = str(result.get("status") or "")
        if state == "completed":
            break
        if state == "error":
            return {
                "ok": False,
                "provider_id": PROVIDER_ID,
                "transcript_id": transcript_id,
                "error": "transcription_failed",
                "message": str(result.get("error") or "")[:300],
            }
        time.sleep(1.0)
    else:
        return {"ok": False, "provider_id": PROVIDER_ID, "transcript_id": transcript_id, "error": "transcription_timeout"}

    entities = []
    for item in result.get("entities") or []:
        if isinstance(item, dict):
            entities.append({k: item.get(k) for k in ("entity_type", "text", "start", "end") if k in item})
    safety = result.get("content_safety_labels") or result.get("content_safety") or {}
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "transcript_id": transcript_id,
        "text": str(result.get("text") or "")[:12000],
        "confidence": result.get("confidence"),
        "entities": entities[:100],
        "content_safety": safety,
        "pii_redaction_enabled": bool(enable_guardrails),
        "redacted_audio_url_present": bool(result.get("redacted_audio_url")),
        "audio_url_exposed": False,
    }


def transcribe_audio_file(
    path: str,
    language_code: str = "es",
    keyterms: list[str] | None = None,
    enable_guardrails: bool = True,
    redact_audio: bool = False,
    timeout_seconds: int = 75,
) -> dict[str, Any]:
    """Upload a local audio file and transcribe it without exposing provider URLs."""
    target = Path(path)
    if not target.is_file():
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "audio_file_not_found"}
    size = target.stat().st_size
    if size <= 0:
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "audio_file_empty"}
    if size > 25 * 1024 * 1024:
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "audio_file_too_large"}

    uploaded = _binary_request(
        REST_BASE + "/v2/upload",
        api_key=_api_key(),
        data=target.read_bytes(),
        timeout=30.0,
    )
    upload_url = str(uploaded.get("upload_url") or "")
    if not upload_url:
        return {"ok": False, "provider_id": PROVIDER_ID, "error": "upload_url_missing"}
    result = transcribe_audio_url(
        upload_url,
        language_code=language_code,
        keyterms=keyterms,
        enable_guardrails=enable_guardrails,
        redact_audio=redact_audio,
        timeout_seconds=timeout_seconds,
    )
    result["source"] = "local_audio_file"
    result["upload_url_exposed"] = False
    return result


def _credential_metadata() -> dict[str, Any]:
    return owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=False, actor="RAFAEL")


def _api_key() -> str:
    credential = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True, actor="RAFAEL")
    secret = str(credential.get("secret") or "") if credential.get("ok") else ""
    if not secret:
        raise RuntimeError("assemblyai_credential_not_configured")
    return secret


def _mint_temporary_token(expires_in_seconds: int, timeout_seconds: float = 8.0) -> str:
    api_key = _api_key()
    url = TOKEN_URL + "?" + parse.urlencode({"expires_in_seconds": max(1, min(int(expires_in_seconds), 600))})
    data = _json_request(url, method="GET", api_key=api_key, timeout=timeout_seconds)
    token = str(data.get("token") or "")
    if not token:
        raise RuntimeError("assemblyai_temporary_token_missing")
    return token


def _json_request(
    url: str,
    *,
    method: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed provider domains
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"assemblyai_http_{exc.code}: {detail}") from exc
    return json.loads(raw or "{}")


def _binary_request(url: str, *, api_key: str, data: bytes, timeout: float = 30.0) -> dict[str, Any]:
    req = request.Request(url, data=data, headers={"Authorization": api_key}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed provider domain
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"assemblyai_http_{exc.code}: {detail}") from exc
    return json.loads(raw or "{}")
