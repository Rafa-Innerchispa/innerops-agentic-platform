"""Human-in-the-loop Playwright browser sessions for headless servers.

The browser runs on the server, while the owner controls it from a LAN/public
broker page. Browser-backed vault actions persist encrypted values server-side
and never return plaintext values to the caller.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import queue
import re
import secrets
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from raphiia_openai.agents import ag55_browser_ops_agent as ag55

SESSION_ROOT = Path(os.getenv("BROWSER_SESSION_ROOT", "/home/rlopez/data/ralfia/browser_ops/human_sessions"))
DEFAULT_TTL_SECONDS = int(os.getenv("BROWSER_SESSION_TTL_SECONDS", "7200"))
APP_PORT = int(os.getenv("RAPHI_IA_OPENAI_PORT", "8101"))
_VAULT_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}")
_TOTP_SEED_RE = re.compile(r"[A-Z2-7]{24,80}")


def _safe_profile(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", (value or "default")[:48])


def _valid_vault_name(value: str) -> bool:
    return bool(_VAULT_TOKEN_RE.fullmatch(value or ""))


def _totp_code(seed: str, now: float | None = None) -> str:
    normalized = "".join(str(seed or "").split()).upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key_bytes = base64.b32decode(normalized + padding, casefold=True)
    counter = int(now if now is not None else time.time()) // 30
    digest = hmac.new(key_bytes, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return f"{binary % 1_000_000:06d}"


def _lan_host() -> str:
    env_host = os.getenv("BROWSER_BROKER_LAN_HOST")
    if env_host:
        return env_host
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(1)
        probe.connect(("192.168.1.1", 80))
        host = probe.getsockname()[0]
        probe.close()
        if not host.startswith("127."):
            return host
    except Exception:
        pass
    return socket.gethostbyname(socket.gethostname())


def _public_base() -> str:
    return os.getenv("BROWSER_BROKER_PUBLIC_BASE_URL", "").rstrip("/")


@dataclass
class BrowserSession:
    session_id: str
    token: str
    profile: str
    start_url: str
    created_at: float
    expires_at: float
    local_preview: bool = False
    loopback_ports: list[int] | None = None
    pw: Any = None
    context: Any = None
    page: Any = None
    command_queue: queue.Queue = field(default_factory=queue.Queue)
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_error: str = ""
    status: str = "starting"


_sessions: dict[str, BrowserSession] = {}
_registry_lock = threading.RLock()


def _public_session(session: BrowserSession) -> dict[str, Any]:
    base_lan = f"http://{_lan_host()}:{APP_PORT}"
    public = _public_base()
    path = f"/browser/session/{session.session_id}?token={session.token}"
    return {
        "session_id": session.session_id,
        "profile": session.profile,
        "status": session.status,
        "start_url": session.start_url,
        "created_at": session.created_at,
        "expires_at": session.expires_at,
        "agent_local_url": f"http://127.0.0.1:{APP_PORT}{path}",
        "user_lan_url": f"{base_lan}{path}",
        "secure_public_url": f"{public}{path}" if public else "",
        "requires_human_login": True,
        "security": {
            "token_in_url": True,
            "ttl_seconds": int(session.expires_at - session.created_at),
            "credentials_persisted": False,
            "chrome_debug_exposed": False,
        },
    }


def _get_session(session_id: str, token: str) -> BrowserSession | None:
    with _registry_lock:
        session = _sessions.get(session_id)
    if not session or session.token != token:
        return None
    if time.time() > session.expires_at:
        stop_session(session_id, token)
        return None
    return session


def start_session(
    url: str,
    *,
    profile: str = "default",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    local_preview: bool = False,
    loopback_ports: list[int] | None = None,
) -> dict[str, Any]:
    guard = ag55._url_allowed_result(url, local_preview=local_preview, loopback_ports=loopback_ports)
    if not guard.get("ok"):
        return {"ok": False, "error": "url_not_allowed", "url_guard": guard}
    session_id = f"bs_{secrets.token_hex(8)}"
    token = secrets.token_urlsafe(24)
    now = time.time()
    session = BrowserSession(
        session_id=session_id,
        token=token,
        profile=_safe_profile(profile),
        start_url=url,
        created_at=now,
        expires_at=now + max(300, min(int(ttl_seconds or DEFAULT_TTL_SECONDS), 24 * 3600)),
        local_preview=local_preview,
        loopback_ports=loopback_ports,
    )
    with _registry_lock:
        _sessions[session_id] = session
    threading.Thread(target=_launch_session, args=(session,), daemon=True).start()
    return {"ok": True, "session": _public_session(session)}


def _launch_session(session: BrowserSession) -> None:
    try:
        from playwright.sync_api import sync_playwright

        SESSION_ROOT.mkdir(parents=True, exist_ok=True)
        profile_dir = SESSION_ROOT / session.profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            str(profile_dir), headless=True, viewport={"width": 1366, "height": 768}
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(session.start_url, wait_until="domcontentloaded", timeout=30000)
        with session.lock:
            session.pw = pw
            session.context = context
            session.page = page
            session.status = "ready"
        while True:
            item = session.command_queue.get()
            if item is None:
                break
            kind, payload, result_queue = item
            try:
                result_queue.put(_execute_page_command(session, kind, payload or {}))
            except Exception as exc:
                with session.lock:
                    session.last_error = str(exc)[:800]
                result_queue.put({"ok": False, "error": str(exc)[:800]})
    except Exception as exc:
        with session.lock:
            session.status = "failed"
            session.last_error = str(exc)[:800]
    finally:
        with session.lock:
            context = session.context
            pw = session.pw
        try:
            if context:
                context.close()
            if pw:
                pw.stop()
        except Exception:
            pass


def _call_worker(session: BrowserSession, kind: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    result_queue: queue.Queue = queue.Queue(maxsize=1)
    session.command_queue.put((kind, payload or {}, result_queue))
    try:
        return result_queue.get(timeout=timeout)
    except queue.Empty:
        return {"ok": False, "error": "browser_command_timeout"}


def _execute_page_command(session: BrowserSession, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    page = session.page
    if not page:
        return {"ok": False, "error": "page_not_ready", "status": session.status, "last_error": session.last_error}

    if kind == "status":
        return {"ok": True, "current_url": page.url, "title": page.title()}
    if kind == "screenshot":
        return {"ok": True, "png": page.screenshot(full_page=False)}
    if kind == "navigate":
        url = str(payload.get("url") or "").strip()
        guard = ag55._url_allowed_result(url, local_preview=session.local_preview, loopback_ports=session.loopback_ports)
        if not guard.get("ok"):
            return {"ok": False, "error": "url_not_allowed", "url_guard": guard}
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    elif kind == "click":
        page.mouse.click(float(payload.get("x") or 0), float(payload.get("y") or 0))
    elif kind == "type":
        page.keyboard.type(str(payload.get("text") or ""), delay=20)
    elif kind == "press":
        page.keyboard.press(str(payload.get("key") or "Enter"))
    elif kind == "wait":
        page.wait_for_timeout(int(payload.get("ms") or 1000))
    elif kind == "inspect":
        limit = max(1, min(int(payload.get("limit") or 80), 200))
        items = page.locator("input, button, a, [role=button], select, textarea").evaluate_all(
            """(els, limit) => els.slice(0, limit).map((el, i) => ({
              i, tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
              name: el.getAttribute('name') || '', id: el.id || '',
              role: el.getAttribute('role') || '', href: el.getAttribute('href') || '',
              placeholder: el.getAttribute('placeholder') || '',
              aria: el.getAttribute('aria-label') || '',
              text: (el.innerText || el.textContent || '').trim().slice(0, 180),
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
            }))""",
            limit,
        )
        return {"ok": True, "current_url": page.url, "title": page.title(), "items": items}
    elif kind == "click_selector":
        selector = str(payload.get("selector") or "").strip()
        if not selector or len(selector) > 500:
            return {"ok": False, "error": "selector_required"}
        page.locator(selector).first.click(timeout=int(payload.get("timeout_ms") or 10000))
        return {"ok": True, "current_url": page.url, "title": page.title()}
    elif kind == "fill_selector":
        selector = str(payload.get("selector") or "").strip()
        if not selector or len(selector) > 500:
            return {"ok": False, "error": "selector_required"}
        page.locator(selector).first.fill(str(payload.get("text") or ""), timeout=int(payload.get("timeout_ms") or 10000))
        return {"ok": True, "current_url": page.url, "title": page.title(), "filled": True}
    elif kind == "text":
        selector = str(payload.get("selector") or "body").strip() or "body"
        text = page.locator(selector).first.inner_text(timeout=int(payload.get("timeout_ms") or 10000))
        return {"ok": True, "current_url": page.url, "title": page.title(), "text": text[:20000]}
    elif kind == "vault_store_value":
        from raphiia_openai import owner_vault

        category = str(payload.get("category") or "").strip().lower()
        key = str(payload.get("key") or "").strip().lower()
        value = str(payload.get("value") or "")
        label = str(payload.get("label") or key).strip()[:120]
        project_id = str(payload.get("project_id") or "").strip()
        if not _valid_vault_name(category) or not _valid_vault_name(key):
            return {"ok": False, "error": "invalid_vault_key"}
        if not value:
            return {"ok": False, "error": "value_required"}
        saved = owner_vault.save_owner_credential(
            key=key,
            secret=value,
            category=category,
            label=label,
            metadata={"project_id": project_id, "source": "browser_session"},
            actor="RAFAEL",
        )
        return {
            "ok": bool(saved.get("ok")),
            "vault_id": saved.get("vault_id"),
            "credential_ref": f"owner_vault:{category}/{key}" if saved.get("ok") else None,
            "value_returned": False,
        }
    elif kind == "vault_capture_totp":
        from raphiia_openai import owner_vault

        category = str(payload.get("category") or "alpaca").strip().lower()
        key = str(payload.get("key") or "totp_seed").strip().lower()
        project_id = str(payload.get("project_id") or "inneros-alpha-alpaca").strip()
        if not _valid_vault_name(category) or not _valid_vault_name(key):
            return {"ok": False, "error": "invalid_vault_key"}
        candidates = page.locator("button").all_inner_texts()
        value = next((text.strip() for text in candidates if _TOTP_SEED_RE.fullmatch(text.strip())), "")
        if not value:
            return {"ok": False, "error": "totp_seed_not_found"}
        saved = owner_vault.save_owner_credential(
            key=key,
            secret=value,
            category=category,
            label="Alpaca hackathon TOTP seed",
            metadata={"project_id": project_id, "source": "alpaca_mfa_manual_code"},
            actor="RAFAEL",
        )
        return {
            "ok": bool(saved.get("ok")),
            "vault_id": saved.get("vault_id"),
            "credential_ref": f"owner_vault:{category}/{key}" if saved.get("ok") else None,
            "value_returned": False,
        }
    elif kind == "fill_from_vault":
        from raphiia_openai import owner_vault

        category = str(payload.get("category") or "").strip().lower()
        key = str(payload.get("key") or "").strip().lower()
        selector = str(payload.get("selector") or "").strip()
        if not _valid_vault_name(category) or not _valid_vault_name(key) or not selector:
            return {"ok": False, "error": "vault_ref_and_selector_required"}
        record = owner_vault.get_owner_credential(key, category=category, reveal=True, actor="RAFAEL")
        value = str(record.get("secret") or "") if record.get("ok") else ""
        if not value:
            return {"ok": False, "error": "vault_credential_unavailable"}
        page.locator(selector).first.fill(value, timeout=int(payload.get("timeout_ms") or 10000))
        return {"ok": True, "filled": True, "credential_ref": f"owner_vault:{category}/{key}", "value_returned": False}
    elif kind == "fill_totp_from_vault":
        from raphiia_openai import owner_vault

        category = str(payload.get("category") or "alpaca").strip().lower()
        key = str(payload.get("key") or "totp_seed").strip().lower()
        selector = str(payload.get("selector") or "input").strip()
        record = owner_vault.get_owner_credential(key, category=category, reveal=True, actor="RAFAEL")
        seed = str(record.get("secret") or "") if record.get("ok") else ""
        if not seed:
            return {"ok": False, "error": "vault_credential_unavailable"}
        try:
            code = _totp_code(seed)
        except Exception:
            return {"ok": False, "error": "totp_seed_invalid"}
        page.locator(selector).first.fill(code, timeout=int(payload.get("timeout_ms") or 10000))
        return {"ok": True, "filled": True, "credential_ref": f"owner_vault:{category}/{key}", "code_returned": False}
    else:
        return {"ok": False, "error": "unknown_action"}

    return {"ok": True, "status": session.status, "current_url": page.url, "title": page.title()}


def status(session_id: str = "", token: str = "") -> dict[str, Any]:
    if session_id:
        session = _get_session(session_id, token)
        if not session:
            return {"ok": False, "error": "session_not_found_or_unauthorized"}
        out = _public_session(session)
        with session.lock:
            out["last_error"] = session.last_error
        if session.page:
            live = _call_worker(session, "status", timeout=10)
            out["current_url"] = live.get("current_url", "")
            out["title"] = live.get("title", "")
            if not live.get("ok"):
                out["last_error"] = live.get("error", out.get("last_error", ""))
        else:
            out["current_url"] = ""
            out["title"] = ""
        return {"ok": True, "session": out}
    with _registry_lock:
        sessions = [_public_session(s) for s in _sessions.values() if time.time() <= s.expires_at]
    return {"ok": True, "sessions": sessions}


def screenshot_png(session_id: str, token: str) -> bytes | None:
    session = _get_session(session_id, token)
    if not session:
        return None
    with session.lock:
        if not session.page:
            return None
    result = _call_worker(session, "screenshot", timeout=20)
    if result.get("ok"):
        return result.get("png")
    with session.lock:
        session.last_error = str(result.get("error") or "")[:800]
    return None


def screenshot_data_url(session_id: str, token: str) -> str:
    data = screenshot_png(session_id, token)
    if not data:
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def action(session_id: str, token: str, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id, token)
    if not session:
        return {"ok": False, "error": "session_not_found_or_unauthorized"}
    payload = payload or {}
    with session.lock:
        if not session.page:
            return {"ok": False, "error": "page_not_ready", "status": session.status, "last_error": session.last_error}
    result = _call_worker(session, kind, payload, timeout=35)
    if not result.get("ok"):
        with session.lock:
            session.last_error = str(result.get("error") or "")[:800]
    return result


def stop_session(session_id: str, token: str = "") -> dict[str, Any]:
    with _registry_lock:
        session = _sessions.get(session_id)
        if not session or (token and session.token != token):
            return {"ok": False, "error": "session_not_found_or_unauthorized"}
        _sessions.pop(session_id, None)
    with session.lock:
        session.status = "stopped"
        session.command_queue.put(None)
    return {"ok": True, "session_id": session_id, "status": "stopped"}
