"""OIDC / service-auth contract for the InnerOS A2A JSON-RPC surface.

Production Google path (LIVE, quota-gated): validate a Google service-account
or workload-identity JWT against JWKS, audience, and issuer.

NON-LIVE harness: HS256 fixture tokens so contracts and middleware can be
tested without Gemini/Vertex quota or a live IdP.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

LIVE_GOOGLE_ISSUERS = (
    "https://accounts.google.com",
    "https://www.googleapis.com/robot/v1/metadata/x509",
)


class A2AOIDCError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def mint_nonlive_service_token(
    *,
    subject: str = "inneros-a2a-service@innerops-agentic-platform.iam.gserviceaccount.com",
    audience: str = "",
    issuer: str = "https://accounts.google.com",
    secret: str = "",
    ttl_seconds: int = 3600,
    now: int | None = None,
) -> str:
    """Mint a NON-LIVE HS256 JWT for local A2A service-auth tests."""
    aud = audience or os.getenv("A2A_OIDC_AUDIENCE") or "inneros-a2a"
    key = secret or os.getenv("A2A_OIDC_HS256_SECRET") or "inneros-nonlive-a2a-oidc"
    issued = int(now if now is not None else time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": "nonlive"}
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": aud,
        "iat": issued,
        "exp": issued + ttl_seconds,
        "email": subject,
        "live_mode": "NON-LIVE",
    }
    signing_input = f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = hmac.new(key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


def verify_service_token(
    token: str,
    *,
    audience: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify an A2A service token.

    NON-LIVE: HS256 with A2A_OIDC_HS256_SECRET.
    LIVE Google JWKS verification is intentionally not claimed here; it is the
    exact remaining live step when Gemini/Vertex quota returns.
    """
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise A2AOIDCError("malformed_jwt", "OIDC bearer token is not a JWT")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise A2AOIDCError("malformed_jwt", "OIDC JWT could not be decoded") from exc

    alg = str(header.get("alg") or "")
    live_requested = os.getenv("A2A_OIDC_LIVE", "").strip().lower() in {"1", "true", "yes"}
    if live_requested and alg != "RS256":
        raise A2AOIDCError(
            "live_oidc_pending",
            "LIVE Google OIDC requires RS256 service-account JWTs; JWKS verification is quota-gated.",
        )
    if alg != "HS256":
        raise A2AOIDCError("unsupported_alg", f"NON-LIVE A2A OIDC only accepts HS256, got {alg}")

    secret = os.getenv("A2A_OIDC_HS256_SECRET") or "inneros-nonlive-a2a-oidc"
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        supplied = _b64url_decode(sig_b64)
    except Exception as exc:
        raise A2AOIDCError("bad_signature", "OIDC signature could not be decoded") from exc
    if not hmac.compare_digest(expected, supplied):
        raise A2AOIDCError("bad_signature", "OIDC signature mismatch")

    aud = audience or os.getenv("A2A_OIDC_AUDIENCE") or "inneros-a2a"
    token_aud = payload.get("aud")
    if isinstance(token_aud, list):
        aud_ok = aud in token_aud
    else:
        aud_ok = str(token_aud or "") == aud
    if not aud_ok:
        raise A2AOIDCError("bad_audience", "OIDC audience mismatch")

    issued_now = int(now if now is not None else time.time())
    exp = int(payload.get("exp") or 0)
    if exp and issued_now >= exp:
        raise A2AOIDCError("expired", "OIDC token expired")

    payload["live_mode"] = "NON-LIVE"
    payload["verified_alg"] = "HS256"
    return payload


def auth_status() -> dict[str, Any]:
    oidc_audience = (os.getenv("A2A_OIDC_AUDIENCE") or "").strip()
    bearer_configured = bool((os.getenv("A2A_SHARED_TOKEN") or "").strip())
    live = os.getenv("A2A_OIDC_LIVE", "").strip().lower() in {"1", "true", "yes"}
    modes = ["loopback"]
    if bearer_configured:
        modes.append("bearer")
    if oidc_audience:
        modes.append("oidc-hs256-nonlive")
    return {
        "ok": True,
        "modes": modes,
        "oidc_audience": oidc_audience or None,
        "live_mode": "LIVE" if live else "NON-LIVE",
        "live_google_jwks_pending": True,
        "live_issuers_pending": list(LIVE_GOOGLE_ISSUERS),
        "note": "Google JWKS/RS256 service-account auth is the remaining LIVE OIDC step.",
    }
