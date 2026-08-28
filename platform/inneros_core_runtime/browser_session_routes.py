from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from raphiia_openai import browser_session_broker as broker

router = APIRouter(prefix="/browser", tags=["browser-session"])


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
