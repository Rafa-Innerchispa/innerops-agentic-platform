#!/usr/bin/env python3
"""Gateway :5188 — una URL ngrok pública; enruta InnerOS + Hackathon + API."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from urllib.parse import urljoin

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

INNEROS = os.getenv("GATEWAY_INNEROS", "http://127.0.0.1:5173").rstrip("/")
HACKATHON = os.getenv("GATEWAY_HACKATHON", "http://127.0.0.1:5190").rstrip("/")
SWARM_API = os.getenv("GATEWAY_SWARM_API", "http://127.0.0.1:8100").rstrip("/")
UIPATH_COPILOT = os.getenv("GATEWAY_UIPATH_COPILOT", "http://127.0.0.1:8097").rstrip("/")
CHUTES_DEPOSIT = os.getenv("GATEWAY_CHUTES_DEPOSIT", "http://127.0.0.1:8098").rstrip("/")
GITLAB_TRANSCEND = os.getenv("GATEWAY_GITLAB_TRANSCEND", "http://127.0.0.1:8095").rstrip("/")
FUNDING_HUB = os.getenv("GATEWAY_FUNDING_HUB", "http://127.0.0.1:8099").rstrip("/")
RAPHI_IA_MCP = os.getenv("GATEWAY_RAPHI_IA_MCP", "http://127.0.0.1:8102").rstrip("/")
RAPHI_IA_MCP_QUOTEOPS = os.getenv(
    "GATEWAY_RAPHI_IA_MCP_QUOTEOPS", "http://127.0.0.1:8110"
).rstrip("/")
RAPHI_IA_AUTH = os.getenv("GATEWAY_RAPHI_IA_AUTH", "http://127.0.0.1:8103").rstrip("/")
AMD_OPS_UI = os.getenv("GATEWAY_AMD_OPS_UI", "http://127.0.0.1:8220").rstrip("/")
AMD_OPS_API = os.getenv("GATEWAY_AMD_OPS_API", "http://127.0.0.1:8220").rstrip("/")
LIVEOPS = os.getenv("GATEWAY_LIVEOPS", "http://127.0.0.1:8788").rstrip("/")
LIVEOPS_BRIDGE = os.getenv("GATEWAY_LIVEOPS_BRIDGE", "http://127.0.0.1:8790").rstrip("/")
RAPHI_IA_PANEL = os.getenv("GATEWAY_RAPHI_IA_PANEL", "http://127.0.0.1:2002").rstrip("/")
AMD_PANEL = os.getenv("GATEWAY_AMD_PANEL", "http://192.168.1.5:2002").rstrip("/")
OPEN_WEBUI = os.getenv("GATEWAY_OPEN_WEBUI", "http://127.0.0.1:3000").rstrip("/")
INNERCHISPA_WEB_STAGING = os.getenv("GATEWAY_INNERCHISPA_WEB_STAGING", "http://127.0.0.1:5185").rstrip("/")
PUBLIC_BASE = os.getenv("PUBLIC_GATEWAY_BASE", "https://sworn-profusely-alongside.ngrok-free.dev").rstrip("/")
OPEN_WEBUI_PUBLIC = f"{PUBLIC_BASE}/openwebui"
PORT = int(os.getenv("PUBLIC_GATEWAY_PORT", "5188"))

app = FastAPI(title="Public Gateway", docs_url=None, redoc_url=None)
_client: httpx.AsyncClient | None = None


def _http_target(path: str) -> str:
    if path.startswith("/smartter"):
        return "http://127.0.0.1:2026"
    if path.startswith("/staging-web"):
        return INNERCHISPA_WEB_STAGING
    if path.startswith("/api/projects/approve"):
        return "http://127.0.0.1:8090"
    if path.startswith("/api/projects/pending"):
        return "http://127.0.0.1:8090"
    if path.startswith("/api/projects/approve-and-build"):
        return "http://127.0.0.1:8090"
    if path.startswith("/sre"):
        return "http://127.0.0.1:8096"
    if path.startswith("/ralfia-panel"):
        return RAPHI_IA_PANEL
    if path.startswith("/amd-panel"):
        return AMD_PANEL
    if path.startswith("/amd-ops-api"):
        return AMD_OPS_API
    if path.startswith("/amd-ops"):
        return AMD_OPS_UI
    if path.startswith("/liveops-bridge"):
        return LIVEOPS_BRIDGE
    if path.startswith("/liveops"):
        return LIVEOPS
    if path.startswith("/openwebui"):
        return OPEN_WEBUI
    if path.startswith("/raphiia-auth"):
        return RAPHI_IA_AUTH
    if path.startswith("/raphiia-mcp-quoteops"):
        return RAPHI_IA_MCP_QUOTEOPS
    if path.startswith("/raphiia-mcp/mcp/.well-known"):
        return RAPHI_IA_AUTH
    if path.startswith("/raphiia-mcp/.well-known"):
        return RAPHI_IA_AUTH
    if path.startswith("/.well-known/oauth-protected-resource"):
        return RAPHI_IA_AUTH
    if path.startswith("/raphiia-mcp"):
        return RAPHI_IA_MCP
    if path.startswith("/funding/ui"):
        return RAPHI_IA_PANEL
    if path.startswith("/api/ops"):
        return RAPHI_IA_PANEL
    if path.startswith("/funding"):
        return FUNDING_HUB
    if path.startswith("/chutes-deposit"):
        return CHUTES_DEPOSIT
    if path.startswith("/uipath"):
        return UIPATH_COPILOT
    if path.startswith("/gitlab"):
        return GITLAB_TRANSCEND
    if path.startswith("/inneros") or path.startswith("/datacenter"):
        return INNEROS
    if path.startswith("/api/v1"):
        return SWARM_API
    if path.startswith("/api/"):
        return os.getenv("GATEWAY_HACKATHON_API", "http://127.0.0.1:8210").rstrip("/")
    return HACKATHON


def _openwebui_ws_url(path: str) -> str:
    base = OPEN_WEBUI.replace("http://", "ws://").replace("https://", "wss://")
    return urljoin(base + "/", path.lstrip("/"))


def _ws_target(path: str) -> str:
    base = HACKATHON.replace("http://", "ws://").replace("https://", "wss://")
    return urljoin(base + "/", path.lstrip("/"))


@app.on_event("startup")
async def _startup() -> None:
    global _client
    _client = httpx.AsyncClient(follow_redirects=False, timeout=120.0)
    # Si pierde LISTEN sin morir (zombie), systemd no reinicia. Auto-salida → Restart=always.
    threading.Thread(target=_listen_watchdog, name="gw-listen-watch", daemon=True).start()


def _listen_watchdog() -> None:
    """Sale del proceso si :PORT deja de aceptar conexiones nuevas."""
    grace = int(os.getenv("GATEWAY_WATCH_GRACE_SEC", "20"))
    interval = int(os.getenv("GATEWAY_WATCH_INTERVAL_SEC", "15"))
    fail_need = int(os.getenv("GATEWAY_WATCH_FAILS", "2"))
    time.sleep(grace)
    fails = 0
    while True:
        time.sleep(interval)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            sock.connect(("127.0.0.1", PORT))
            fails = 0
        except OSError:
            fails += 1
            if fails >= fail_need:
                # Forzar reinicio por systemd (Restart=always)
                os._exit(78)
        finally:
            try:
                sock.close()
            except OSError:
                pass


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client:
        await _client.aclose()


@app.websocket("/openwebui/{rest:path}")
async def openwebui_ws_proxy(websocket: WebSocket, rest: str) -> None:
    forward = rest or ""
    upstream_url = _openwebui_ws_url(forward)
    await websocket.accept()
    try:
        async with websockets.connect(upstream_url) as upstream:
            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "text" in msg:
                            await upstream.send(msg["text"])
                        elif "bytes" in msg:
                            await upstream.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        await websocket.close()


@app.websocket("/ws/{rest:path}")
async def ws_proxy(websocket: WebSocket, rest: str) -> None:
    path = f"/ws/{rest}" if rest else "/ws"
    upstream_url = _ws_target(path)
    await websocket.accept()
    try:
        async with websockets.connect(upstream_url) as upstream:
            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "text" in msg:
                            await upstream.send(msg["text"])
                        elif "bytes" in msg:
                            await upstream.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        await websocket.close()


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def http_proxy(full_path: str, request: Request) -> Response:
    assert _client is not None
    path = "/" + full_path if full_path else "/"
    quoteops_resource = f"{PUBLIC_BASE}/raphiia-mcp-quoteops/mcp"
    quoteops_metadata = f"{quoteops_resource}/.well-known/oauth-protected-resource"
    if path == "/raphiia-mcp-quoteops/mcp/.well-known/oauth-protected-resource":
        return JSONResponse(
            {
                "resource": quoteops_resource,
                "authorization_servers": [f"{PUBLIC_BASE}/raphiia-auth"],
                "scopes_supported": [
                    "ralfia:read",
                    "ralfia:write",
                    "ralfia:agents",
                    "ralfia:admin",
                ],
                "bearer_methods_supported": ["header"],
            },
            headers={"Cache-Control": "no-store"},
        )
    has_session = bool(request.headers.get("mcp-session-id"))
    has_auth = bool(request.headers.get("authorization"))
    if path == "/raphiia-mcp-quoteops/mcp" and request.method in {"GET", "HEAD"} and not has_session and not has_auth:
        return Response(
            status_code=401,
            headers={
                "WWW-Authenticate": f'Bearer resource_metadata="{quoteops_metadata}", scope="ralfia:read"',
                "Cache-Control": "no-store",
            },
        )
    if path == "/raphiia-mcp/mcp" and request.method in {"GET", "HEAD"} and not has_session and not has_auth:
        metadata_url = f"{PUBLIC_BASE}/raphiia-mcp/mcp/.well-known/oauth-protected-resource"
        return Response(
            status_code=401,
            headers={
                "WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}", scope="ralfia:read"',
                "Cache-Control": "no-store",
            },
        )
    upstream = _http_target(path)
    forward_path = path
    if path.startswith("/amd-ops-api"):
        forward_path = path[len("/amd-ops-api"):] or "/"
    elif path.startswith("/ralfia-panel"):
        rest = path[len("/ralfia-panel"):] or "/"
        forward_path = rest if rest.startswith("/") else "/" + rest
    elif path.startswith("/amd-panel"):
        rest = path[len("/amd-panel"):] or "/"
        forward_path = rest if rest.startswith("/") else "/" + rest
    elif path.startswith("/amd-ops"):
        rest = path[len("/amd-ops"):] or "/"
        forward_path = "/console" + (rest if rest.startswith("/") else "/" + rest)
    elif path.startswith("/liveops-bridge"):
        rest = path[len("/liveops-bridge"):] or "/"
        forward_path = rest if rest.startswith("/") else "/" + rest
    elif path.startswith("/liveops"):
        rest = path[len("/liveops"):] or "/"
        forward_path = rest if rest.startswith("/") else "/" + rest
    elif path.startswith("/raphiia-auth"):
        forward_path = path[len("/raphiia-auth"):] or "/"
    elif path.startswith("/raphiia-mcp-quoteops"):
        forward_path = path[len("/raphiia-mcp-quoteops"):] or "/"
    elif path.startswith("/raphiia-mcp/mcp/.well-known"):
        forward_path = path[len("/raphiia-mcp/mcp"):] or "/"
    elif path.startswith("/raphiia-mcp/.well-known"):
        forward_path = path[len("/raphiia-mcp"):] or "/"
    elif path.startswith("/.well-known/oauth-protected-resource"):
        forward_path = path
    elif path.startswith("/raphiia-mcp"):
        forward_path = path[len("/raphiia-mcp"):] or "/"
    elif path.startswith("/smartter"):
        rest = path[len("/smartter"):] or "/"
        forward_path = rest if rest.startswith("/") else "/" + rest
    elif path.startswith("/sre"):
        forward_path = path[len("/sre"):] or "/"
    elif path.startswith("/staging-web"):
        forward_path = path
    elif path.startswith("/funding"):
        forward_path = path[len("/funding"):] or "/"
    elif path.startswith("/chutes-deposit"):
        forward_path = path[len("/chutes-deposit"):] or "/"
    elif path.startswith("/uipath"):
        forward_path = path[len("/uipath"):] or "/"
    elif path.startswith("/openwebui"):
        rest = path[len("/openwebui"):] or "/"
        forward_path = rest if rest.startswith("/") else "/" + rest
    url = urljoin(upstream + "/", forward_path.lstrip("/"))
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    if path.startswith("/openwebui"):
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-Prefix"] = "/openwebui"
        headers["X-Forwarded-Host"] = request.headers.get("host", "")
    body = await request.body()

    try:
        upstream_resp = await _client.request(request.method, url, headers=headers, content=body)
    except httpx.RequestError as exc:
        return Response(content=f"Gateway upstream error: {exc}", status_code=502)

    skip = {"transfer-encoding", "connection", "content-encoding"}
    out_headers = {k: v for k, v in upstream_resp.headers.items() if k.lower() not in skip}
    if request.method == "HEAD":
        return Response(status_code=upstream_resp.status_code, headers=out_headers)

    return StreamingResponse(
        upstream_resp.aiter_bytes(),
        status_code=upstream_resp.status_code,
        headers=out_headers,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
