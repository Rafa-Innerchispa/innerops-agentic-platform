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


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    """Landing informativa: evita 404 al abrir el issuer en el navegador."""
    issuer, resource = resolve_oauth_urls(request.headers.get("host"))
    return HTMLResponse(_oauth_landing(issuer, resource))


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
    from inneros_core_runtime.oauth_metadata import small_router_protected_resource_metadata

    return small_router_protected_resource_metadata(request.headers.get("host"))


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


def _oauth_styles() -> str:
    return """
    :root {
      --bg: #030712;
      --card: rgba(15, 23, 42, 0.72);
      --stroke: rgba(148, 163, 184, 0.22);
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #22d3ee;
      --accent2: #a78bfa;
      --ok: #4ade80;
      --bad: #f87171;
    }
  font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  body {
    margin: 0;
    min-height: 100vh;
    color: var(--text);
    background: var(--bg);
    background-image:
      radial-gradient(ellipse 80% 50% at 20% -10%, rgba(34, 211, 238, 0.18), transparent),
      radial-gradient(ellipse 60% 45% at 100% 0%, rgba(167, 139, 250, 0.14), transparent),
      radial-gradient(ellipse 50% 40% at 50% 100%, rgba(14, 165, 233, 0.08), transparent);
    font-family: inherit;
  }
  .page { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 1.5rem; box-sizing: border-box; }
  .card {
    width: 100%;
    max-width: 440px;
    padding: 2rem 1.75rem 1.75rem;
    border-radius: 20px;
    border: 1px solid var(--stroke);
    background: var(--card);
    backdrop-filter: blur(18px);
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  }
  .mark { width: 52px; height: 52px; margin: 0 auto 1rem; border-radius: 16px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: grid; place-items: center; font-weight: 800; font-size: 1.1rem; letter-spacing: -0.04em; color: #0f172a;
    box-shadow: 0 8px 32px rgba(34, 211, 238, 0.35);
  }
  h1 { margin: 0; text-align: center; font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em; }
  .tagline { text-align: center; color: var(--muted); font-size: 0.88rem; line-height: 1.45; margin: 0.5rem 0 1.25rem; }
  .pill-row { display: flex; flex-wrap: wrap; gap: 0.4rem; justify-content: center; margin-bottom: 1.25rem; }
  .pill { font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 0.28rem 0.55rem; border-radius: 999px; border: 1px solid var(--stroke); color: #cbd5e1; background: rgba(2, 6, 23, 0.5); }
  .pill.live { border-color: rgba(74, 222, 128, 0.35); color: var(--ok); }
  .client-box {
    padding: 0.85rem 1rem; border-radius: 12px; border: 1px solid var(--stroke);
    background: rgba(2, 6, 23, 0.55); margin-bottom: 1rem; font-size: 0.82rem; line-height: 1.4;
  }
  .client-box strong { color: var(--accent); font-weight: 600; word-break: break-all; }
  .scopes { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; }
  .scope-chip { font-size: 0.72rem; padding: 0.2rem 0.45rem; border-radius: 6px; background: #1e293b; color: #bae6fd; }
  .sso-banner {
    padding: 0.75rem 1rem; border-radius: 12px; margin-bottom: 1rem; text-align: center; font-size: 0.88rem;
    border: 1px solid rgba(34, 211, 238, 0.35); background: rgba(8, 47, 73, 0.45); color: #a5f3fc;
  }
  label { display: block; margin: 0.9rem 0 0.35rem; font-size: 0.8rem; font-weight: 600; color: #cbd5e1; }
  input[type="text"], input[type="password"] {
    width: 100%; box-sizing: border-box; padding: 0.72rem 0.9rem; border-radius: 10px;
    border: 1px solid var(--stroke); background: rgba(2, 6, 23, 0.7); color: var(--text); font-size: 1rem;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.2); }
  button[type="submit"] {
    width: 100%; margin-top: 1.35rem; padding: 0.85rem 1rem; border: none; border-radius: 12px; cursor: pointer;
    font-weight: 700; font-size: 0.95rem; color: #0f172a;
    background: linear-gradient(135deg, #22d3ee, #38bdf8 45%, #a78bfa);
    box-shadow: 0 10px 40px rgba(34, 211, 238, 0.25);
    transition: transform 0.12s, box-shadow 0.12s;
  }
  button[type="submit"]:hover { transform: translateY(-1px); box-shadow: 0 14px 48px rgba(34, 211, 238, 0.32); }
  .error {
    color: var(--bad); font-size: 0.85rem; margin-bottom: 1rem; padding: 0.65rem 0.85rem; border-radius: 10px;
    background: rgba(127, 29, 29, 0.35); border: 1px solid rgba(248, 113, 113, 0.35);
  }
  footer { margin-top: 1.25rem; text-align: center; font-size: 0.72rem; color: #64748b; line-height: 1.5; }
  footer a { color: var(--muted); text-decoration: none; }
  .landing-links { margin-top: 1.5rem; display: flex; flex-direction: column; gap: 0.5rem; font-size: 0.85rem; }
  .landing-links a { color: var(--accent); text-decoration: none; }
"""


def _scope_chips(scope: str) -> str:
    parts = [s.strip() for s in (scope or "").split() if s.strip()]
    if not parts:
        return ""
    chips = "".join(f'<span class="scope-chip">{html.escape(p)}</span>' for p in parts[:8])
    more = f'<span class="scope-chip">+{len(parts) - 8}</span>' if len(parts) > 8 else ""
    return f'<div class="scopes">{chips}{more}</div>'


def _oauth_landing(issuer: str, resource: str) -> str:
    iss = html.escape(issuer)
    res = html.escape(resource or "")
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#030712">
  <title>InnerOS · OAuth Gateway</title>
  <style>{_oauth_styles()}</style>
</head>
<body>
  <div class="page">
    <div class="card">
      <div class="mark">IO</div>
      <h1>InnerOS Unified SSO</h1>
      <p class="tagline">Puerta de autorización OAuth para MCP, ChatGPT y agentes coordinados en tu red.</p>
      <div class="pill-row">
        <span class="pill live">Auth operational</span>
        <span class="pill">OAuth 2.0</span>
        <span class="pill">PKCE S256</span>
        <span class="pill">Local-first</span>
      </div>
      <div class="client-box">
        <div>Issuer</div>
        <strong>{iss}</strong>
        {"<div style='margin-top:0.75rem'>Recurso MCP</div><strong>" + res + "</strong>" if res else ""}
      </div>
      <p class="tagline">Abre tu cliente (p. ej. ChatGPT → Conectores MCP) para iniciar el flujo en <code>/authorize</code>.</p>
      <div class="landing-links">
        <a href="{iss}/.well-known/oauth-authorization-server">Metadata del servidor</a>
        <a href="{iss}/health">Health</a>
      </div>
      <footer>PCDoctor · InnerChispa · Intel + AMD</footer>
    </div>
  </div>
</body>
</html>"""


def _authorize_form(params: dict[str, str], issuer: str, active_user: str | None = None, error: str | None = None) -> str:
    hidden = "\n".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v or "")}">'
        for k, v in params.items()
    )
    error_html = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    client = html.escape(params.get("client_id", ""))
    scope_html = _scope_chips(params.get("scope", ""))
    resource = html.escape((params.get("resource") or "").strip())
    resource_block = (
        f"<div style='margin-top:0.6rem;color:var(--muted);font-size:0.75rem'>Recurso MCP</div>"
        f"<strong style='font-size:0.8rem'>{resource}</strong>"
        if resource
        else ""
    )
    logged_in_banner = (
        f'<div class="sso-banner">Sesión activa · <strong>{html.escape(active_user)}</strong></div>'
        if active_user
        else ""
    )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#030712">
  <meta name="color-scheme" content="dark">
  <title>InnerOS Unified SSO</title>
  <style>{_oauth_styles()}</style>
</head>
<body>
  <div class="page">
    <div class="card">
      <div class="mark">IO</div>
      <h1>InnerOS Unified SSO</h1>
      <p class="tagline">Autoriza el acceso MCP de forma segura. Tus credenciales no salen de este servidor.</p>
      <div class="pill-row">
        <span class="pill live">Conexión cifrada</span>
        <span class="pill">PKCE</span>
        <span class="pill">ralfia scopes</span>
      </div>
      <div class="client-box">
        <div style="color:var(--muted);font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em">Aplicación cliente</div>
        <strong>{client}</strong>
        {resource_block}
        {scope_html}
      </div>
      {logged_in_banner}
      {error_html}
      <form method="post" action="{html.escape(issuer)}/authorize">
        {hidden}
        <label for="username">Usuario</label>
        <input id="username" name="username" autocomplete="username" value="{html.escape(active_user or "")}" required>
        <label for="password">Contraseña</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Iniciar sesión y autorizar MCP</button>
      </form>
      <footer>InnerOS · mcp.pcdoctor.ai · Coordinación RalfIA</footer>
    </div>
  </div>
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
