"""OAuth authorization server for ChatGPT MCP access to RalfIA."""

from __future__ import annotations

import hashlib
import html
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
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

app = FastAPI(title="RalfIA OAuth", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chatgpt.com", "https://chat.openai.com"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    oauth_store.ensure_indexes()
    issuer, resource = resolve_oauth_urls(request.headers.get("host"))
    return {
        "ok": True,
        "service": "ralfia-auth",
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
    return authorization_server_metadata(request.headers.get("host"))


@app.get("/.well-known/oauth-protected-resource")
async def protected_resource(request: Request) -> dict[str, Any]:
    return protected_resource_metadata(request.headers.get("host"))


@app.on_event("startup")
async def _startup() -> None:
    oauth_store.ensure_indexes()


ROLE_SCOPES = {
    "admin": {
        "ralfia:read", "ralfia:write", "ralfia:agents", "ralfia:admin",
        "ralfia:memory:read", "ralfia:memory:write", "ralfia:memory:finalize",
        "ralfia:private_memory",
    },
    "tech": {"ralfia:read", "ralfia:write"},
    "user": {"ralfia:read", "ralfia:write"},
}


def _portal_user(username: str, password: str) -> dict[str, Any] | None:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    db = client["hackathon_autopilot"]
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    return db.users.find_one({"username": username, "password_hash": password_hash})


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


def _authorize_form(params: dict[str, str], issuer: str, error: str | None = None) -> str:
    hidden = "\n".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v or "")}">'
        for k, v in params.items()
    )
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    client = html.escape(params.get("client_id", ""))
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Autorizar RalfIA</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #0f172a; color: #e5e7eb; }}
    main {{ max-width: 420px; margin: 10vh auto; padding: 28px; background: #111827; border: 1px solid #334155; border-radius: 8px; }}
    label {{ display: block; margin: 14px 0 6px; color: #cbd5e1; }}
    input {{ width: 100%; box-sizing: border-box; padding: 11px; border: 1px solid #475569; border-radius: 6px; background: #020617; color: #e5e7eb; }}
    button {{ width: 100%; margin-top: 18px; padding: 12px; border: 0; border-radius: 6px; background: #22c55e; color: #052e16; font-weight: 700; cursor: pointer; }}
    .muted {{ color: #94a3b8; font-size: 14px; }}
    .error {{ background: #7f1d1d; color: #fecaca; padding: 10px; border-radius: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>Autorizar RalfIA</h1>
    <p class="muted">Cliente OAuth: {client}. Usa tu usuario del portal principal de RalfIA.</p>
    {error_html}
    <form method="post" action="{html.escape(issuer)}/authorize">
      {hidden}
      <label for="username">Usuario</label>
      <input id="username" name="username" autocomplete="username" required>
      <label for="password">Contraseña</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Autorizar conexión</button>
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
    return HTMLResponse(_authorize_form(params, issuer))


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
    _client, granted_scope = _validate_authorize_params(params)
    portal_user = _portal_user(username, password)
    issuer, _resource = resolve_oauth_urls(request.headers.get("host"))
    if not portal_user:
        return HTMLResponse(_authorize_form(params, issuer, "Usuario o contrasena incorrectos."), status_code=401)
    granted_scope = _scope_for_user(portal_user, granted_scope)
    code = oauth_store.save_auth_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=granted_scope,
        username=username,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource=resource or None,
    )
    query = {"code": code}
    if state:
        query["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(query)}", status_code=303)


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


@app.post("/dev-token")
async def dev_token_disabled() -> JSONResponse:
    nonce = secrets.token_urlsafe(8)
    return JSONResponse({"ok": False, "error": "disabled", "nonce": nonce}, status_code=403)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=OAUTH_HOST, port=OAUTH_PORT, log_level="info")
