"""Discord provider plane for InnerOS Resource Fabric.

Discord is an operations/community surface for alerts, approvals, publishing,
and read-only coordination. Local command execution stays behind MCP scopes and
separate approval gates.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store, owner_vault

CAPABILITY = "local_discord_plane"
PROVIDER_ID = "discord-ops"
VAULT_CATEGORY = "discord"
BOT_TOKEN_KEY = "bot_token"
WEBHOOK_URL_KEY = "ops_webhook_url"
API_BASE = "https://discord.com/api/v10"
COL_CONFIG = "inneros_discord_config"
COL_AUDIT = "ralfia_discord_audit"

DEFAULT_APPLICATION_ID = "1534410918962663425"
DEFAULT_PUBLIC_KEY = "45ba549cabf8c5fc61798bb894d7facac2d22f14eaf0e3cb82cac1df49bde0d2"
DEFAULT_BOT_PERMISSIONS = 84992


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: str) -> str:
    text = value or ""
    text = re.sub(r"Bot\s+[A-Za-z0-9._\-]+", "Bot [REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"(discord(?:app)?\.com/api/webhooks/)[^\s\"']+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"(Authorization)(:\s*|=\s*)(Bot\s+)?[^\s,;]+", r"\1\2[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, 100))


def _config() -> dict[str, Any]:
    doc = mongo_store.get_db()[COL_CONFIG].find_one({"config_id": "default"}, {"_id": 0}) or {}
    channels = doc.get("channels") if isinstance(doc.get("channels"), dict) else {}
    return {
        "application_id": str(doc.get("application_id") or os.getenv("DISCORD_APPLICATION_ID") or DEFAULT_APPLICATION_ID).strip(),
        "public_key": str(doc.get("public_key") or os.getenv("DISCORD_PUBLIC_KEY") or DEFAULT_PUBLIC_KEY).strip(),
        "default_channel_id": str(doc.get("default_channel_id") or os.getenv("DISCORD_DEFAULT_CHANNEL_ID") or "").strip(),
        "default_guild_id": str(doc.get("default_guild_id") or os.getenv("DISCORD_DEFAULT_GUILD_ID") or "").strip(),
        "interactions_endpoint_url": str(doc.get("interactions_endpoint_url") or os.getenv("DISCORD_INTERACTIONS_ENDPOINT_URL") or "").strip(),
        "channels": {str(k): str(v) for k, v in channels.items()},
        "updated_at": doc.get("updated_at"),
    }


def configure_public_app(
    application_id: str = DEFAULT_APPLICATION_ID,
    public_key: str = DEFAULT_PUBLIC_KEY,
    default_channel_id: str = "",
    default_guild_id: str = "",
    actor: str = "RAFAEL",
) -> dict[str, Any]:
    if actor.upper() != "RAFAEL":
        return {"ok": False, "error": "owner_only"}
    app_id = (application_id or "").strip()
    pub = (public_key or "").strip()
    if not app_id or not pub:
        return {"ok": False, "error": "application_id_and_public_key_required"}
    doc = {
        "config_id": "default",
        "application_id": app_id,
        "public_key": pub,
        "default_channel_id": (default_channel_id or "").strip(),
        "default_guild_id": (default_guild_id or "").strip(),
        "updated_at": _now(),
        "updated_by": actor.upper(),
    }
    mongo_store.get_db()[COL_CONFIG].update_one({"config_id": "default"}, {"$set": doc, "$setOnInsert": {"created_at": doc["updated_at"]}}, upsert=True)
    public = {k: v for k, v in doc.items() if k != "public_key"}
    return {"ok": True, "config": public, "public_key_present": True}


def store_bot_token_server_side(secret: str, label: str = "Discord Bot Token", actor: str = "RAFAEL") -> dict[str, Any]:
    result = owner_vault.save_owner_credential(
        key=BOT_TOKEN_KEY,
        secret=secret,
        category=VAULT_CATEGORY,
        label=label,
        actor=actor,
        metadata={"provider": PROVIDER_ID, "stored_for": CAPABILITY},
    )
    return {**result, "secret_stored": bool(result.get("ok")), "secret_returned": False}


def store_webhook_url_server_side(secret: str, label: str = "Discord Ops Webhook URL", actor: str = "RAFAEL") -> dict[str, Any]:
    result = owner_vault.save_owner_credential(
        key=WEBHOOK_URL_KEY,
        secret=secret,
        category=VAULT_CATEGORY,
        label=label,
        actor=actor,
        metadata={"provider": PROVIDER_ID, "stored_for": CAPABILITY},
    )
    return {**result, "secret_stored": bool(result.get("ok")), "secret_returned": False}


def _secret(key: str) -> tuple[str, str]:
    cred = owner_vault.get_owner_credential(key, category=VAULT_CATEGORY, reveal=True)
    secret = str(cred.get("secret") or "").strip() if cred.get("ok") else ""
    if secret:
        return secret, f"owner_vault:discord/{key}"
    env_key = "DISCORD_BOT_TOKEN" if key == BOT_TOKEN_KEY else "DISCORD_OPS_WEBHOOK_URL"
    env_secret = (os.getenv(env_key) or "").strip()
    if env_secret:
        return env_secret, f"env:{env_key}"
    return "", "missing"


def _request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 25) -> dict[str, Any]:
    token, source = _secret(BOT_TOKEN_KEY)
    if not token:
        return {"ok": False, "error": "discord_bot_token_missing", "token_source": source, "hint": "store token with local_discord_store_bot_token_server_side"}
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method.upper(),
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json", "User-Agent": "InnerOS-Discord-Plane/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else None
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": parsed, "token_source": source}
    except urllib.error.HTTPError as exc:
        detail_raw = exc.read().decode("utf-8", errors="replace")[:2000]
        retry_after = None
        try:
            parsed = json.loads(detail_raw)
            retry_after = parsed.get("retry_after") if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        return {"ok": False, "status": exc.code, "error": "discord_rate_limited" if exc.code == 429 else "discord_http_error", "retry_after": retry_after, "detail": _redact(detail_raw), "token_source": source}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": "discord_unreachable", "detail": _redact(str(exc.reason)), "token_source": source}


def _audit(action: str, result: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    try:
        mongo_store.get_db()[COL_AUDIT].insert_one(
            {"action": action, "result_ok": bool(result.get("ok")), "result": {k: v for k, v in result.items() if k != "data"}, "metadata": metadata or {}, "created_at": _now(), "capability": CAPABILITY}
        )
    except Exception:
        pass


def discord_status() -> dict[str, Any]:
    cfg = _config()
    token, source = _secret(BOT_TOKEN_KEY)
    webhook, webhook_source = _secret(WEBHOOK_URL_KEY)
    result: dict[str, Any] = {
        "ok": True,
        "capability": CAPABILITY,
        "provider_id": PROVIDER_ID,
        "application_id": cfg["application_id"],
        "public_key_present": bool(cfg["public_key"]),
        "default_channel_id_present": bool(cfg["default_channel_id"]),
        "default_guild_id_present": bool(cfg["default_guild_id"]),
        "interactions_endpoint_url": cfg.get("interactions_endpoint_url") or None,
        "bot_token_present": bool(token),
        "bot_token_source": source,
        "webhook_present": bool(webhook),
        "webhook_source": webhook_source,
        "auth_ok": False,
        "bot_user": None,
        "execution_policy": "alerts and approvals first; command execution requires MCP scope plus explicit approval",
        "interaction_gateway": {
            "path": "/discord/interactions",
            "signature_verification": "ed25519_required",
            "arbitrary_execution": False,
        },
    }
    if token:
        me = _request("GET", "/users/@me")
        result["auth_ok"] = bool(me.get("ok"))
        result["auth_status"] = me.get("status")
        if me.get("ok") and isinstance(me.get("data"), dict):
            data = me["data"]
            result["bot_user"] = {"id": data.get("id"), "username": data.get("username"), "bot": data.get("bot")}
        else:
            result["auth_error"] = {k: v for k, v in me.items() if k != "data"}
    return result


def oauth_install_url(permissions: int = DEFAULT_BOT_PERMISSIONS) -> dict[str, Any]:
    cfg = _config()
    app_id = cfg["application_id"]
    if not app_id:
        return {"ok": False, "error": "application_id_required"}
    scopes = "bot applications.commands"
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={app_id}"
        f"&permissions={int(permissions)}"
        "&integration_type=0"
        f"&scope={scopes.replace(' ', '+')}"
    )
    return {
        "ok": True,
        "application_id": app_id,
        "permissions": int(permissions),
        "scopes": scopes.split(),
        "url": url,
        "permission_notes": ["View Channels", "Send Messages", "Embed Links", "Read Message History"],
    }


def set_interactions_endpoint_url(endpoint_url: str, dry_run: bool = True, actor: str = "RAFAEL") -> dict[str, Any]:
    cfg = _config()
    app_id = cfg["application_id"]
    url = (endpoint_url or "").strip()
    if not app_id or not url:
        return {"ok": False, "error": "application_id_and_endpoint_url_required"}
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.path.startswith("/discord/interactions"):
        return {"ok": False, "error": "https_discord_interactions_url_required", "hint": "Use https://mcp.pcdoctor.ai/discord/interactions"}
    payload = {"interactions_endpoint_url": url}
    if dry_run:
        return {"ok": True, "dry_run": True, "application_id": app_id, "endpoint_url": url}
    res = _request("PATCH", f"/applications/{app_id}", payload=payload)
    _audit("set_interactions_endpoint_url", res, {"endpoint_url": url, "actor": actor})
    if res.get("ok"):
        mongo_store.get_db()[COL_CONFIG].update_one(
            {"config_id": "default"},
            {"$set": {"interactions_endpoint_url": url, "updated_at": _now(), "updated_by": actor}},
            upsert=True,
        )
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    return {
        "ok": bool(res.get("ok")),
        "status": res.get("status"),
        "application_id": app_id,
        "endpoint_url": data.get("interactions_endpoint_url") or url,
        "error": res.get("error"),
        "detail": res.get("detail"),
    }


def list_guilds(limit: int = 20) -> dict[str, Any]:
    res = _request("GET", "/users/@me/guilds")
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    items = rows[: _limit(limit)]
    return {"ok": True, "count": len(items), "guilds": [{"id": g.get("id"), "name": g.get("name"), "owner": g.get("owner"), "permissions": g.get("permissions")} for g in items if isinstance(g, dict)]}


def list_channels(guild_id: str = "", limit: int = 100) -> dict[str, Any]:
    cfg = _config()
    guild = (guild_id or cfg["default_guild_id"]).strip()
    if not guild:
        return {"ok": False, "error": "guild_id_required"}
    res = _request("GET", f"/guilds/{guild}/channels")
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    items = rows[: _limit(limit)]
    return {
        "ok": True,
        "count": len(items),
        "guild_id": guild,
        "channels": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "parent_id": item.get("parent_id"),
                "position": item.get("position"),
            }
            for item in items
            if isinstance(item, dict)
        ],
    }


def create_text_channel(name: str, topic: str = "", guild_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    cfg = _config()
    guild = (guild_id or cfg["default_guild_id"]).strip()
    channel_name = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")[:90]
    if not guild or not channel_name:
        return {"ok": False, "error": "guild_id_and_name_required"}
    payload = {"name": channel_name, "type": 0}
    if topic:
        payload["topic"] = topic[:1024]
    if dry_run:
        return {"ok": True, "dry_run": True, "guild_id": guild, "channel": payload}
    res = _request("POST", f"/guilds/{guild}/channels", payload=payload)
    _audit("create_text_channel", res, {"guild_id": guild, "name": channel_name})
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    return {"ok": bool(res.get("ok")), "status": res.get("status"), "channel_id": data.get("id"), "name": data.get("name") or channel_name, "error": res.get("error"), "detail": res.get("detail")}


def list_channel_webhooks(channel_id: str = "") -> dict[str, Any]:
    resolved = resolve_channel(channel_id)
    if not resolved.get("ok"):
        return resolved
    res = _request("GET", f"/channels/{resolved['channel_id']}/webhooks")
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {
        "ok": True,
        "count": len(rows),
        "channel_id": resolved["channel_id"],
        "webhooks": [
            {"id": item.get("id"), "name": item.get("name"), "channel_id": item.get("channel_id"), "guild_id": item.get("guild_id")}
            for item in rows
            if isinstance(item, dict)
        ],
    }


def create_channel_webhook(channel: str, name: str = "RalphiIA", dry_run: bool = True) -> dict[str, Any]:
    resolved = resolve_channel(channel)
    if not resolved.get("ok"):
        return resolved
    hook_name = (name or "RalphiIA").strip()[:80]
    if dry_run:
        return {"ok": True, "dry_run": True, "channel_id": resolved["channel_id"], "name": hook_name}
    existing = list_channel_webhooks(resolved["channel_id"])
    if existing.get("ok"):
        for webhook in existing.get("webhooks", []):
            if webhook.get("name") == hook_name:
                return {
                    "ok": True,
                    "status": 200,
                    "webhook_id": webhook.get("id"),
                    "channel_id": webhook.get("channel_id") or resolved["channel_id"],
                    "name": hook_name,
                    "already_existed": True,
                    "webhook_url_stored": False,
                    "secret_returned": False,
                }
    res = _request("POST", f"/channels/{resolved['channel_id']}/webhooks", payload={"name": hook_name})
    _audit("create_channel_webhook", res, {"channel_id": resolved["channel_id"], "name": hook_name})
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    if res.get("ok") and data.get("url"):
        store_webhook_url_server_side(str(data["url"]), label=f"Discord webhook {hook_name}", actor="RAFAEL")
    return {
        "ok": bool(res.get("ok")),
        "status": res.get("status"),
        "webhook_id": data.get("id"),
        "channel_id": data.get("channel_id") or resolved["channel_id"],
        "name": data.get("name") or hook_name,
        "webhook_url_stored": bool(res.get("ok") and data.get("url")),
        "secret_returned": False,
        "error": res.get("error"),
        "detail": res.get("detail"),
    }


def create_thread(channel: str, name: str, message: str = "", dry_run: bool = True) -> dict[str, Any]:
    resolved = resolve_channel(channel)
    if not resolved.get("ok"):
        return resolved
    thread_name = (name or "").strip()[:100]
    if not thread_name:
        return {"ok": False, "error": "thread_name_required"}
    payload: dict[str, Any] = {"name": thread_name, "type": 11, "auto_archive_duration": 1440}
    if message.strip():
        payload["message"] = {"content": message.strip()[:1900]}
    if dry_run:
        return {"ok": True, "dry_run": True, "channel_id": resolved["channel_id"], "thread": payload}
    res = _request("POST", f"/channels/{resolved['channel_id']}/threads", payload=payload)
    _audit("create_thread", res, {"channel_id": resolved["channel_id"], "name": thread_name})
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    return {"ok": bool(res.get("ok")), "status": res.get("status"), "thread_id": data.get("id"), "name": data.get("name") or thread_name, "error": res.get("error"), "detail": res.get("detail")}


def list_channel_messages(channel_id: str = "", limit: int = 20) -> dict[str, Any]:
    cfg = _config()
    channel = (channel_id or cfg["default_channel_id"]).strip()
    if not channel:
        return {"ok": False, "error": "channel_id_required"}
    res = _request("GET", f"/channels/{channel}/messages?limit={_limit(limit)}")
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {
        "ok": True,
        "count": len(rows),
        "channel_id": channel,
        "messages": [
            {
                "id": item.get("id"),
                "author": (item.get("author") or {}).get("username") if isinstance(item.get("author"), dict) else None,
                "content": item.get("content"),
                "timestamp": item.get("timestamp"),
            }
            for item in rows
            if isinstance(item, dict)
        ],
    }


def resolve_channel(name_or_id: str = "") -> dict[str, Any]:
    cfg = _config()
    value = (name_or_id or "").strip().lstrip("#")
    if not value:
        value = cfg["default_channel_id"]
    channels = cfg.get("channels") or {}
    if value in channels:
        return {"ok": True, "channel_id": channels[value], "matched": value, "source": "configured_channel_map"}
    normalized = value.replace("-", "_")
    if normalized in channels:
        return {"ok": True, "channel_id": channels[normalized], "matched": normalized, "source": "configured_channel_map"}
    if value.isdigit():
        return {"ok": True, "channel_id": value, "matched": value, "source": "direct_id"}
    listed = list_channels(guild_id=cfg["default_guild_id"], limit=100)
    if not listed.get("ok"):
        return listed
    for item in listed.get("channels") or []:
        if str(item.get("name") or "").lower() == value.lower():
            return {"ok": True, "channel_id": str(item.get("id")), "matched": item.get("name"), "source": "discord_channels"}
    return {"ok": False, "error": "channel_not_found", "name_or_id": name_or_id}


def search_channel_messages(channel_id: str = "", query: str = "", limit: int = 50) -> dict[str, Any]:
    needle = (query or "").strip().lower()
    if not needle:
        return {"ok": False, "error": "query_required"}
    messages = list_channel_messages(channel_id=channel_id, limit=limit)
    if not messages.get("ok"):
        return messages
    matches = [
        item
        for item in messages.get("messages") or []
        if needle in str(item.get("content") or "").lower() or needle in str(item.get("author") or "").lower()
    ]
    return {"ok": True, "count": len(matches), "query": query, "channel_id": messages.get("channel_id"), "matches": matches}


def read_configured_channels(limit_per_channel: int = 10) -> dict[str, Any]:
    cfg = _config()
    out: dict[str, Any] = {"ok": True, "channels": {}}
    for name, channel_id in (cfg.get("channels") or {}).items():
        out["channels"][name] = list_channel_messages(channel_id=channel_id, limit=limit_per_channel)
    return out


def search_configured_channels(query: str, limit_per_channel: int = 50) -> dict[str, Any]:
    cfg = _config()
    matches: list[dict[str, Any]] = []
    for name, channel_id in (cfg.get("channels") or {}).items():
        res = search_channel_messages(channel_id=channel_id, query=query, limit=limit_per_channel)
        if res.get("ok"):
            for item in res.get("matches") or []:
                matches.append({**item, "channel_name": name, "channel_id": channel_id})
    return {"ok": True, "query": query, "count": len(matches), "matches": matches}


def send_named_channel_message(channel: str, content: str, dry_run: bool = True) -> dict[str, Any]:
    resolved = resolve_channel(channel)
    if not resolved.get("ok"):
        return resolved
    result = send_channel_message(channel_id=resolved["channel_id"], content=content, dry_run=dry_run)
    return {**result, "resolved_channel": resolved}


def list_guild_commands(guild_id: str = "") -> dict[str, Any]:
    cfg = _config()
    guild = (guild_id or cfg["default_guild_id"]).strip()
    if not guild:
        return {"ok": False, "error": "guild_id_required"}
    res = _request("GET", f"/applications/{cfg['application_id']}/guilds/{guild}/commands")
    if not res.get("ok"):
        return res
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {"ok": True, "count": len(rows), "commands": [{"id": item.get("id"), "name": item.get("name"), "description": item.get("description")} for item in rows if isinstance(item, dict)]}


def register_guild_commands(guild_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    cfg = _config()
    guild = (guild_id or cfg["default_guild_id"]).strip()
    if not guild:
        return {"ok": False, "error": "guild_id_required"}
    commands = [
        {"name": "inneros-status", "description": "Mostrar estado operativo de InnerOS/RalphiIA"},
        {
            "name": "inneros-novedad",
            "description": "Publicar una novedad en un canal controlado",
            "options": [
                {"type": 3, "name": "texto", "description": "Texto a publicar", "required": True},
                {"type": 3, "name": "canal", "description": "Alias o nombre del canal", "required": False},
            ],
        },
        {
            "name": "inneros-hackathon",
            "description": "Publicar avance o evidencia de hackathon",
            "options": [
                {"type": 3, "name": "texto", "description": "Avance o evidencia", "required": True},
            ],
        },
        {
            "name": "inneros-aprobar",
            "description": "Solicitar aprobacion operativa controlada",
            "options": [
                {"type": 3, "name": "texto", "description": "Decision o accion a aprobar", "required": True},
            ],
        },
    ]
    if dry_run:
        return {"ok": True, "dry_run": True, "guild_id": guild, "commands": commands}
    res = _request("PUT", f"/applications/{cfg['application_id']}/guilds/{guild}/commands", payload=commands)
    _audit("register_guild_commands", res, {"guild_id": guild})
    rows = res.get("data") if isinstance(res.get("data"), list) else []
    return {"ok": bool(res.get("ok")), "status": res.get("status"), "count": len(rows), "commands": [{"id": item.get("id"), "name": item.get("name")} for item in rows if isinstance(item, dict)], "error": res.get("error"), "detail": res.get("detail")}


def add_reaction(channel_id: str, message_id: str, emoji: str, dry_run: bool = True) -> dict[str, Any]:
    channel = (channel_id or "").strip()
    message = (message_id or "").strip()
    icon = (emoji or "").strip()
    if not channel or not message or not icon:
        return {"ok": False, "error": "channel_message_emoji_required"}
    encoded_emoji = urllib.parse.quote(icon, safe="")
    if dry_run:
        return {"ok": True, "dry_run": True, "channel_id": channel, "message_id": message, "emoji": icon}
    res = _request("PUT", f"/channels/{channel}/messages/{message}/reactions/{encoded_emoji}/@me")
    _audit("add_reaction", res, {"channel_id": channel, "message_id": message})
    return {"ok": bool(res.get("ok")), "status": res.get("status"), "error": res.get("error"), "detail": res.get("detail")}


def send_channel_message(channel_id: str = "", content: str = "", dry_run: bool = True) -> dict[str, Any]:
    cfg = _config()
    channel = (channel_id or cfg["default_channel_id"]).strip()
    text = (content or "").strip()
    if not channel or not text:
        return {"ok": False, "error": "channel_id_and_content_required"}
    if dry_run:
        return {"ok": True, "dry_run": True, "channel_id": channel, "content_preview": text[:500]}
    res = _request("POST", f"/channels/{channel}/messages", payload={"content": text[:1900]})
    _audit("send_channel_message", res, {"channel_id": channel})
    return {"ok": bool(res.get("ok")), "status": res.get("status"), "message_id": (res.get("data") or {}).get("id") if isinstance(res.get("data"), dict) else None, "error": res.get("error")}


def send_webhook_message(content: str, dry_run: bool = True) -> dict[str, Any]:
    webhook, source = _secret(WEBHOOK_URL_KEY)
    text = (content or "").strip()
    if not webhook:
        return {"ok": False, "error": "discord_webhook_missing", "webhook_source": source, "hint": "store webhook with local_discord_store_webhook_url_server_side"}
    if not text:
        return {"ok": False, "error": "content_required"}
    if dry_run:
        return {"ok": True, "dry_run": True, "webhook_source": source, "content_preview": text[:500]}
    req = urllib.request.Request(webhook, data=json.dumps({"content": text[:1900]}).encode("utf-8"), method="POST", headers={"Content-Type": "application/json", "User-Agent": "InnerOS-Discord-Plane/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = {"ok": 200 <= resp.status < 300, "status": resp.status, "webhook_source": source}
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "status": exc.code, "error": "discord_webhook_http_error", "detail": _redact(exc.read().decode("utf-8", errors="replace")[:1000]), "webhook_source": source}
    except urllib.error.URLError as exc:
        result = {"ok": False, "error": "discord_webhook_unreachable", "detail": _redact(str(exc.reason)), "webhook_source": source}
    _audit("send_webhook_message", result)
    return result


def resource_provider_document() -> dict[str, Any]:
    status = discord_status()
    return {
        "provider_id": PROVIDER_ID,
        "label": "Discord Ops Bridge",
        "kind": "ops_communication_provider",
        "capabilities": ["ops_alerts", "approval_requests", "community_updates", "incident_notifications", "slash_commands", "read_recent_messages", "search_recent_messages", "channel_management", "webhooks", "threads"],
        "interaction_gateway": "/discord/interactions",
        "local_first": False,
        "status": "active" if (status.get("auth_ok") or status.get("webhook_present")) else "configured_needs_token_or_webhook",
        "requires": ["Discord bot token or channel webhook in owner_vault", "guild/channel IDs for production routing"],
        "cost_policy": "external_messaging_only_no_model_spend",
        "verified_user": status.get("bot_user"),
        "updated_at": _now(),
        "registry_version": "resource_fabric_v1",
    }


def register_resource_provider(dry_run: bool = False) -> dict[str, Any]:
    provider = resource_provider_document()
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": provider}
    now = _now()
    provider["updated_at"] = now
    mongo_store.get_db()["inneros_resource_providers"].update_one({"provider_id": provider["provider_id"]}, {"$set": provider, "$setOnInsert": {"created_at": now}}, upsert=True)
    _audit("register_resource_provider", {"ok": True, "provider_id": PROVIDER_ID})
    return {"ok": True, "provider": provider}
