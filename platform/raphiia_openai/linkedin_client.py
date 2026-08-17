"""Publicación LinkedIn — UGC Posts + upload imagen."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from raphiia_openai.settings import LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN
from raphiia_openai import config_store


def _token() -> str:
    return config_store.get("LINKEDIN_ACCESS_TOKEN") or LINKEDIN_ACCESS_TOKEN


def _default_author() -> str:
    return config_store.get("LINKEDIN_AUTHOR_URN") or LINKEDIN_AUTHOR_URN


def _author(override: str | None = None) -> str:
    urn = (override or _default_author() or "").strip()
    if not urn:
        raise RuntimeError("LINKEDIN_AUTHOR_URN requerido (urn:li:person:... o urn:li:organization:...)")
    return urn


def _headers() -> dict[str, str]:
    token = _token()
    if not token:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN no configurado — usa Panel :2002 → Configuración")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _request(method: str, url: str, data: dict | None = None) -> dict[str, Any]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=_headers(), method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


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
    )


def upload_image(upload_url: str, image_path: str) -> None:
    path = Path(image_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"imagen inválida: {image_path}")
    data = path.read_bytes()
    req = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Authorization": f"Bearer {_token()}",
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
    return _request("POST", "https://api.linkedin.com/v2/ugcPosts", payload)


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
    upload_image(upload_url, image_path)
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


def get_member_profile() -> dict[str, Any]:
    """Perfil LinkedIn del token actual (requiere scope r_liteprofile o similar)."""
    if not _token():
        return {"ok": False, "error": "no token"}
    try:
        data = _request("GET", "https://api.linkedin.com/v2/me?projection=(id,localizedFirstName,localizedLastName)")
        return {"ok": True, "profile": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


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
        ],
        "recommended_p1": [
            "Guardar linkedin_post_urn tras publicar (ya)",
            "Poll métricas 24h/7d si Rafael aprueba Marketing API",
            "Hashtag sugeridos + contador caracteres en preview",
            "Duplicar borrador ganador",
            "A/B texto corto vs largo",
        ],
    }
