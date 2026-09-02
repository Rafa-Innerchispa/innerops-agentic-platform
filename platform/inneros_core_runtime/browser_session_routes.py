from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from raphiia_openai import browser_session_broker as broker

router = APIRouter(prefix="/browser", tags=["browser-session"])

_LOCAL_AUTOMATION_ENV = "BROWSER_BROKER_LOCAL_AUTOMATION_ENABLED"
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_LOCAL_ACTIONS = {
    "status",
    "inspect",
    "click_selector",
    "press",
    "wait",
    "fill_from_vault",
    "fill_totp_from_vault",
    "vault_capture_totp",
}
_TOTP_RE = re.compile(r"\b[A-Z2-7]{24,80}\b")
_SECRET_TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[opsu]_[A-Za-z0-9_]{20,})\b")


def _local_automation_enabled() -> bool:
    return os.getenv(_LOCAL_AUTOMATION_ENV, "").strip().lower() in {"1", "true", "yes"}


def _require_local_automation(request: Request) -> None:
    if not _local_automation_enabled():
        raise HTTPException(status_code=404, detail="local_browser_automation_disabled")
    host = str(getattr(getattr(request, "client", None), "host", "") or "").strip().lower()
    if host not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="loopback_only")


def _sanitize_local_text(value: str) -> str:
    value = _TOTP_RE.sub("[REDACTED_TOTP_SEED]", str(value or ""))
    return _SECRET_TOKEN_RE.sub("[REDACTED_TOKEN]", value)


def _sanitize_local_result(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_local_text(value)
    if isinstance(value, list):
        return [_sanitize_local_result(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_local_result(item) for key, item in value.items()}
    return value


def _local_action_payload(
    kind: str,
    *,
    selector: str = "",
    category: str = "",
    key: str = "",
    keypress: str = "",
    limit: int = 80,
    ms: int = 1000,
) -> dict[str, Any]:
    if kind not in _LOCAL_ACTIONS:
        raise HTTPException(status_code=400, detail="local_action_not_allowed")
    payload: dict[str, Any] = {}
    if kind == "inspect":
        payload["limit"] = max(1, min(int(limit or 80), 200))
    elif kind == "click_selector":
        if not selector:
            raise HTTPException(status_code=400, detail="selector_required")
        payload["selector"] = selector
    elif kind == "press":
        payload["key"] = keypress or "Enter"
    elif kind == "wait":
        payload["ms"] = max(0, min(int(ms or 1000), 30000))
    elif kind in {"fill_from_vault", "fill_totp_from_vault"}:
        if not selector or not category or not key:
            raise HTTPException(status_code=400, detail="vault_ref_and_selector_required")
        payload.update({"selector": selector, "category": category, "key": key})
    elif kind == "vault_capture_totp":
        payload.update({"category": category or "alpaca", "key": key or "totp_seed"})
    return payload


def _html(session_id: str, token: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InnerOS Browser Session</title>
  <style>
    body {{ margin:0; font-family: system-ui, sans-serif; background:#101114; color:#f3f4f6; }}
    header {{ display:flex; gap:8px; align-items:center; padding:10px; background:#1f2937; position:sticky; top:0; z-index:2; }}
    input, button {{ font: inherit; padding:8px; border-radius:6px; border:1px solid #4b5563; background:#111827; color:#f9fafb; }}
    button {{ cursor:pointer; background:#2563eb; border-color:#2563eb; }}
    button.secondary {{ background:#374151; border-color:#4b5563; }}
    #url {{ flex:1; min-width:180px; }}
    #screen {{ width:100%; max-width:1366px; display:block; margin:0 auto; background:#000; cursor:crosshair; }}
    .bar {{ display:flex; gap:8px; padding:10px; background:#111827; }}
    #text {{ flex:1; }}
    #status {{ padding:8px 10px; font-size:13px; color:#d1d5db; }}
  </style>
</head>
<body>
  <header>
    <strong>InnerOS Browser</strong>
    <input id="url" placeholder="https://..." />
    <button onclick="navigate()">Go</button>
    <button class="secondary" onclick="press('Enter')">Enter</button>
    <button class="secondary" onclick="press('Tab')">Tab</button>
    <button class="secondary" onclick="stopSession()">Stop</button>
  </header>
  <div class="bar">
    <input id="text" placeholder="Type into focused field. Passwords are not stored by InnerOS." type="password" autocomplete="off" />
    <button onclick="typeText()">Type</button>
    <button class="secondary" onclick="toggleText()">Show/Hide</button>
  </div>
  <div id="status">Starting...</div>
  <img id="screen" alt="browser screenshot" onclick="clickScreen(event)" />
  <script>
    const sid = {session_id!r};
    const token = {token!r};
    const base = `/browser/api/session/${{sid}}`;
    async function api(path, body) {{
      const res = await fetch(`${{base}}/${{path}}?token=${{encodeURIComponent(token)}}`, {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify(body || {{}})
      }});
      return await res.json();
    }}
    async function refresh() {{
      const img = document.getElementById('screen');
      img.src = `${{base}}/screenshot.png?token=${{encodeURIComponent(token)}}&t=${{Date.now()}}`;
      const res = await fetch(`${{base}}/status?token=${{encodeURIComponent(token)}}`);
      const st = await res.json();
      document.getElementById('status').textContent = JSON.stringify(st.session || st);
      const urlInput = document.getElementById('url');
      if (st.session && st.session.current_url && document.activeElement !== urlInput) urlInput.value = st.session.current_url;
    }}
    async function navigate() {{ await api('action', {{kind:'navigate', url:document.getElementById('url').value}}); refresh(); }}
    async function typeText() {{ await api('action', {{kind:'type', text:document.getElementById('text').value}}); document.getElementById('text').value=''; refresh(); }}
    async function press(key) {{ await api('action', {{kind:'press', key}}); refresh(); }}
    async function clickScreen(ev) {{
      const img = ev.currentTarget;
      const rect = img.getBoundingClientRect();
      const scaleX = img.naturalWidth / rect.width;
      const scaleY = img.naturalHeight / rect.height;
      await api('action', {{kind:'click', x:(ev.clientX-rect.left)*scaleX, y:(ev.clientY-rect.top)*scaleY}});
      setTimeout(refresh, 300);
    }}
    async function stopSession() {{ await api('stop', {{}}); document.getElementById('status').textContent='Stopped'; }}
    function toggleText() {{ const el=document.getElementById('text'); el.type = el.type === 'password' ? 'text' : 'password'; }}
    setInterval(refresh, 2000);
    refresh();
  </script>
</body>
</html>"""


@router.post("/api/session/start")
async def session_start(request: Request):
    body = await request.json()
    return broker.start_session(
        str(body.get("url") or ""),
        profile=str(body.get("profile") or "default"),
        ttl_seconds=int(body.get("ttl_seconds") or 7200),
        local_preview=bool(body.get("local_preview") or False),
        loopback_ports=body.get("loopback_ports"),
    )


@router.get("/api/session/status")
def session_status_list():
    return broker.status()


@router.get("/session/{session_id}", response_class=HTMLResponse)
def session_page(session_id: str, token: str):
    status = broker.status(session_id, token)
    if not status.get("ok"):
        raise HTTPException(status_code=404, detail=status.get("error"))
    return _html(session_id, token)


@router.get("/api/session/{session_id}/status")
def session_status(session_id: str, token: str):
    return broker.status(session_id, token)


@router.get("/api/session/{session_id}/screenshot.png")
def session_screenshot(session_id: str, token: str):
    data = broker.screenshot_png(session_id, token)
    if not data:
        raise HTTPException(status_code=404, detail="screenshot_unavailable")
    return Response(content=data, media_type="image/png")


@router.post("/api/session/{session_id}/action")
async def session_action(session_id: str, token: str, request: Request):
    body = await request.json()
    kind = str(body.pop("kind", ""))
    return broker.action(session_id, token, kind, body)


@router.post("/api/session/{session_id}/stop")
def session_stop(session_id: str, token: str):
    return broker.stop_session(session_id, token)


@router.get("/local/start")
def local_session_start(
    request: Request,
    url: str,
    profile: str = "local-automation",
    ttl_seconds: int = 7200,
):
    _require_local_automation(request)
    result = broker.start_session(url, profile=profile, ttl_seconds=ttl_seconds, local_preview=False)
    return _sanitize_local_result(result)


@router.get("/local/status")
def local_session_status(request: Request, session_id: str, token: str):
    _require_local_automation(request)
    return _sanitize_local_result(broker.status(session_id, token))


@router.get("/local/action")
def local_session_action(
    request: Request,
    session_id: str,
    token: str,
    kind: str,
    selector: str = "",
    category: str = "",
    key: str = "",
    keypress: str = "",
    limit: int = 80,
    ms: int = 1000,
):
    _require_local_automation(request)
    payload = _local_action_payload(
        kind,
        selector=selector,
        category=category,
        key=key,
        keypress=keypress,
        limit=limit,
        ms=ms,
    )
    return _sanitize_local_result(broker.action(session_id, token, kind, payload))


@router.get("/local/stop")
def local_session_stop(request: Request, session_id: str, token: str):
    _require_local_automation(request)
    return _sanitize_local_result(broker.stop_session(session_id, token))
