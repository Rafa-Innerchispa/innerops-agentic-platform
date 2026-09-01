"""Publicación LinkedIn — UGC Posts + upload imagen."""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from raphiia_openai.settings import LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN
from raphiia_openai import config_store

LINKEDIN_API_VERSION = "202608"
DEFAULT_OAUTH_SCOPES = ["openid", "profile", "email", "w_member_social"]
ORG_OAUTH_SCOPES = ["openid", "profile", "email", "w_member_social", "w_organization_social"]


def _token(mode: str | None = None, *, author_urn: str | None = None) -> str:
    oauth_mode = _oauth_mode(mode)
    if author_urn and "urn:li:organization:" in author_urn:
        oauth_mode = "organization"
    elif author_urn and "urn:li:person:" in author_urn:
        oauth_mode = "personal"
    if oauth_mode == "organization":
        return config_store.get("LINKEDIN_ORG_ACCESS_TOKEN") or config_store.get("LINKEDIN_ACCESS_TOKEN") or LINKEDIN_ACCESS_TOKEN
    if oauth_mode == "personal":
        return config_store.get("LINKEDIN_PERSONAL_ACCESS_TOKEN") or config_store.get("LINKEDIN_ACCESS_TOKEN") or LINKEDIN_ACCESS_TOKEN
    return (
        config_store.get("LINKEDIN_ACCESS_TOKEN")
        or config_store.get("LINKEDIN_PERSONAL_ACCESS_TOKEN")
        or config_store.get("LINKEDIN_ORG_ACCESS_TOKEN")
        or LINKEDIN_ACCESS_TOKEN
    )


def _default_author() -> str:
    return config_store.get("LINKEDIN_AUTHOR_URN") or LINKEDIN_AUTHOR_URN


def _oauth_mode(mode: str | None) -> str:
    clean = (mode or "default").strip().lower()
    if clean in {"org", "organization", "company", "page", "pages"}:
        return "organization"
    if clean in {"personal", "member", "profile"}:
        return "personal"
    return "default"


def _client_id(mode: str | None = None) -> str:
    oauth_mode = _oauth_mode(mode)
    if oauth_mode == "personal":
        return config_store.get("LINKEDIN_PERSONAL_CLIENT_ID") or config_store.get("LINKEDIN_CLIENT_ID")
    if oauth_mode == "organization":
        return config_store.get("LINKEDIN_ORG_CLIENT_ID") or config_store.get("LINKEDIN_CLIENT_ID")
    return config_store.get("LINKEDIN_CLIENT_ID") or config_store.get("LINKEDIN_PERSONAL_CLIENT_ID") or config_store.get("LINKEDIN_ORG_CLIENT_ID")


def _client_secret(mode: str | None = None) -> str:
    oauth_mode = _oauth_mode(mode)
    if oauth_mode == "personal":
        return config_store.get("LINKEDIN_PERSONAL_CLIENT_SECRET") or config_store.get("LINKEDIN_CLIENT_SECRET")
    if oauth_mode == "organization":
        return config_store.get("LINKEDIN_ORG_CLIENT_SECRET") or config_store.get("LINKEDIN_CLIENT_SECRET")
    return config_store.get("LINKEDIN_CLIENT_SECRET") or config_store.get("LINKEDIN_PERSONAL_CLIENT_SECRET") or config_store.get("LINKEDIN_ORG_CLIENT_SECRET")


def _redirect_uri() -> str:
    return config_store.get("LINKEDIN_REDIRECT_URI") or "https://www.linkedin.com/developers/tools/oauth/redirect"


def _author(override: str | None = None) -> str:
    urn = (override or _default_author() or "").strip()
    if not urn:
        raise RuntimeError("LINKEDIN_AUTHOR_URN requerido (urn:li:person:... o urn:li:organization:...)")
    return urn


def _headers(mode: str | None = None, *, author_urn: str | None = None) -> dict[str, str]:
    token = _token(mode, author_urn=author_urn)
    if not token:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN no configurado — usa Panel :2002 → Configuración")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Linkedin-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _request(
    method: str,
    url: str,
    data: dict | None = None,
    *,
    mode: str | None = None,
    author_urn: str | None = None,
) -> dict[str, Any]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=_headers(mode, author_urn=author_urn), method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


def _request_result(
    method: str,
    url: str,
    data: dict | None = None,
    *,
    mode: str | None = None,
    author_urn: str | None = None,
) -> dict[str, Any]:
    try:
        data_out = _request(method, url, data, mode=mode, author_urn=author_urn)
        return {"ok": True, "data": data_out}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1000]
        return {
            "ok": False,
            "http_status": exc.code,
            "error": raw or exc.reason,
            "needs_reauth": exc.code in (401, 403),
        }
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "needs_token": "LINKEDIN_ACCESS_TOKEN" in str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:1000]}


def oauth_authorization_url(scopes: list[str] | None = None, *, state: str | None = None, mode: str | None = None) -> dict[str, Any]:
    oauth_mode = _oauth_mode(mode)
    default_scopes = ORG_OAUTH_SCOPES if oauth_mode == "organization" else DEFAULT_OAUTH_SCOPES
    client_id = _client_id(oauth_mode)
    redirect_uri = _redirect_uri()
    if not client_id:
        return {"ok": False, "error": "LINKEDIN_CLIENT_ID missing", "mode": oauth_mode}
    clean_scopes = [s.strip() for s in (scopes or default_scopes) if s and s.strip()]
    state_value = state or f"inneros-linkedin-{oauth_mode}-{secrets.token_urlsafe(18)}"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(clean_scopes),
        "state": state_value,
    }
    return {
        "ok": True,
        "url": "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params),
        "state": state_value,
        "mode": oauth_mode,
        "scopes": clean_scopes,
        "redirect_uri": redirect_uri,
        "organization_posting_ready": "w_organization_social" in clean_scopes,
        "note": "Current app scopes can authorize personal posting. Organization posting requires LinkedIn app approval for w_organization_social.",
    }


def exchange_authorization_code(code: str, *, redirect_uri: str | None = None, mode: str | None = None) -> dict[str, Any]:
    clean_code = (code or "").strip()
    oauth_mode = _oauth_mode(mode)
    client_id = _client_id(oauth_mode)
    client_secret = _client_secret(oauth_mode)
    final_redirect = (redirect_uri or _redirect_uri()).strip()
    missing = [name for name, value in {
        "authorization_code": clean_code,
        "LINKEDIN_CLIENT_ID": client_id,
        "LINKEDIN_CLIENT_SECRET": client_secret,
        "LINKEDIN_REDIRECT_URI": final_redirect,
    }.items() if not value]
    if missing:
        return {"ok": False, "error": "missing_oauth_config", "missing": missing, "mode": oauth_mode}
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": clean_code,
            "redirect_uri": final_redirect,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1000]
        return {"ok": False, "http_status": exc.code, "error": raw or exc.reason, "needs_new_code": True}
    token = str(data.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "error": "linkedin_response_missing_access_token", "raw_keys": sorted(data)}
    token_key = "LINKEDIN_ORG_ACCESS_TOKEN" if oauth_mode == "organization" else "LINKEDIN_PERSONAL_ACCESS_TOKEN"
    config_store.set_values({token_key: token, "LINKEDIN_ACCESS_TOKEN": token}, updated_by="LINKEDIN_OAUTH", sync_env=True)
    return {
        "ok": True,
        "status": "access_token_updated",
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope", ""),
        "token_display": config_store.mask_secret(token),
        "mode": oauth_mode,
        "diagnostics": token_diagnostics(),
    }


def register_image_upload(*, author_urn: str | None = None) -> dict[str, Any]:
    author = _author(author_urn)
    return _request(
        "POST",
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": author,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        },
        author_urn=author,
    )


def upload_image(upload_url: str, image_path: str, *, author_urn: str | None = None) -> None:
    path = Path(image_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"imagen inválida: {image_path}")
    data = path.read_bytes()
    req = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Authorization": f"Bearer {_token(author_urn=author_urn)}",
            "Content-Type": "application/octet-stream",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"upload failed {resp.status}")


def publish_post(
    *,
    text: str,
    asset_urn: str | None = None,
    media_title: str = "",
    visibility: str = "PUBLIC",
    author_urn: str | None = None,
) -> dict[str, Any]:
    author = _author(author_urn)
    vis = "PUBLIC" if visibility.upper() != "CONNECTIONS" else "CONNECTIONS"
    share_content: dict[str, Any] = {
        "shareCommentary": {"text": text[:3000]},
        "shareMediaCategory": "NONE" if not asset_urn else "IMAGE",
    }
    if asset_urn:
        share_content["media"] = [
            {
                "status": "READY",
                "description": {"text": text[:200]},
                "media": asset_urn,
                "title": {"text": (media_title or "Ralphi IA")[:200]},
            }
        ]
    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": vis},
    }
    return _request("POST", "https://api.linkedin.com/v2/ugcPosts", payload, author_urn=author)


def publish_with_image(
    text: str,
    image_path: str,
    *,
    media_title: str = "",
    visibility: str = "PUBLIC",
    author_urn: str | None = None,
) -> dict[str, Any]:
    reg = register_image_upload(author_urn=author_urn)
    value = reg.get("value", reg)
    upload_mechanism = value.get("uploadMechanism", {})
    http_req = upload_mechanism.get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
    upload_url = http_req.get("uploadUrl")
    asset = value.get("asset")
    if not upload_url or not asset:
        raise RuntimeError(f"registerUpload respuesta inválida: {json.dumps(reg)[:400]}")
    upload_image(upload_url, image_path, author_urn=author_urn)
    result = publish_post(
        text=text, asset_urn=asset, media_title=media_title, visibility=visibility, author_urn=author_urn
    )
    urn = result.get("id") or result.get("entity") or ""
    return {"ok": True, "linkedin_urn": urn, "asset": asset, "raw": result}


def config_status() -> dict[str, Any]:
    tok = _token()
    auth = _default_author()
    return {
        "linkedin_token": bool(tok),
        "linkedin_author": bool(auth),
        "ready": bool(tok and auth),
        "config_source": "panel_mongo",
    }


def token_diagnostics(mode: str | None = None) -> dict[str, Any]:
    """Read-only OAuth health check. Never publishes content."""
    oauth_mode = _oauth_mode(mode)
    token_present = bool(_token(oauth_mode))
    author = _default_author()
    out: dict[str, Any] = {
        "ok": token_present,
        "token_present": token_present,
        "default_author_present": bool(author),
        "default_author_urn_display": author.rsplit(":", 1)[-1][-8:] if author else "",
        "api_version": LINKEDIN_API_VERSION,
        "mode": oauth_mode,
        "required_scopes": ["w_member_social", "w_organization_social"],
        "recommended_read_scopes": ["openid", "profile", "r_organization_admin"],
    }
    if not token_present:
        out.update(
            {
                "status": "missing_token",
                "needs_human_action": "Generate/authorize a LinkedIn OAuth token with member + organization posting permissions.",
            }
        )
        return out
    me = _request_result("GET", "https://api.linkedin.com/v2/me?projection=(id,localizedFirstName,localizedLastName)", mode=oauth_mode)
    out["me"] = me
    if not me.get("ok"):
        out["ok"] = False
        out["status"] = "token_invalid_or_missing_profile_scope"
        out["needs_human_action"] = "Refresh LinkedIn token/scopes in the editorial panel."
        return out
    out["status"] = "token_valid_profile_ok"
    return out


def get_member_profile() -> dict[str, Any]:
    """Perfil LinkedIn del token actual (requiere scope r_liteprofile o similar)."""
    if not _token():
        return {"ok": False, "error": "no token"}
    try:
        data = _request("GET", "https://api.linkedin.com/v2/me?projection=(id,localizedFirstName,localizedLastName)")
        return {"ok": True, "profile": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def list_administered_organizations() -> dict[str, Any]:
    """List pages the authenticated member can administer, when scopes allow it."""
    diag = token_diagnostics()
    if not diag.get("ok"):
        return {"ok": False, "error": diag.get("status", "token_not_ready"), "diagnostics": diag}
    profile_id = ((diag.get("me") or {}).get("data") or {}).get("id", "")
    if not profile_id:
        return {"ok": False, "error": "member_id_missing", "diagnostics": diag}
    member_urn = f"urn:li:person:{profile_id}"
    import urllib.parse

    encoded_member = urllib.parse.quote(member_urn, safe="")
    url = (
        "https://api.linkedin.com/v2/organizationAcls"
        "?q=roleAssignee"
        f"&roleAssignee={encoded_member}"
        "&state=APPROVED"
    )
    raw = _request_result("GET", url)
    if not raw.get("ok"):
        return {
            "ok": False,
            "error": "organization_acl_unavailable",
            "details": raw,
            "requires": ["r_organization_admin or Marketing Developer Platform organization access", "admin role on each LinkedIn Page"],
        }
    elements = (raw.get("data") or {}).get("elements") or []
    organizations: list[dict[str, Any]] = []
    for item in elements:
        org = item.get("organization") or item.get("organizationalTarget") or ""
        if isinstance(org, str) and org:
            organizations.append(
                {
                    "organization_urn": org,
                    "organization_id": org.rsplit(":", 1)[-1],
                    "role": item.get("role", ""),
                    "state": item.get("state", ""),
                    "raw": item,
                }
            )
    return {"ok": True, "member_urn": member_urn, "count": len(organizations), "organizations": organizations}


def try_post_statistics(post_urn: str) -> dict[str, Any]:
    """Estadísticas — suele requerir Marketing Developer Platform."""
    if not post_urn:
        return {"ok": False, "error": "missing urn", "requires": "marketing_api"}
    return {
        "ok": False,
        "error": "scope_or_product_missing",
        "requires": "LinkedIn Marketing API + r_organization_social o analytics scopes",
        "post_urn": post_urn,
        "hint": "Guardamos URN al publicar; métricas P1 cuando apruebes Marketing API",
    }


def list_visibility_options() -> list[dict[str, str]]:
    return [
        {"id": "PUBLIC", "label_es": "Público", "label_en": "Public"},
        {"id": "CONNECTIONS", "label_es": "Solo conexiones", "label_en": "Connections only"},
    ]


def api_capabilities() -> dict[str, Any]:
    """Qué puede hacer la conexión LinkedIn actual vs requiere scopes extra."""
    ready = config_status()["ready"]
    return {
        "connected": ready,
        "available_now": [
            "Publicar post texto (UGC Posts API)",
            "Publicar post con imagen (registerUpload + UGC)",
            "Visibilidad PUBLIC o CONNECTIONS",
            "Preview editorial en :8101/editorial",
            "Traducción multi-idioma (Ollama local)",
            "Cola aprobación humana antes de publicar",
            "Perfil miembro (GET /v2/me) si scope lo permite",
        ],
        "requires_marketing_api": [
            "Impresiones, clics, engagement por post",
            "Demografía de audiencia",
            "Analytics organización (Company Page)",
            "Programación nativa LinkedIn (Scheduler API)",
        ],
        "requires_extra_scopes": [
            "r_member_social — leer posts propios y estadísticas básicas",
            "w_member_social — publicar (ya usamos)",
            "r_organization_social — analytics página empresa",
            "w_organization_social — publicar como páginas empresa",
            "r_organization_admin — descubrir páginas administradas",
        ],
        "recommended_p1": [
            "Guardar linkedin_post_urn tras publicar (ya)",
            "Poll métricas 24h/7d si Rafael aprueba Marketing API",
            "Hashtag sugeridos + contador caracteres en preview",
            "Duplicar borrador ganador",
            "A/B texto corto vs largo",
        ],
    }
