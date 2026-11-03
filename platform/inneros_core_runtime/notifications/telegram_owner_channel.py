"""Telegram como canal owner (reemplazo WhatsApp): texto, voz, botones."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from raphiia_openai.notifications.settings import NOTIFY_WHATSAPP_TO


def _owner_digits() -> set[str]:
    out: set[str] = set()
    for raw in (
        os.getenv("RALFIA_ALERTS_TO"),
        os.getenv("NOTIFY_WHATSAPP_TO"),
        NOTIFY_WHATSAPP_TO,
    ):
        digits = "".join(c for c in str(raw or "") if c.isdigit())
        if digits:
            out.add(digits)
    return out


def is_owner_destination(number: str | None) -> bool:
    digits = "".join(c for c in str(number or "") if c.isdigit())
    if not digits:
        return True  # alertas sin destino explícito → owner
    owners = _owner_digits()
    if not owners:
        return True
    return digits in owners or any(digits.endswith(o[-10:]) for o in owners)


def synthesize_voice_ogg(text: str, *, voice: str | None = None) -> tuple[bytes | None, str | None]:
    from raphiia_openai.voice_gateway import _synthesize_reply

    snippet = (text or "").strip()[:2000]
    if not snippet:
        return None, "empty_text"
    with tempfile.TemporaryDirectory(prefix="ralfia-tg-voice-") as tmpdir:
        wav_path, err = _synthesize_reply(snippet, voice=voice)
        if not wav_path or not Path(wav_path).is_file():
            return None, err or "tts_failed"
        src = Path(wav_path)
        ogg = Path(tmpdir) / "reply.ogg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-c:a", "libopus", "-b:a", "48k", str(ogg)],
                capture_output=True,
                timeout=45,
                check=True,
            )
            return ogg.read_bytes(), None
        except Exception:
            return src.read_bytes(), "wav_fallback"


def deliver_owner_message(
    text: str,
    *,
    chat_id: str | None = None,
    reply_voice: bool | None = None,
    inline_ops_task_id: str | None = None,
) -> dict[str, Any]:
    from inneros_core_runtime.notifications import telegram_client as tg

    if not tg.telegram_enabled():
        return {"ok": False, "skipped": "telegram_disabled"}
    if not tg._bot_token():
        return {"ok": False, "skipped": "telegram_not_configured"}
    body = (text or "").strip()[:4000]
    if not body:
        return {"ok": False, "skipped": "empty"}
    markup = tg.ops_auth_inline_keyboard(inline_ops_task_id) if inline_ops_task_id else None
    msg = tg.send_message(body, chat_id=chat_id, reply_markup=markup, parse_mode="")
    voice = reply_voice
    if voice is None:
        voice = os.getenv("TELEGRAM_REPLY_VOICE", "1").strip().lower() in {"1", "true", "yes", "on"}
    voice_out: dict[str, Any] = {"ok": False, "skipped": "not_requested"}
    if voice:
        raw, err = synthesize_voice_ogg(body)
        if raw:
            voice_out = tg.send_voice(raw, chat_id=chat_id, caption="")
        else:
            voice_out = {"ok": False, "error": err or "voice_failed"}
    ok = bool(msg.get("ok") or voice_out.get("ok"))
    return {"ok": ok, "telegram_text": msg, "telegram_voice": voice_out, "channel": "telegram"}


def deliver_owner_buttons(text: str, buttons: list[dict[str, str]], *, task_id: str = "") -> dict[str, Any]:
    tid = task_id or ""
    for b in buttons:
        bid = str(b.get("id") or "")
        if bid.startswith("ops.auth.") and "ops_" in bid:
            tid = bid.split(".")[-1]
            break
    return deliver_owner_message(text, reply_voice=False, inline_ops_task_id=tid or None)
