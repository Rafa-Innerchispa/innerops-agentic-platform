"""Cliente HTTP hacia ntfy self-hosted (Intel LAN). Sin Home Assistant ni Telegram."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote

import httpx


def configured() -> bool:
    return bool(_base_url().strip()) and bool(_token() or _topic().startswith("ralfia"))


def _base_url() -> str:
    return (os.getenv("INNEROS_NTFY_URL") or "http://127.0.0.1:2586").rstrip("/")


def _topic() -> str:
    return (os.getenv("INNEROS_NTFY_TOPIC") or "ralfia-owner-ops").strip().lstrip("/")


def _token() -> str:
    return (os.getenv("INNEROS_NTFY_TOKEN") or "").strip()


def publish(
    message: str,
    *,
    title: str = "InnerOS",
    tags: list[str] | None = None,
    priority: str = "high",
    click: str = "",
    actions: list[dict[str, str]] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not configured():
        return {"ok": False, "skipped": "ntfy_not_configured"}
    url = f"{_base_url()}/{quote(_topic(), safe='')}"
    headers: dict[str, str] = {"Title": title[:250], "Priority": priority, "Tags": ",".join(tags or ["inneros"])}
    if click:
        headers["Click"] = click[:2048]
    if actions:
        # ntfy: Action: action, Label, URL [, clear=true]
        action_lines = []
        for a in actions[:3]:
            action_lines.append(
                f"{a.get('action','view')}, {a.get('label','OK')}, {a.get('url','')}"
                + (", clear=true" if a.get("clear") else "")
            )
        headers["Actions"] = "; ".join(action_lines)
    if extras:
        headers["Extras"] = json.dumps(extras)[:3500]
    if _token():
        headers["Authorization"] = f"Bearer {_token()}"
    try:
        r = httpx.post(url, content=(message or title)[:4000].encode(), headers=headers, timeout=15.0)
        ok = r.status_code in (200, 201)
        return {"ok": ok, "http_status": r.status_code, "topic": _topic(), "url": url}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300]}