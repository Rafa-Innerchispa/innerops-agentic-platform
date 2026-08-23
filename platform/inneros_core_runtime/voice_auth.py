"""Autenticación multi-usuario para voice gateway — sesiones + perfiles + aprobación."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from pymongo import MongoClient

from raphiia_openai.settings import MONGO_DB, MONGO_URI, RALFIA_OWNER_ID

log = logging.getLogger("ralfia.voice.auth")

COL_VOICE_USERS = "ralfia_voice_users"
SESSION_COOKIE = "ralfia_voice_session"
SESSION_TTL = int(os.getenv("VOICE_SESSION_TTL", str(7 * 86400)))
AUTH_REQUIRED = os.getenv("VOICE_AUTH_REQUIRED", "1").strip().lower() in ("1", "true", "yes")
SESSION_SECRET = os.getenv("VOICE_SESSION_SECRET") or os.getenv("MCP_API_KEY") or "ralfia-voice-dev-change-me"

# Memoria compartida empresa (no privada de Rafael)
SHARED_PRIVACY = ["INTERNAL_WORK", "PROJECT", "PUBLIC"]
ADMIN_USERNAMES = frozenset(
    u.strip().lower()
    for u in os.getenv("VOICE_ADMIN_USERS", "rlopez,admin,rafagye@gmail.com,rafagye").split(",")
    if u.strip()
)

GOOGLE_OAUTH_SCOPES = "openid email profile"
_DEFAULT_OAUTH_REDIRECT = "https://voz.pcdoctor.ai/api/voice/auth/google/callback"


def _normalize_client_secret(raw: str) -> str:
    """Corrige secret pegado dos veces (error común al copiar en panel)."""
    s = (raw or "").strip()
    if len(s) >= 2 and s[: len(s) // 2] == s[len(s) // 2 :]:
        log.warning("GOOGLE_CLIENT_SECRET duplicado detectado — usando mitad válida")
        return s[: len(s) // 2]
    return s


def _oauth_client_id() -> str:
    try:
        from raphiia_openai import config_store

        return (config_store.get("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
    except Exception:
        return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def _oauth_client_secret() -> str:
    try:
        from raphiia_openai import config_store

        return _normalize_client_secret(
            config_store.get("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET", "")
        )
    except Exception:
        return _normalize_client_secret(os.getenv("GOOGLE_CLIENT_SECRET", ""))


def _oauth_redirect_uri() -> str:
    try:
        from raphiia_openai import config_store

        return (
            config_store.get("VOICE_OAUTH_REDIRECT_URI")
            or os.getenv("VOICE_OAUTH_REDIRECT_URI", _DEFAULT_OAUTH_REDIRECT)
        ).strip()
    except Exception:
        return os.getenv("VOICE_OAUTH_REDIRECT_URI", _DEFAULT_OAUTH_REDIRECT).strip()

_client: MongoClient | None = None


def _db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    return _client[MONGO_DB]


def _portal_db():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)["hackathon_autopilot"]


def resolve_username(raw: str) -> str:
    """Normaliza email → usuario portal (rafagye@gmail.com → rafagye)."""
    u = (raw or "").strip()
    if not u:
        return u
    db = _portal_db()
    if db.users.find_one({"username": u}, {"_id": 1}):
        return u
    if "@" in u:
        local = u.split("@")[0].lower()
        if db.users.find_one({"username": local}, {"_id": 1}):
            return local
        if db.users.find_one({"username": u.lower()}, {"_id": 1}):
            return u.lower()
    return u


def verify_portal_credentials(username: str, password: str) -> dict[str, Any] | None:
    raw = (username or "").strip()
    if not raw or not password:
        return None
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    portal = _portal_db()
    candidates: list[str] = []
    resolved = resolve_username(raw)
    if resolved:
        candidates.append(resolved)
    low = raw.lower()
    if low not in candidates:
        candidates.append(low)
    if "@" in raw:
        local = raw.split("@", 1)[0].lower()
        if local not in candidates:
            candidates.append(local)
    for uname in candidates:
        user = portal.users.find_one({"username": uname, "password_hash": pw_hash}, {"_id": 0})
        if user:
            return user
    user = portal.users.find_one({"google_email": low, "password_hash": pw_hash}, {"_id": 0})
    return user


def set_local_password(username: str, password: str, *, allow_admin_bootstrap: bool = False) -> dict[str, Any]:
    """Establece contraseña local (OAuth + login portal pueden coexistir)."""
    uname = resolve_username(username).lower().replace(" ", "")
    if len(password or "") < 4:
        raise ValueError("password_too_short")
    if not uname:
        raise ValueError("username_required")
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    portal = _portal_db()
    existing = portal.users.find_one({"username": uname}, {"_id": 0})
    if not existing and not allow_admin_bootstrap:
        raise ValueError("user_not_found")
    providers = list((existing or {}).get("auth_providers") or [])
    if "local" not in providers:
        providers.append("local")
    portal.users.update_one(
        {"username": uname},
        {
            "$set": {
                "password_hash": pw_hash,
                "local_auth_enabled": True,
                "auth_providers": providers,
            },
            "$setOnInsert": {
                "role": "admin" if uname in ADMIN_USERNAMES else "user",
                "oauth_enabled": True,
                "display_name": uname.split("@")[0].title(),
            },
        },
        upsert=bool(allow_admin_bootstrap and uname in ADMIN_USERNAMES),
    )
    db = _db()
    db[COL_VOICE_USERS].update_one(
        {"username": uname},
        {"$set": {"local_auth_enabled": True, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}},
        upsert=False,
    )
    return {"ok": True, "username": uname}


def request_access(*, username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    """Registro nuevo usuario — queda pending hasta que Rafael apruebe."""
    uname = resolve_username(username).lower().replace(" ", "")
    if not uname or len(uname) < 3:
        raise ValueError("username_too_short")
    if len(password or "") < 4:
        raise ValueError("password_too_short")
    if uname in ADMIN_USERNAMES:
        raise ValueError("use_login")
    portal = _portal_db()
    if portal.users.find_one({"username": uname}, {"_id": 1}):
        raise ValueError("username_exists")
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    portal.users.insert_one(
        {
            "username": uname,
            "password_hash": pw_hash,
            "role": "user",
            "oauth_enabled": True,
            "display_name": (display_name or uname).strip(),
            "auth_providers": ["local"],
            "local_auth_enabled": True,
        }
    )
    db = _db()
    doc = {
        "username": uname,
        "owner_id": uname.upper().replace("@", "_").replace(".", "_")[:48],
        "status": "pending",
        "role": "operator",
        "allowed_privacy": SHARED_PRIVACY,
        "display_name": (display_name or uname).strip(),
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    db[COL_VOICE_USERS].update_one({"username": uname}, {"$set": doc}, upsert=True)
    try:
        from raphiia_openai.voice_notifications import notify_access_request

        notify_access_request(
            username=uname,
            email=username if "@" in username else None,
            display_name=doc.get("display_name"),
            source="register",
        )
    except Exception as exc:
        log.warning("notify_access_request falló para %s: %s", uname, exc)
    return doc


def _owner_id_for(user: dict[str, Any]) -> str:
    uname = str(user.get("username") or "").strip()
    if uname.lower() in ADMIN_USERNAMES or user.get("role") == "admin":
        return RALFIA_OWNER_ID
    return uname.upper().replace("@", "_").replace(".", "_")[:48] or "USER"


def get_voice_profile(username: str) -> dict[str, Any]:
    username = resolve_username(username)
    db = _db()
    doc = db[COL_VOICE_USERS].find_one({"username": username}, {"_id": 0})
    if doc:
        return doc
    user = _portal_db().users.find_one({"username": username}, {"_id": 0}) or {}
    is_admin = username.lower() in ADMIN_USERNAMES or user.get("role") == "admin"
    doc = {
        "username": username,
        "owner_id": _owner_id_for(user or {"username": username}),
        "status": "approved" if is_admin else "pending",
        "role": "admin" if is_admin else str(user.get("role") or "operator"),
        "allowed_privacy": SHARED_PRIVACY + (["PRIVATE_PERSONAL"] if is_admin else []),
        "display_name": str(user.get("display_name") or username.split("@")[0].title()),
    }
    db[COL_VOICE_USERS].insert_one(dict(doc))
    return doc


def approve_user(username: str, *, approved_by: str, role: str = "operator") -> dict[str, Any]:
    db = _db()
    db[COL_VOICE_USERS].update_one(
        {"username": username},
        {
            "$set": {
                "status": "approved",
                "role": role,
                "allowed_privacy": SHARED_PRIVACY,
                "approved_by": approved_by,
                "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        },
        upsert=True,
    )
    profile = get_voice_profile(username)
    try:
        from raphiia_openai.voice_notifications import notify_access_approved

        notify_access_approved(
            username=username,
            email=profile.get("google_email") or profile.get("email"),
            display_name=profile.get("display_name"),
            approved_by=approved_by,
        )
    except Exception as exc:
        log.warning("notify_access_approved falló para %s: %s", username, exc)
    return profile


def list_pending_users(limit: int = 20) -> list[dict[str, Any]]:
    db = _db()
    cur = (
        db[COL_VOICE_USERS]
        .find({"status": "pending"}, {"_id": 0, "username": 1, "display_name": 1, "google_email": 1, "requested_at": 1, "auth_provider": 1})
        .sort("requested_at", -1)
        .limit(max(1, min(limit, 50)))
    )
    return list(cur)


def _sign(payload: str) -> str:
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _unsign(token: str) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if int(data.get("exp") or 0) < int(time.time()):
        return None
    return data


APPROVAL_TOKEN_TTL = int(os.getenv("VOICE_APPROVAL_TOKEN_TTL", str(7 * 86400)))


def create_approval_token(username: str) -> str:
    """Token firmado de un solo uso lógico para aprobar usuario vía link/WhatsApp."""
    username = resolve_username(username)
    payload = json.dumps(
        {
            "kind": "voice_approve",
            "username": username,
            "exp": int(time.time()) + APPROVAL_TOKEN_TTL,
            "nonce": secrets.token_hex(8),
        },
        separators=(",", ":"),
    )
    return _sign(payload)


def verify_approval_token(token: str) -> str | None:
    data = _unsign(token or "")
    if not data or data.get("kind") != "voice_approve":
        return None
    username = str(data.get("username") or "").strip()
    return username or None


def create_session(username: str) -> str:
    username = resolve_username(username)
    profile = get_voice_profile(username)
    if profile.get("status") != "approved":
        raise HTTPException(status_code=403, detail="pending_approval")
    payload = json.dumps(
        {
            "username": username,
            "owner_id": profile.get("owner_id"),
            "role": profile.get("role"),
            "display_name": profile.get("display_name"),
            "allowed_privacy": profile.get("allowed_privacy") or SHARED_PRIVACY,
            "exp": int(time.time()) + SESSION_TTL,
            "sid": secrets.token_hex(8),
        },
        separators=(",", ":"),
    )
    return _sign(payload)


def session_from_request(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE) or ""
    if not token:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return _unsign(token)


def require_user(request: Request) -> dict[str, Any]:
    if not AUTH_REQUIRED:
        return {
            "username": "local",
            "owner_id": RALFIA_OWNER_ID,
            "role": "admin",
            "display_name": "Rafael",
            "allowed_privacy": list(SHARED_PRIVACY) + ["PRIVATE_PERSONAL", "PRIVATE_HEALTH", "PRIVATE_RELATIONSHIPS", "PRIVATE_FAMILY", "PRIVATE_FINANCIAL"],
            "is_admin": True,
        }
    user = session_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="login_required")
    profile = get_voice_profile(str(user.get("username") or ""))
    if profile.get("status") != "approved":
        raise HTTPException(status_code=403, detail="pending_approval")
    user["is_admin"] = str(user.get("role")) == "admin" or str(user.get("owner_id")) == RALFIA_OWNER_ID
    user["allowed_privacy"] = profile.get("allowed_privacy") or SHARED_PRIVACY
    user["display_name"] = profile.get("display_name") or user.get("username")
    return user


def user_public(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": user.get("username"),
        "owner_id": user.get("owner_id"),
        "display_name": user.get("display_name"),
        "role": user.get("role"),
        "is_admin": bool(user.get("is_admin")),
    }


def google_oauth_configured() -> bool:
    return bool(_oauth_client_id() and _oauth_client_secret() and _oauth_redirect_uri())


def new_oauth_state() -> str:
    payload = json.dumps(
        {"exp": int(time.time()) + 600, "nonce": secrets.token_hex(8), "kind": "google"},
        separators=(",", ":"),
    )
    return _sign(payload)


def verify_oauth_state(state: str) -> bool:
    data = _unsign(state or "")
    return bool(data and data.get("kind") == "google")


def google_authorize_url(state: str, *, redirect_uri: str | None = None) -> str:
    params = {
        "client_id": _oauth_client_id(),
        "redirect_uri": (redirect_uri or _oauth_redirect_uri()).strip(),
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_google_code(code: str, *, redirect_uri: str | None = None) -> dict[str, Any]:
    """Intercambia code por tokens y devuelve perfil Google (email, name, sub)."""
    import httpx

    redirect = (redirect_uri or _oauth_redirect_uri()).strip()
    if not _oauth_client_id() or not _oauth_client_secret() or not redirect:
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    token_resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": _oauth_client_id(),
            "client_secret": _oauth_client_secret(),
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    if token_resp.status_code >= 400:
        log.warning("Google token error: %s", token_resp.text[:300])
        raise HTTPException(status_code=400, detail="google_token_failed")
    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="google_token_missing")

    user_resp = httpx.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30.0,
    )
    if user_resp.status_code >= 400:
        raise HTTPException(status_code=400, detail="google_userinfo_failed")
    info = user_resp.json()
    email = str(info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified", True):
        raise HTTPException(status_code=400, detail="google_email_unverified")
    return {
        "email": email,
        "display_name": str(info.get("name") or email.split("@")[0]).strip(),
        "google_sub": str(info.get("sub") or ""),
        "picture": info.get("picture"),
    }


def _is_admin_identity(email: str, username: str) -> bool:
    return email.lower() in ADMIN_USERNAMES or username.lower() in ADMIN_USERNAMES


def ensure_google_access(*, email: str, display_name: str, google_sub: str) -> tuple[dict[str, Any], bool]:
    """Perfil tras login Google. Retorna (profile, notify_sent)."""
    email = email.strip().lower()
    uname = resolve_username(email).lower().replace(" ", "")
    if not uname:
        raise ValueError("invalid_google_user")
    display = (display_name or uname.split("@")[0].title()).strip()
    is_admin = _is_admin_identity(email, uname)

    portal = _portal_db()
    db = _db()
    existing_voice = db[COL_VOICE_USERS].find_one({"username": uname}, {"_id": 0})
    existing_portal = portal.users.find_one({"username": uname}, {"_id": 0})
    is_new = existing_voice is None and existing_portal is None

    if not existing_portal:
        portal.users.insert_one(
            {
                "username": uname,
                "password_hash": hashlib.sha256(secrets.token_hex(32).encode()).hexdigest(),
                "role": "admin" if is_admin else "user",
                "oauth_enabled": True,
                "google_email": email,
                "google_sub": google_sub,
                "display_name": display,
                "auth_provider": "google",
                "auth_providers": ["google"],
                "local_auth_enabled": False,
            }
        )
    else:
        portal.users.update_one(
            {"username": uname},
            {
                "$set": {
                    "google_email": email,
                    "google_sub": google_sub,
                    "display_name": display,
                    "oauth_enabled": True,
                },
                "$addToSet": {"auth_providers": "google"},
            },
        )

    meta = {
        "google_email": email,
        "google_sub": google_sub,
        "display_name": display,
        "auth_provider": "google",
    }

    if is_admin:
        doc = {
            "username": uname,
            "owner_id": RALFIA_OWNER_ID,
            "status": "approved",
            "role": "admin",
            "allowed_privacy": SHARED_PRIVACY + ["PRIVATE_PERSONAL"],
            "approved_by": "google_oauth",
            "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **meta,
        }
        db[COL_VOICE_USERS].update_one({"username": uname}, {"$set": doc}, upsert=True)
        return get_voice_profile(uname), False

    if existing_voice and existing_voice.get("status") == "approved":
        db[COL_VOICE_USERS].update_one({"username": uname}, {"$set": meta})
        return get_voice_profile(uname), False

    doc = {
        "username": uname,
        "owner_id": uname.upper().replace("@", "_").replace(".", "_")[:48],
        "status": "pending",
        "role": "operator",
        "allowed_privacy": SHARED_PRIVACY,
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta,
    }
    db[COL_VOICE_USERS].update_one({"username": uname}, {"$set": doc}, upsert=True)

    notify_sent = False
    if is_new:
        try:
            from raphiia_openai.voice_notifications import notify_access_request

            notify_access_request(
                username=uname,
                email=email,
                display_name=display,
                source="google",
            )
            notify_sent = True
        except Exception as exc:
            log.warning("notify_access_request google falló para %s: %s", uname, exc)
    return get_voice_profile(uname), notify_sent
