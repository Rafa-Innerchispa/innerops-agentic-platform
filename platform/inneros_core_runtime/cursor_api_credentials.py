"""Resolve Cursor User API key for SDK / Cloud Agents (never log secret values)."""

from __future__ import annotations

import os
from typing import Any

VAULT_CATEGORY = "cursor"
VAULT_KEY = "api_key"


def resolve_cursor_api_key() -> dict[str, Any]:
    """Return {ok, present, source, key} — key only when present (for internal use)."""
    env = (os.getenv("CURSOR_API_KEY") or "").strip()
    if env:
        return {"ok": True, "present": True, "source": "env:CURSOR_API_KEY", "key": env}

    file_path = (os.getenv("CURSOR_API_KEY_FILE") or "").strip()
    if file_path:
        try:
            from pathlib import Path

            raw = Path(file_path).expanduser().read_text(encoding="utf-8").strip()
            if raw:
                return {"ok": True, "present": True, "source": f"file:{file_path}", "key": raw}
        except OSError:
            pass

    try:
        from inneros_core_runtime import owner_vault

        row = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True)
        secret = str((row.get("secret") or row.get("value") or "")).strip()
        if row.get("ok") and secret:
            return {"ok": True, "present": True, "source": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}", "key": secret}
    except Exception as exc:
        return {"ok": False, "present": False, "source": "none", "error": str(exc)[:200]}

    return {
        "ok": True,
        "present": False,
        "source": "none",
        "hint": "Mint User API key at https://cursor.com/dashboard → API Keys; store via scripts/inneros_store_cursor_api_key.py",
    }


def cursor_api_key_status() -> dict[str, Any]:
    row = resolve_cursor_api_key()
    return {
        "ok": True,
        "present": bool(row.get("present")),
        "source": row.get("source"),
        "hint": row.get("hint"),
    }
