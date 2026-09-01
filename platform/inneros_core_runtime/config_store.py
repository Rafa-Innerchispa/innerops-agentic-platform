"""Configuración Ralphi IA — panel :2002 → Mongo → sync .env (sin copiar/pegar SSH)."""

from __future__ import annotations

import builtins
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.settings import ROOT

COL_APP_CONFIG = "ralfia_app_config"
ENV_PATH = ROOT / ".env"

# Catálogo canónico — misma forma en todos los proyectos Ralphi IA
CONFIG_CATALOG: list[dict[str, Any]] = [
    {
        "key": "LINKEDIN_ACCESS_TOKEN",
        "label": "LinkedIn — Access Token",
        "group": "editorial",
        "secret": True,
        "required": True,
        "help": "Developer Portal → OAuth token con w_member_social",
    },
    {
        "key": "LINKEDIN_AUTHOR_URN",
        "label": "LinkedIn — URN default (persona)",
        "group": "editorial",
        "secret": False,
        "required": False,
        "help": "urn:li:person:… — fallback si la entidad no tiene URN propio",
        "placeholder": "urn:li:person:XXXXXXXX",
    },
    {
        "key": "LINKEDIN_CLIENT_ID",
        "label": "LinkedIn OAuth — Client ID",
        "group": "editorial",
        "secret": False,
        "required": False,
        "help": "LinkedIn Developer Portal → Auth → Client ID",
    },
    {
        "key": "LINKEDIN_CLIENT_SECRET",
        "label": "LinkedIn OAuth — Client Secret",
        "group": "editorial",
        "secret": True,
        "required": False,
        "help": "LinkedIn Developer Portal → Auth → Client Secret",
    },
    {
        "key": "LINKEDIN_REDIRECT_URI",
        "label": "LinkedIn OAuth — Redirect URI",
        "group": "editorial",
        "secret": False,
        "required": False,
        "placeholder": "https://www.linkedin.com/developers/tools/oauth/redirect",
        "help": "Debe coincidir exactamente con Authorized redirect URLs de la app LinkedIn.",
    },
    {
        "key": "LINKEDIN_PERSONAL_CLIENT_ID",
        "label": "LinkedIn OAuth personal — Client ID",
        "group": "editorial",
        "secret": False,
        "required": False,
        "help": "App con Sign in with LinkedIn + Sharing on LinkedIn para perfil personal.",
    },
    {
        "key": "LINKEDIN_PERSONAL_CLIENT_SECRET",
        "label": "LinkedIn OAuth personal — Client Secret",
        "group": "editorial",
        "secret": True,
        "required": False,
        "help": "Se usa para renovar token de perfil personal.",
    },
    {
        "key": "LINKEDIN_ORG_CLIENT_ID",
        "label": "LinkedIn OAuth páginas — Client ID",
        "group": "editorial",
        "secret": False,
        "required": False,
        "help": "App con Community Management para publicar como organización.",
    },
    {
        "key": "LINKEDIN_ORG_CLIENT_SECRET",
        "label": "LinkedIn OAuth páginas — Client Secret",
        "group": "editorial",
        "secret": True,
        "required": False,
        "help": "Se usa para renovar token con w_organization_social.",
    },
    {
        "key": "GOOGLE_API_KEY",
        "label": "Google AI / Imagen (Gemini)",
        "group": "editorial",
        "secret": True,
        "required": False,
        "help": "AI Studio — imágenes editoriales en servidor",
    },
    {
        "key": "IMAGE_GEN_PROVIDER",
        "label": "Imagen — provider principal",
        "group": "editorial",
        "secret": False,
        "required": False,
        "placeholder": "google",
        "help": "google | local_comfy | automatic1111 | placeholder",
    },
    {
        "key": "LOCAL_IMAGE_PROVIDER",
        "label": "Imagen local — backend",
        "group": "editorial",
        "secret": False,
        "required": False,
        "placeholder": "comfyui",
        "help": "comfyui | automatic1111",
    },
    {
        "key": "COMFYUI_URL",
        "label": "ComfyUI — URL",
        "group": "editorial",
        "secret": False,
        "required": False,
        "placeholder": "http://127.0.0.1:8188",
    },
    {
        "key": "COMFYUI_CHECKPOINT",
        "label": "ComfyUI — checkpoint",
        "group": "editorial",
        "secret": False,
        "required": False,
        "placeholder": "sdxl_turbo.safetensors",
    },
    {
        "key": "AUTOMATIC1111_URL",
        "label": "Automatic1111 — URL",
        "group": "editorial",
        "secret": False,
        "required": False,
        "placeholder": "http://127.0.0.1:7860",
    },
    {
        "key": "MCP_API_KEY",
        "label": "MCP — API Key (ChatGPT conector)",
        "group": "mcp",
        "secret": True,
        "required": True,
        "help": "Se aplica al guardar — el panel reinicia ralfia-mcp automáticamente",
        "restart_units": ["ralfia-mcp.service"],
    },
    {
        "key": "GOOGLE_CLIENT_ID",
        "label": "Google OAuth — Client ID (voz.pcdoctor.ai)",
        "group": "voice",
        "secret": False,
        "required": False,
        "help": "Cloud Console → OAuth 2.0 Web client. Redirect: https://voz.pcdoctor.ai/api/voice/auth/google/callback",
        "restart_units": ["ralfia-voice-gateway.service"],
    },
    {
        "key": "GOOGLE_CLIENT_SECRET",
        "label": "Google OAuth — Client Secret",
        "group": "voice",
        "secret": True,
        "required": False,
        "help": "Par con GOOGLE_CLIENT_ID para login Google en RalfIA Voz",
        "restart_units": ["ralfia-voice-gateway.service"],
    },
    {
        "key": "VOICE_OAUTH_REDIRECT_URI",
        "label": "Google OAuth — Redirect URI voz",
        "group": "voice",
        "secret": False,
        "required": False,
        "placeholder": "https://voz.pcdoctor.ai/api/voice/auth/google/callback",
        "help": "Debe coincidir exactamente con Google Cloud Console",
        "restart_units": ["ralfia-voice-gateway.service"],
    },
    {
        "key": "EVOLUTION_BASE_URL",
        "label": "Evolution API — URL",
        "group": "notifications",
        "secret": False,
        "required": False,
        "placeholder": "http://192.168.1.4:8082",
    },
    {
        "key": "EVOLUTION_API_KEY",
        "label": "Evolution API — Key",
        "group": "notifications",
        "secret": True,
        "required": False,
    },
    {
        "key": "EVOLUTION_INSTANCE",
        "label": "Evolution — instancia WhatsApp",
        "group": "notifications",
        "secret": False,
        "required": False,
        "placeholder": "RalphiIA-pcdoctor",
    },
    {
        "key": "NOTIFY_WHATSAPP_TO",
        "label": "WhatsApp alertas — número",
        "group": "notifications",
        "secret": False,
        "required": False,
        "placeholder": "593988959606",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get(key: str, default: str = "") -> str:
    """Mongo primero, luego .env en disco, luego default."""
    key = key.strip()
    if not key:
        return default
    try:
        db = mongo_store.get_db()
        doc = db[COL_APP_CONFIG].find_one({"_id": key}, {"value": 1})
        if doc and doc.get("value") not in (None, ""):
            return str(doc["value"])
    except Exception:
        pass
    env_val = os.getenv(key, "")
    if env_val:
        return env_val
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            m = re.match(rf"^{re.escape(key)}=(.*)$", line.strip())
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return default


def get_google_api_key() -> str:
    return get("GOOGLE_API_KEY") or get("GEMINI_API_KEY")


def set(key: str, value: str, *, updated_by: str = "PANEL", sync_env: bool = True) -> dict[str, Any]:
    return set_values({key: value}, updated_by=updated_by, sync_env=sync_env)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "••••••"
    return "••••" + value[-4:]


def _is_masked_placeholder(value: str) -> bool:
    return bool(value) and value.startswith("••••")


def _normalize_oauth_secret(val: str) -> str:
    s = (val or "").strip()
    if len(s) >= 2 and s[: len(s) // 2] == s[len(s) // 2 :]:
        return s[: len(s) // 2]
    return s


def set_values(
    updates: dict[str, str],
    *,
    updated_by: str = "PANEL",
    sync_env: bool = True,
) -> dict[str, Any]:
    """Guarda claves en Mongo y opcionalmente sincroniza .env."""
    db = mongo_store.get_db()
    now = _now_iso()
    applied: list[str] = []
    env_patch: dict[str, str] = {}
    allowed = {c["key"] for c in CONFIG_CATALOG}

    for key, raw in updates.items():
        if key not in allowed:
            continue
        if _is_masked_placeholder(raw):
            continue
        val = (raw or "").strip()
        if key == "GOOGLE_CLIENT_SECRET":
            val = _normalize_oauth_secret(val)
        db[COL_APP_CONFIG].update_one(
            {"_id": key},
            {
                "$set": {
                    "key": key,
                    "value": val,
                    "updated_at": now,
                    "updated_by": updated_by,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        applied.append(key)
        env_patch[key] = val
        if key == "GOOGLE_API_KEY" and val:
            env_patch["GEMINI_API_KEY"] = val

    if sync_env and env_patch:
        _sync_env_file(env_patch)

    restarts: list[dict[str, Any]] = []
    if applied:
        from raphiia_openai import service_control

        restarts = service_control.restart_for_config_keys(applied)

    mongo_store.log_coordination(
        agent=updated_by,
        summary=f"Config panel: {', '.join(applied)}" + (f" · reinicios: {len(restarts)}" if restarts else ""),
        event="config_update",
        project="ralfia-ops",
        metadata={"keys": applied, "restarts": restarts},
    )
    restart_msg = ""
    if restarts:
        ok_n = sum(1 for r in restarts if r.get("ok"))
        names = ", ".join(r["unit"].replace(".service", "") for r in restarts)
        restart_msg = (
            f"Reiniciados {ok_n}/{len(restarts)} ({names}). "
            "Agente de recuperación verificando — recibirás WhatsApp cuando esté OK."
        )
    return {
        "ok": True,
        "updated": applied,
        "restarts": restarts,
        "restart_message": restart_msg,
        "recovery_scheduled": bool(restarts),
    }


def _sync_env_file(updates: dict[str, str]) -> None:
    """Merge keys into .env without borrar el resto."""
    if not ENV_PATH.is_file():
        lines = [f"{k}={v}\n" for k, v in updates.items()]
        ENV_PATH.write_text("".join(lines), encoding="utf-8")
        return

    text = ENV_PATH.read_text(encoding="utf-8")
    out_lines: list[str] = []
    seen: builtins.set[str] = builtins.set()
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line if line.endswith("\n") else line + "\n")
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
        if m and m.group(1) in updates:
            k = m.group(1)
            seen.add(k)
            out_lines.append(f"{k}={updates[k]}\n")
        else:
            out_lines.append(line if line.endswith("\n") else line + "\n")
    for k, v in updates.items():
        if k not in seen:
            out_lines.append(f"{k}={v}\n")
    ENV_PATH.write_text("".join(out_lines), encoding="utf-8")
    for k, v in updates.items():
        os.environ[k] = v


def status_catalog() -> dict[str, Any]:
    """Estado visual para panel — qué falta configurar."""
    groups: dict[str, list[dict[str, Any]]] = {}
    missing_required = 0
    configured = 0
    for item in CONFIG_CATALOG:
        key = item["key"]
        val = get(key)
        if key == "GOOGLE_API_KEY" and not val:
            val = get("GEMINI_API_KEY")
        ok = bool(val)
        if item.get("required") and not ok:
            missing_required += 1
        if ok:
            configured += 1
        row = {
            **item,
            "configured": ok,
            "display_value": mask_secret(val) if item.get("secret") and val else (val[:60] if val else ""),
        }
        groups.setdefault(item["group"], []).append(row)
    return {
        "ok": missing_required == 0,
        "configured_count": configured,
        "total_count": len(CONFIG_CATALOG),
        "missing_required": missing_required,
        "groups": groups,
        "source": "mongo+env",
        "env_path": str(ENV_PATH),
    }


def list_entities_editorial() -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    rows = list(db.entities.find({"status": "active"}, {"_id": 0}).sort("name", 1))
    default_urn = get("LINKEDIN_AUTHOR_URN")
    default_token = bool(get("LINKEDIN_ACCESS_TOKEN"))
    out = []
    for ent in rows:
        urn = (ent.get("linkedin_author_urn") or "").strip()
        out.append(
            {
                **ent,
                "linkedin_ready": default_token and bool(urn or default_urn),
                "linkedin_urn_display": urn or default_urn or "",
            }
        )
    return out


def patch_entity(entity_id: str, patch: dict[str, Any], *, updated_by: str = "PANEL") -> dict[str, Any]:
    db = mongo_store.get_db()
    if not db.entities.find_one({"entity_id": entity_id}):
        return {"ok": False, "error": "entidad no encontrada"}
    allowed = {
        "name",
        "linkedin_author_urn",
        "linkedin_publish_as",
        "notes",
        "status",
    }
    doc_patch = {k: v for k, v in patch.items() if k in allowed}
    if "linkedin_author_urn" in doc_patch:
        doc_patch["linkedin_author_urn"] = str(doc_patch["linkedin_author_urn"] or "").strip()
    if "linkedin_publish_as" in doc_patch:
        doc_patch["linkedin_publish_as"] = str(doc_patch["linkedin_publish_as"] or "").strip()
    doc_patch["updated_at"] = _now_iso()
    db.entities.update_one({"entity_id": entity_id}, {"$set": doc_patch})
    doc = db.entities.find_one({"entity_id": entity_id}, {"_id": 0})
    return {"ok": True, "entity": doc}
