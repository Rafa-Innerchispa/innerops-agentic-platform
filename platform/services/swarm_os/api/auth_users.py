"""Usuarios demo + permisos (modo demostración)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

# Permisos granulares
ALL_PERMS = {
    "clients:read", "clients:write",
    "catalog:read", "catalog:write",
    "inventory:read", "inventory:write",
    "quotes:read", "quotes:write",
    "visits:read", "visits:write",
    "reports:read", "reports:write",
    "chat:use", "voice:use", "settings:write", "users:admin",
}

DEFAULT_USERS = [
    {
        "username": "admin",
        "password": "RalphiAdmin2026",
        "display_name": "Administrador",
        "role": "admin",
        "permissions": list(ALL_PERMS),
    },
    {
        "username": "demo",
        "password": "RalphiDemo2026",
        "display_name": "Usuario demo",
        "role": "demo",
        "permissions": [
            "clients:read", "catalog:read", "inventory:read",
            "quotes:read", "visits:read", "reports:read",
            "chat:use", "voice:use",
        ],
    },
]


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc)


def ensure_users(db) -> None:
    for u in DEFAULT_USERS:
        doc = {
            "username": u["username"],
            "password_hash": _hash(u["password"]),
            "display_name": u["display_name"],
            "role": u["role"],
            "permissions": u["permissions"],
            "active": True,
            "updated_at": _now(),
        }
        db.app_users.update_one({"username": u["username"]}, {"$set": doc}, upsert=True)


def authenticate(db, username: str, password: str) -> dict | None:
    user = db.app_users.find_one({"username": username, "active": True}, {"_id": 0})
    if not user or user.get("password_hash") != _hash(password):
        return None
    token = secrets.token_urlsafe(32)
    db.app_sessions.insert_one({
        "token": token,
        "username": username,
        "created_at": _now(),
        "expires_at": None,
    })
    user.pop("password_hash", None)
    return {"token": token, "user": user}


def get_session_user(db, token: str) -> dict | None:
    if not token:
        return None
    sess = db.app_sessions.find_one({"token": token})
    if not sess:
        return None
    return db.app_users.find_one(
        {"username": sess["username"], "active": True},
        {"_id": 0, "password_hash": 0},
    )


def has_permission(user: dict | None, perm: str) -> bool:
    if not user:
        return True  # modo abierto si no hay login aún
    if user.get("role") == "admin":
        return True
    return perm in (user.get("permissions") or [])
