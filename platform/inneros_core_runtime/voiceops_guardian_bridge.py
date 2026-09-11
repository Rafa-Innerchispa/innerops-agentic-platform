"""Bounded WhatsApp -> Physical Guardian -> VoiceOps bridge.

This module does not own cameras, WhatsApp credentials, AssemblyAI credentials or
Service Operations. It binds an authenticated owner's voice-note transcript to
one sanitized Guardian event, then calls the private VoiceOps bridge.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from raphiia_openai import mongo_store, whatsapp_evolution_parse as evo

PENDING_COL = "voiceops_guardian_whatsapp_pending"
DEFAULT_GUARDIAN_EVENTS_URL = "http://127.0.0.1:8788/api/events/recent"
DEFAULT_VOICEOPS_URL = "http://127.0.0.1:8791/api/guardian/voice-command"
EVENT_REF_RE = re.compile(r"(?:^|\n)\s*(?:ref|referencia)\s*:\s*([A-Za-z0-9._:-]{4,160})\s*(?:$|\n)", re.I)
_EVENT_FIELDS = {
    "event_id",
    "source_id",
    "event_type",
    "severity",
    "occurred_at",
    "tenant_id",
    "site_id",
    "zone_id",
    "confidence",
    "evidence_refs",
}


def extract_event_ref(text: str) -> str:
    match = EVENT_REF_RE.search(text or "")
    return match.group(1).strip() if match else ""


def conversation_ref(value: str) -> str:
    return "wa-guardian-" + hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:24]


def _bridge_token() -> str:
    token_file = os.getenv("VOICEOPS_BRIDGE_TOKEN_FILE", "").strip()
    if not token_file:
        raise RuntimeError("voiceops_bridge_token_file_not_configured")
    path = Path(token_file).expanduser()
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 24:
        raise RuntimeError("voiceops_bridge_token_invalid")
    return token


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    safe = {key: event.get(key) for key in _EVENT_FIELDS if key in event}
    required = ("event_id", "source_id", "event_type", "severity", "occurred_at")
    if any(not str(safe.get(key) or "").strip() for key in required):
        raise ValueError("Guardian event is incomplete")
    confidence = safe.get("confidence")
    if confidence is not None:
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Guardian event confidence is invalid")
        safe["confidence"] = confidence
    refs = safe.get("evidence_refs")
    if refs is not None and not isinstance(refs, list):
        safe.pop("evidence_refs", None)
    rendered = repr(safe).lower()
    if any(term in rendered for term in ("rtsp://", "password", "credential", "authorization", "base64")):
        raise ValueError("Guardian event contains private transport material")
    return safe


def fetch_guardian_event(
    event_id: str,
    *,
    events_url: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    wanted = str(event_id or "").strip()
    if not wanted:
        raise ValueError("Guardian event ref is required")
    url = events_url or os.getenv("PHYSICAL_GUARDIAN_EVENTS_URL", DEFAULT_GUARDIAN_EVENTS_URL)
    with opener(Request(url, method="GET"), timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise RuntimeError("Guardian recent-events response is invalid")
    for event in events:
        if isinstance(event, dict) and str(event.get("event_id") or "") == wanted:
            return _sanitize_event(event)
    raise LookupError("Guardian event ref not found")


def submit_voiceops_command(
    event: dict[str, Any],
    transcript: str,
    *,
    voiceops_url: str | None = None,
    token: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    text = str(transcript or "").strip()
    if not text:
        raise ValueError("voice transcript is empty")
    secret = token if token is not None else _bridge_token()
    url = voiceops_url or os.getenv("VOICEOPS_GUARDIAN_BRIDGE_URL", DEFAULT_VOICEOPS_URL)
    request = Request(
        url,
        data=json.dumps({"event": _sanitize_event(event), "transcript": text}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
        method="POST",
    )
    with opener(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("VoiceOps bridge response is invalid")
    return payload


def _pending_get(ref: str) -> dict[str, Any] | None:
    row = mongo_store.get_db()[PENDING_COL].find_one({"conversation_ref": ref}, {"_id": 0})
    return dict(row) if isinstance(row, dict) else None


def _pending_set(ref: str, event: dict[str, Any]) -> None:
    mongo_store.get_db()[PENDING_COL].update_one(
        {"conversation_ref": ref},
        {"$set": {"conversation_ref": ref, "event_id": event["event_id"], "event": _sanitize_event(event), "status": "approval_pending"}},
        upsert=True,
    )


def _pending_clear(ref: str) -> None:
    mongo_store.get_db()[PENDING_COL].delete_one({"conversation_ref": ref})


def route_owner_voice_reply(
    payload: dict[str, Any],
    transcript: str,
    *,
    canonical_conversation_id: str,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    submitter: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Route one authenticated owner's WhatsApp voice note to exact Guardian event."""
    text = str(transcript or "").strip()
    if not text:
        return {"ok": False, "applicable": False, "reason": "empty_transcript"}
    ref = conversation_ref(canonical_conversation_id)
    quoted_text = evo.extract_quoted_text(payload)
    quoted_event_id = extract_event_ref(quoted_text)
    pending = _pending_get(ref)
    if quoted_event_id:
        if pending and str(pending.get("event_id") or "") != quoted_event_id:
            return {"ok": False, "applicable": True, "status": "event_switch_blocked", "event_id": str(pending.get("event_id") or "")}
        event = (fetcher or fetch_guardian_event)(quoted_event_id)
    elif pending and isinstance(pending.get("event"), dict):
        event = _sanitize_event(dict(pending["event"]))
        quoted_event_id = str(event.get("event_id") or "")
    else:
        return {"ok": True, "applicable": False, "reason": "no_guardian_event_ref_or_pending_event"}

    result = (submitter or submit_voiceops_command)(event, text)
    last = result.get("last_result") if isinstance(result.get("last_result"), dict) else {}
    status = str(last.get("status") or result.get("bridge_status") or "processed")
    if status in {"approval_required", "blocked"}:
        _pending_set(ref, event)
    elif status in {"completed", "already_completed"}:
        _pending_clear(ref)
    action = result.get("action") if isinstance(result.get("action"), dict) else {}
    return {
        "ok": True,
        "applicable": True,
        "status": status,
        "event_id": quoted_event_id,
        "action_id": action.get("action_id"),
        "production_writes": bool(result.get("production_writes", False)),
        "voiceops": result,
    }


def format_whatsapp_reply(result: dict[str, Any]) -> str:
    event_id = str(result.get("event_id") or "")
    status = str(result.get("status") or "")
    if status == "approval_required":
        return f"Ralphi revisó el incidente. Hay una acción propuesta que requiere autorización explícita.\nRef: {event_id}\nResponde por voz: Sí, autorizo."
    if status == "blocked":
        return f"No ejecuté la acción porque la autorización fue ambigua o insuficiente.\nRef: {event_id}\nPara continuar, responde: Sí, autorizo."
    if status in {"completed", "already_completed"}:
        action_id = str(result.get("action_id") or "acción registrada")
        return f"Listo. {action_id} quedó registrado y la evidencia de decisión fue sellada.\nRef: {event_id}"
    if status == "event_switch_blocked":
        return f"Hay otra incidencia esperando autorización. No mezclé los eventos.\nRef: {event_id}"
    return f"La nota de voz fue recibida, pero no ejecuté ninguna acción.\nRef: {event_id}" if event_id else "La nota de voz fue recibida, pero no ejecuté ninguna acción."
