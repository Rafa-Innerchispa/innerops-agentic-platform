"""Telegram Bot API — owner alerts and OPS auth (official API, no Baileys)."""

from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE = "https://api.telegram.org"
VAULT_KEY = "telegram_bot_token"
CHAT_STATE_KEY = "telegram_owner_chat_id"


def _bot_token() -> str:
    tok = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        from inneros_core_runtime import owner_vault

        for vault_key in (VAULT_KEY, "bot_token"):
            got = owner_vault.get_owner_credential(vault_key, category="telegram", reveal=True, actor="RAFAEL")
            if got.get("ok") and got.get("secret"):
                return str(got["secret"]).strip()
    except Exception:
        pass
    return ""


def owner_chat_id() -> str:
    cid = (os.getenv("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    if cid:
        return cid
    try:
        from raphiia_openai import mongo_store

        row = mongo_store.get_coordination_state(CHAT_STATE_KEY)
        st = (row.get("state") or {}) if row.get("ok") else {}
        return str(st.get("chat_id") or "").strip()
    except Exception:
        return ""


def persist_owner_chat_id(chat_id: str, *, actor: str = "telegram") -> None:
    cid = str(chat_id or "").strip()
    if not cid:
        return
    from raphiia_openai import mongo_store

    mongo_store.upsert_coordination_state(
        key=CHAT_STATE_KEY,
        data={"chat_id": cid, "updated_by": actor},
    )


def configured() -> bool:
    return bool(_bot_token() and owner_chat_id())


def telegram_enabled() -> bool:
    return os.getenv("NOTIFY_OPS_TELEGRAM", "1").strip().lower() not in {"0", "false", "no", "off"}


def _post(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "telegram_bot_token_missing"}
    url = f"{API_BASE}/bot{token}/{method}"
    try:
        r = httpx.post(url, json=payload, timeout=30.0)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:500]}
        ok = r.status_code == 200 and isinstance(body, dict) and body.get("ok") is True
        return {"ok": ok, "http_status": r.status_code, "response": body}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300]}


def send_message(
    text: str,
    *,
    chat_id: str | None = None,
    parse_mode: str = "Markdown",
    reply_markup: dict[str, Any] | None = None,
    disable_web_page_preview: bool = True,
) -> dict[str, Any]:
    if not telegram_enabled():
        return {"ok": False, "skipped": "NOTIFY_OPS_TELEGRAM disabled"}
    dest = (chat_id or owner_chat_id()).strip()
    if not dest:
        return {"ok": False, "error": "telegram_owner_chat_id_missing"}
    payload: dict[str, Any] = {
        "chat_id": dest,
        "text": (text or "")[:4000],
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _post("sendMessage", payload)


def ops_auth_inline_keyboard(task_id: str) -> dict[str, Any]:
    tid = str(task_id or "").strip()
    return {
        "inline_keyboard": [
            [
                {"text": "Confirmar", "callback_data": f"ops.auth.yes.{tid}"},
                {"text": "Cancelar", "callback_data": f"ops.auth.no.{tid}"},
            ]
        ]
    }


def answer_callback(callback_query_id: str, text: str = "") -> dict[str, Any]:
    return _post(
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id, "text": (text or "")[:200]},
    )


def get_me() -> dict[str, Any]:
    return _post("getMe", {})
