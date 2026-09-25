"""InnerOS Unified Auth Middleware ? Canonical Authentication Gateway for Panels."""

from __future__ import annotations

from typing import Any, Callable
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from inneros_core_runtime import oauth_store

SSO_COOKIE_NAME = "inneros_sso_session"


async def get_current_user(request: Request) -> dict[str, Any]:
    # 1. Try Bearer Token in Header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        doc = oauth_store.validate_access_token(token)
        if doc:
            return {
                "username": doc.get("username"),
                "role": "admin" if "ralfia:admin" in (doc.get("scope") or "") else "user",
                "auth_type": "bearer_token",
                "scopes": (doc.get("scope") or "").split(),
            }

    # 2. Try Central SSO Session Cookie
    session_id = request.cookies.get(SSO_COOKIE_NAME)
    if session_id:
        sso_doc = oauth_store.get_sso_session(session_id)
        if sso_doc:
            return {
                "username": sso_doc.get("username"),
                "role": sso_doc.get("role", "user"),
                "auth_type": "sso_session",
                "display_name": sso_doc.get("display_name"),
            }

    raise HTTPException(status_code=401, detail="Authentication required")


def require_role(allowed_roles: list[str]) -> Callable:
    async def _role_checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("role") not in allowed_roles and user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return user
    return _role_checker
