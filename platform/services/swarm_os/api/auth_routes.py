"""Login demo / admin."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from api.auth_users import authenticate, get_session_user, has_permission

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _db():
    from tools.mongo import get_db

    return get_db()


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn):
    from api.auth_users import ensure_users

    db = _db()
    ensure_users(db)
    result = authenticate(db, body.username.strip(), body.password)
    if not result:
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    return result


@router.get("/auth/me")
def me(authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return {"user": None, "mode": "open"}
    user = get_session_user(_db(), authorization[7:].strip())
    if not user:
        raise HTTPException(401, "Sesión inválida")
    return {"user": user, "mode": "authenticated"}


@router.get("/auth/permissions")
def permissions(authorization: str | None = Header(None)):
    user = None
    if authorization and authorization.startswith("Bearer "):
        user = get_session_user(_db(), authorization[7:].strip())
    return {
        "can_write_clients": has_permission(user, "clients:write"),
        "can_write_catalog": has_permission(user, "catalog:write"),
        "can_use_voice": has_permission(user, "voice:use"),
        "can_admin": has_permission(user, "users:admin"),
    }
