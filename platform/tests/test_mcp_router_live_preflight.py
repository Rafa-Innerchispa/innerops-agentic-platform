"""Read-only live backend preflight. Never reads secrets or modifies services."""
import json
import socket
import httpx

def test_live_shadow_prerequisites():
    with socket.socket() as sock:
        occupied = sock.connect_ex(("127.0.0.1",8103)) == 0
    response = httpx.post("http://127.0.0.1:8102/mcp", timeout=10,
        headers={"Accept":"application/json, text/event-stream"},
        json={"jsonrpc":"2.0","id":"shadow-preflight","method":"initialize","params":{
            "protocolVersion":"2025-03-26","capabilities":{},
            "clientInfo":{"name":"mcp-router-read-only-preflight","version":"1"}}})
    print("LIVE_PREFLIGHT",json.dumps({"monolith_http_status":response.status_code,
        "monolith_content_type":response.headers.get("content-type"),"port_8103_occupied":occupied,
        "auth_required":response.status_code in (401,403)}))
    assert response.status_code == 200, "Live authenticated test identity required; no auth bypass permitted"
    assert not occupied, "8103 already occupied; do not replace existing service"
