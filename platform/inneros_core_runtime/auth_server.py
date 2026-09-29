"""OAuth & OIDC Authorization Server for InnerOS Unified Identity & SSO Plane."""

from __future__ import annotations

import html
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pymongo import MongoClient

from raphiia_openai import oauth_store
from raphiia_openai.oauth_metadata import (
    authorization_server_metadata,
    protected_resource_metadata,
    resolve_oauth_urls,
)
from raphiia_openai.settings import (
    MONGO_URI,
    OAUTH_HOST,
    OAUTH_ISSUER,
    OAUTH_MCP_RESOURCE,
    OAUTH_PORT,
)

SSO_COOKIE_NAME = "inneros_sso_session"

app = FastAPI(title="InnerOS Unified SSO & OAuth", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

ROLE_SCOPES: dict[str, list[str]] = {
    "admin": [
        "openid", "profile", "email", "ralfia:read", "ralfia:write",
        "ralfia:agents", "ralfia:admin", "ralfia:memory:read",
        "ralfia:memory:write", "ralfia:memory:finalize", "ralfia:private_memory",
    ],
    "tech": [
        "openid", "profile", "email", "ralfia:read", "ralfia:write",
        "ralfia:agents", "ralfia:memory:read", "ralfia:memory:write",
    ],
    "user": [
        "openid", "profile", "email", "ralfia:read", "ralfia:write", "ralfia:agents",
    ],
    "viewer": [
        "openid", "profile", "ralfia:read",
    ],
}


def _authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    client = MongoClient(MONGO_URI)
    db = client["hackathon_autopilot"]
    user = db.users.find_one({"username": username})
    if not user:
        return None
    if oauth_store.verify_and_upgrade_password(user, password, db):
        return user
    return None


def _scope_for_user(user: dict[str, Any], requested_scope: str) -> str:
    if user.get("oauth_enabled") is False:
        raise HTTPException(status_code=403, detail="OAuth disabled for this user")
    role = user.get("role", "user")
    allowed = set(ROLE_SCOPES.get(role, ROLE_SCOPES["user"]))
    allowed.update(s for s in (user.get("oauth_scopes") or []) if isinstance(s, str))
    requested = set(oauth_store.parse_scopes(requested_scope))
    granted = sorted(scope for scope in requested if scope in allowed)
    if "ralfia:write" in allowed and "ralfia:write" not in granted:
        granted.append("ralfia:write")
        granted = sorted(set(granted))
    if not granted:
        granted = ["ralfia:read"] if "ralfia:read" in allowed else []
    if not granted:
        raise HTTPException(status_code=403, detail="User has no OAuth scopes")
    return " ".join(granted)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    oauth_store.ensure_indexes()
    issuer, resource = resolve_oauth_urls(request.headers.get("host"))
    return {
        "ok": True,
        "service": "inneros-unified-sso",
        "version": "3.0.0",
        "issuer": issuer,
        "resource": resource,
        "public_issuer": OAUTH_ISSUER,
        "public_resource": OAUTH_MCP_RESOURCE,
    }


@app.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server(request: Request) -> dict[str, Any]:
    return authorization_server_metadata(request.headers.get("host"))


@app.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request) -> dict[str, Any]:
    meta = authorization_server_metadata(request.headers.get("host"))
    meta["id_token_signing_alg_values_supported"] = ["none", "RS256"]
    meta["subject_types_supported"] = ["public"]
    return meta


@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request) -> dict[str, Any]:
    return protected_resource_metadata(request.headers.get("host"))


@app.get("/.well-known/jwks.json")
async def jwks() -> dict[str, Any]:
    return {"keys": []}


@app.post("/register")
async def register_client(request: Request) -> JSONResponse:
    metadata = await request.json()
    try:
        client = oauth_store.create_client(metadata)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = {
        "client_id": client["client_id"],
        "client_id_issued_at": int(oauth_store.now_utc().timestamp()),
        "redirect_uris": client["redirect_uris"],
        "grant_types": client["grant_types"],
        "response_types": client["response_types"],
        "scope": client["scope"],
        "token_endpoint_auth_method": client["token_endpoint_auth_method"],
    }
    if client.get("client_secret"):
        response["client_secret"] = client["client_secret"]
    return JSONResponse(response, status_code=201)


def _authorize_form(params: dict[str, str], issuer: str, active_user: str | None = None, error: str | None = None) -> str:
    hidden = "\n".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v or "")}">'
        for k, v in params.items()
    )
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    client = html.escape(params.get("client_id", ""))
    logged_in_banner = f'<div class="sso-banner">Conectado como <strong>{html.escape(active_user)}</strong></div>' if active_user else ""
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InnerOS Unified SSO</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; background: #0f172a; color: #e5e7eb; }
    main { max-width: 440px; margin: 8vh auto; padding: 32px; background: #111827; border: 1px solid #334155; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); }
    h1 { font-size: 1.4rem; margin-bottom: 0.5rem; text-align: center; color: #38bdf8; }
    .muted { color: #94a3b8; font-size: 0.88rem; margin-bottom: 1.25rem; text-align: center; }
    .sso-banner { background: #1e293b; border: 1px solid #0284c7; padding: 10px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9rem; text-align: center; color: #bae6fd; }
    label { display: block; margin: 12px 0 4px; font-size: 0.88rem; font-weight: 500; }
    input { width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; font-size: 0.95rem; }
    input:focus { outline: none; border-color: #38bdf8; }
    button { width: 100%; margin-top: 20px; padding: 12px; border-radius: 6px; border: none; background: #2563eb; color: #fff; font-weight: 600; font-size: 0.95rem; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    .error { color: #f87171; font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(239, 68, 68, 0.1); border-radius: 4px; }
  </style>
</head>
<body>
  <main>
    <h1>InnerOS Unified SSO</h1>
    <p class="muted">Aplicaci?n: <strong>{client}</strong></p>
    {logged_in_banner}
    {error_html}
    <form method="post" action="{html.escape(issuer)}/authorize">
      {hidden}
      <label for="username">Usuario</label>
      <input id="username" name="username" autocomplete="username" value="{html.escape(active_user or "")}" required>
      <label for="password">Contrase?a</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Iniciar Sesi?n y Autorizar</button>
    </form>
  </main>
</body>
</html>"""


def _validate_authorize_params(params: dict[str, str]) -> tuple[dict[str, Any], str]:
    if params.get("response_type") != "code":
        raise HTTPException(status_code=400, detail="response_type must be code")
    if params.get("code_challenge_method") != "S256":
        raise HTTPException(status_code=400, detail="PKCE S256 required")
    client = oauth_store.get_client(params.get("client_id", ""))
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client_id")
    redirect_uri = params.get("redirect_uri", "")
    if not oauth_store.redirect_uri_allowed(redirect_uri, client.get("redirect_uris")):
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")
    scope = " ".join(oauth_store.parse_scopes(params.get("scope") or client.get("scope")))
    return client, scope


@app.get("/authorize", response_class=HTMLResponse)
async def authorize_get(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str | None = None,
    scope: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    resource: str | None = None,
) -> HTMLResponse:
    params = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state or "",
        "scope": scope or "",
        "code_challenge": code_challenge or "",
        "code_challenge_method": code_challenge_method or "",
        "resource": resource or "",
    }
    _validate_authorize_params(params)
    issuer, _resource = resolve_oauth_urls(request.headers.get("host"))
    session = oauth_store.get_sso_session(request.cookies.get(SSO_COOKIE_NAME))
    active_user = session.get("username") if session else None
    return HTMLResponse(_authorize_form(params, issuer, active_user=active_user))


@app.post("/authorize")
async def authorize_post(
    request: Request,
    response_type: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    scope: str = Form(""),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    resource: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
):
    params = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource,
    }
    _client, default_scope = _validate_authorize_params(params)
    issuer, _resource = resolve_oauth_urls(request.headers.get("host"))
    user = _authenticate_user(username, password)
    if not user:
        return HTMLResponse(
            _authorize_form(params, issuer, error="Credenciales inv?lidas"),
            status_code=401,
        )
    granted_scope = _scope_for_user(user, scope or default_scope)
    code = oauth_store.save_auth_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=granted_scope,
        username=username,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource=resource or None,
    )
    sso_sess = oauth_store.create_sso_session(
        username=username,
        role=user.get("role", "user"),
        display_name=user.get("display_name"),
    )
    query = {"code": code}
    if state:
        query["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    redirect = RedirectResponse(f"{redirect_uri}{sep}{urlencode(query)}", status_code=303)
    redirect.set_cookie(
        key=SSO_COOKIE_NAME,
        value=sso_sess["session_id"],
        max_age=oauth_store.SSO_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return redirect


@app.post("/token")
async def token(
    grant_type: str = Form(...),
    code: str = Form(""),
    refresh_token: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(...),
    code_verifier: str = Form(""),
) -> JSONResponse:
    if not oauth_store.get_client(client_id):
        raise HTTPException(status_code=400, detail="invalid_client")
    if grant_type == "authorization_code":
        code_doc = oauth_store.consume_auth_code(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        if not code_doc:
            raise HTTPException(status_code=400, detail="invalid_grant")
        return JSONResponse(oauth_store.issue_access_token(code_doc))
    if grant_type == "refresh_token":
        token_doc = oauth_store.exchange_refresh_token(refresh_token=refresh_token, client_id=client_id)
        if not token_doc:
            raise HTTPException(status_code=400, detail="invalid_grant")
        return JSONResponse(token_doc)
    raise HTTPException(status_code=400, detail="unsupported_grant_type")


@app.post("/introspect")
async def introspect(token: str = Form(...)) -> JSONResponse:
    info = oauth_store.introspect_token(token)
    return JSONResponse(info)


@app.get("/userinfo")
async def userinfo(request: Request) -> JSONResponse:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token_str = auth_header[7:].strip()
    token_doc = oauth_store.validate_access_token(token_str)
    if not token_doc:
        raise HTTPException(status_code=401, detail="Invalid token")
    username = token_doc.get("username", "")
    client = MongoClient(MONGO_URI)
    db = client["hackathon_autopilot"]
    user = db.users.find_one({"username": username}) or {}
    return JSONResponse({
        "sub": f"user_{username}",
        "preferred_username": username,
        "name": user.get("display_name", username),
        "email": user.get("google_email", f"{username}@pcdoctor.ai"),
        "role": user.get("role", "user"),
        "scopes": (token_doc.get("scope") or "").split(),
    })


@app.get("/session")
async def get_session(request: Request) -> JSONResponse:
    session_id = request.cookies.get(SSO_COOKIE_NAME)
    session = oauth_store.get_sso_session(session_id)
    if not session:
        return JSONResponse({"authenticated": False, "user": None})
    return JSONResponse({
        "authenticated": True,
        "username": session.get("username"),
        "role": session.get("role"),
        "display_name": session.get("display_name"),
    })


@app.post("/logout")
async def logout(request: Request, response: Response) -> JSONResponse:
    session_id = request.cookies.get(SSO_COOKIE_NAME)
    if session_id:
        oauth_store.revoke_sso_session(session_id)
    response.delete_cookie(SSO_COOKIE_NAME)
    return JSONResponse({"ok": True, "message": "Logged out"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=OAUTH_HOST, port=OAUTH_PORT, log_level="info")
