"""Adaptador Band LIVE — colaboración real entre agentes vía REST."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from hackathon_band import config
from hackathon_band.console_log import log as clog
from hackathon_band.exceptions import HackathonConfigError, HackathonIntegrationError
from hackathon_band.validate import require_config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def band_mode() -> str:
    return "LIVE"


def _audit_path(chat_id: str) -> Path:
    """Cache local solo para audit trail UI — NO simula Band."""
    return config.BAND_AUDIT_DIR / f"{chat_id}.json"


def _append_audit(chat_id: str, msg: dict[str, Any]) -> None:
    path = _audit_path(chat_id)
    data = {"chat_id": chat_id, "messages": []}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("messages", []).append(msg)
    data["updated_at"] = _now_iso()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _agent_api_key(agent_key: str) -> str:
    agent = config.AGENTS.get(agent_key, {})
    key = (agent.get("api_key") or "").strip()
    if not key:
        raise HackathonConfigError(
            [f"BAND_API_KEY_{agent_key.upper()}"],
            hint=(
                f"Falta API key del agente {agent_key}. "
                "En Band, cada agente tiene su propia API key (no uses band_u_* de usuario)."
            ),
        )
    return key


def _band_headers(agent_key: str = "router") -> dict[str, str]:
    return {
        "X-API-Key": _agent_api_key(agent_key),
        "Content-Type": "application/json",
    }


def add_participant(chat_id: str, participant_id: str, *, as_agent: str = "router") -> None:
    """Añade un agente/usuario a la sala (requerido antes de @mentions)."""
    url = f"{config.BAND_REST_URL}/api/v1/agent/chats/{chat_id}/participants"
    payload = {"participant": {"participant_id": participant_id, "role": "member"}}
    try:
        res = requests.post(
            url, headers=_band_headers(as_agent), json=payload, timeout=30
        )
        if res.ok or res.status_code == 409:
            clog("info", "band", f"Participant added: {participant_id[:8]}…")
            return
        raise HackathonIntegrationError(
            "Band",
            f"add_participant HTTP {res.status_code}: {res.text[:300]}",
        )
    except HackathonIntegrationError:
        raise
    except requests.RequestException as exc:
        raise HackathonIntegrationError("Band", f"add_participant: {exc}") from exc


def ensure_hackathon_participants(chat_id: str) -> None:
    """Registra los 4 agentes del pipeline en la sala Band."""
    seen: set[str] = set()
    for key, agent in config.AGENTS.items():
        band_id = (agent.get("band_id") or "").strip()
        if not band_id or band_id in seen:
            continue
        seen.add(band_id)
        add_participant(chat_id, band_id, as_agent="router")


def create_chat(title: str = "Hackathon Band") -> dict[str, Any]:
    require_config()
    url = f"{config.BAND_REST_URL}/api/v1/agent/chats"
    try:
        res = requests.post(
            url,
            headers=_band_headers("router"),
            json={"chat": {"title": title[:120]}},
            timeout=30,
        )
        if not res.ok:
            raise HackathonIntegrationError(
                "Band",
                f"create_chat HTTP {res.status_code}: {res.text[:300]}",
            )
        data = res.json()
        chat_obj = data.get("data") or data.get("chat") or data
        chat_id = chat_obj.get("id") or data.get("id") or data.get("chat_id")
        if not chat_id:
            raise HackathonIntegrationError("Band", f"create_chat sin id: {data}")
        ensure_hackathon_participants(chat_id)
        clog("success", "band", f"Chat room created: {chat_id}", title=title[:60])
        return {"chat_id": chat_id, "mode": "LIVE", "raw": data}
    except HackathonIntegrationError:
        raise
    except requests.RequestException as exc:
        raise HackathonIntegrationError("Band", f"create_chat: {exc}") from exc


def send_message(
    chat_id: str,
    *,
    agent_key: str,
    content: str,
    mention_keys: list[str] | None = None,
) -> dict[str, Any]:
    require_config()
    agent = config.AGENTS.get(agent_key, {})
    agent_name = agent.get("name", agent_key)
    mentions = mention_keys or []
    mention_tags = " ".join(
        f"@{config.AGENTS[k]['name']}" for k in mentions if k in config.AGENTS
    )
    full_content = f"{mention_tags}\n{content}".strip() if mention_tags else content

    band_agent_id = (agent.get("band_id") or "").strip()
    if not band_agent_id:
        env_name = {
            "router": "BAND_AGENT_ID_ROUTER",
            "memory": "BAND_AGENT_ID_MEMORY",
            "analyst": "BAND_AGENT_ID_ANALYST",
            "documentation": "BAND_AGENT_ID_DOCUMENTATION",
        }.get(agent_key, f"BAND_AGENT_ID_{agent_key.upper()}")
        raise HackathonConfigError(
            [env_name],
            hint=f"Falta UUID Band para agente {agent_key}",
        )

    url = f"{config.BAND_REST_URL}/api/v1/agent/chats/{chat_id}/messages"
    mention_payload = [
        {
            "id": config.AGENTS[k]["band_id"],
            "name": config.AGENTS[k]["name"],
        }
        for k in mentions
        if k in config.AGENTS and config.AGENTS[k].get("band_id")
    ]
    if not mention_payload:
        mention_payload = [
            {"id": band_agent_id, "name": agent_name, "kind": "reference"}
        ]
    elif any(m.get("kind") != "reference" for m in mention_payload):
        # Band exige @ real en contenido para mentions activos
        tags = " ".join(
            f"@{m['name']}" for m in mention_payload if m.get("kind") != "reference"
        )
        if tags and tags not in full_content:
            full_content = f"{tags}\n{full_content}".strip()
    payload = {
        "message": {
            "content": full_content,
            "mentions": mention_payload,
        }
    }

    try:
        res = requests.post(url, headers=_band_headers(agent_key), json=payload, timeout=60)
        if not res.ok:
            raise HackathonIntegrationError(
                "Band",
                f"send_message HTTP {res.status_code}: {res.text[:300]}",
            )
        band_response = res.json()
        clog(
            "success",
            "band",
            f"Message sent as @{agent_name}",
            agent_key=agent_key,
            mentions=mentions,
        )
    except HackathonIntegrationError:
        raise
    except requests.RequestException as exc:
        raise HackathonIntegrationError("Band", f"send_message: {exc}") from exc

    msg = {
        "id": str(uuid.uuid4()),
        "agent_key": agent_key,
        "agent_id": agent.get("id"),
        "agent_name": agent_name,
        "content": full_content,
        "mentions": mentions,
        "timestamp": _now_iso(),
        "band_mode": "LIVE",
        "band_response": band_response,
    }
    _append_audit(chat_id, msg)
    return msg


def get_messages(chat_id: str) -> list[dict[str, Any]]:
    require_config()
    url = f"{config.BAND_REST_URL}/api/v1/agent/chats/{chat_id}/messages"
    try:
        res = requests.get(url, headers=_band_headers("router"), timeout=30)
        if res.ok:
            data = res.json()
            if isinstance(data, list) and data:
                return data
            if isinstance(data, dict) and data.get("messages"):
                return data["messages"]
    except requests.RequestException:
        pass

    path = _audit_path(chat_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("messages") or []
    return []


def status() -> dict[str, Any]:
    from hackathon_band.validate import missing_vars, readiness

    return {
        "band_mode": band_mode(),
        "band_rest_url": config.BAND_REST_URL,
        "ready": readiness()["ready"],
        "missing": missing_vars(),
        "agents": {
            k: {"code": v["id"], "name": v["name"], "band_id_set": bool(v.get("band_id"))}
            for k, v in config.AGENTS.items()
        },
    }
