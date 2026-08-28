"""Discord interaction gateway for slash commands.

The HTTP route validates Discord Ed25519 signatures before dispatching any
command. Commands are intentionally allowlisted and auditable; this gateway is
not a general shell or MCP execution bridge.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from raphiia_openai import local_discord_plane, mongo_store

COL_AUDIT = "ralfia_discord_interactions"
MAX_TIMESTAMP_SKEW_SECONDS = 300

INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE = 4
FLAG_EPHEMERAL = 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, result: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    try:
        mongo_store.get_db()[COL_AUDIT].insert_one(
            {
                "action": action,
                "result_ok": bool(result.get("ok")),
                "result": {k: v for k, v in result.items() if k not in {"raw_body", "headers"}},
                "metadata": metadata or {},
                "created_at": _now(),
            }
        )
    except Exception:
        pass


def _response(content: str, ephemeral: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {"content": content[:1900]}
    if ephemeral:
        data["flags"] = FLAG_EPHEMERAL
    return {"type": RESPONSE_CHANNEL_MESSAGE, "data": data}


def _options(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    out: dict[str, Any] = {}
    for item in data.get("options") or []:
        if isinstance(item, dict) and item.get("name"):
            out[str(item["name"])] = item.get("value")
    return out


def _command_name(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("name") or "").strip().lower()


def verify_signature(raw_body: bytes, signature: str, timestamp: str, public_key: str) -> dict[str, Any]:
    if not signature or not timestamp or not public_key:
        return {"ok": False, "error": "missing_signature_headers_or_public_key"}
    try:
        ts = int(timestamp)
    except ValueError:
        return {"ok": False, "error": "invalid_timestamp"}
    if abs(int(time.time()) - ts) > MAX_TIMESTAMP_SKEW_SECONDS:
        return {"ok": False, "error": "timestamp_out_of_window"}
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        key.verify(bytes.fromhex(signature), timestamp.encode("utf-8") + raw_body)
    except (ValueError, InvalidSignature):
        return {"ok": False, "error": "bad_request_signature"}
    return {"ok": True}


def endpoint_status() -> dict[str, Any]:
    status = local_discord_plane.discord_status()
    configured = bool(status.get("application_id") and status.get("public_key_present"))
    return {
        "ok": True,
        "configured": configured,
        "application_id": status.get("application_id"),
        "bot_auth_ok": bool(status.get("auth_ok")),
        "supported_commands": ["inneros-status", "inneros-novedad", "inneros-hackathon", "inneros-aprobar"],
        "security": {
            "ed25519_signature_required": True,
            "timestamp_window_seconds": MAX_TIMESTAMP_SKEW_SECONDS,
            "allowlisted_commands_only": True,
            "arbitrary_execution": False,
        },
    }


def handle_interaction(raw_body: bytes, signature: str, timestamp: str) -> tuple[int, dict[str, Any]]:
    cfg = local_discord_plane._config()
    verified = verify_signature(raw_body, signature, timestamp, cfg.get("public_key") or "")
    if not verified.get("ok"):
        result = {"ok": False, **verified}
        _audit("verify_failed", result)
        return 401, {"error": verified.get("error")}

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return 400, {"error": "invalid_json"}

    interaction_type = payload.get("type")
    if interaction_type == INTERACTION_PING:
        _audit("ping", {"ok": True})
        return 200, {"type": RESPONSE_PONG}
    if interaction_type != INTERACTION_APPLICATION_COMMAND:
        return 200, _response("InnerOS: interaction type not supported yet.")

    name = _command_name(payload)
    options = _options(payload)
    result = _dispatch_command(name, options, payload)
    _audit("command", result, {"command": name, "guild_id": payload.get("guild_id"), "channel_id": payload.get("channel_id")})
    return 200, result["discord_response"]


def _dispatch_command(name: str, options: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if name == "inneros-status":
        status = endpoint_status()
        content = (
            "InnerOS Discord gateway activo. "
            f"Bot auth: {'OK' if status.get('bot_auth_ok') else 'pendiente'}. "
            "Comandos: status, novedad, hackathon, aprobar."
        )
        return {"ok": True, "discord_response": _response(content)}

    if name == "inneros-novedad":
        text = str(options.get("texto") or "").strip()
        channel = str(options.get("canal") or "novedades").strip()
        if not text:
            return {"ok": False, "discord_response": _response("Falta el texto de la novedad.")}
        sent = local_discord_plane.send_named_channel_message(channel=channel, content=text, dry_run=False)
        if sent.get("ok"):
            return {"ok": True, "discord_response": _response(f"Novedad publicada en #{channel}.")}
        return {"ok": False, "discord_response": _response(f"No pude publicar la novedad: {sent.get('error') or sent.get('detail') or 'error desconocido'}")}

    if name == "inneros-hackathon":
        text = str(options.get("texto") or "").strip()
        if not text:
            return {"ok": False, "discord_response": _response("Falta el texto del avance de hackathon.")}
        sent = local_discord_plane.send_named_channel_message(channel="hackathons", content=text, dry_run=False)
        if sent.get("ok"):
            return {"ok": True, "discord_response": _response("Avance de hackathon publicado.")}
        return {"ok": False, "discord_response": _response(f"No pude publicar en hackathons: {sent.get('error') or sent.get('detail') or 'error desconocido'}")}

    if name == "inneros-aprobar":
        text = str(options.get("texto") or "").strip()
        if not text:
            return {"ok": False, "discord_response": _response("Falta el texto de la aprobacion solicitada.")}
        record = {
            "ok": True,
            "kind": "approval_request",
            "text": text[:1900],
            "discord_user_id": (payload.get("member") or {}).get("user", {}).get("id") if isinstance(payload.get("member"), dict) else None,
            "created_at": _now(),
        }
        _audit("approval_request", record)
        sent = local_discord_plane.send_named_channel_message(channel="ops-alerts", content=f"Approval request: {text[:1800]}", dry_run=False)
        if sent.get("ok"):
            return {"ok": True, "discord_response": _response("Solicitud enviada a ops-alerts.")}
        return {"ok": False, "discord_response": _response("Solicitud registrada, pero no pude publicar en ops-alerts.")}

    return {"ok": False, "discord_response": _response("Comando no reconocido por InnerOS.")}
