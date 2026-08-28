#!/usr/bin/env python3
"""Genera openwebui.env limpio + flags 0.10.x útiles (sin duplicados)."""

from __future__ import annotations

import json
from pathlib import Path

ENV_FILE = Path("/mnt/datos_agentes/ai-server-v2/open-webui/openwebui.env")
SECRET_FILE = Path("/mnt/datos_agentes/ai-server-v2/open-webui/.webui_secret_key")
RAPHI_ENV = Path("/home/rlopez/projects/raphiia-openai/.env")
DATA = ENV_FILE.parent
TERMINAL_ENV = Path("/home/rlopez/data/open-terminal/open-terminal.env")
TERMINAL_PORT = 8010


def _load_mcp_key() -> str:
    for line in RAPHI_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("MCP_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("MCP_API_KEY missing")


def main() -> None:
    secret = SECRET_FILE.read_text(encoding="utf-8").strip() if SECRET_FILE.is_file() else ""
    mcp_key = _load_mcp_key()
    tool_json = (DATA / "tool_server_connections.json").read_text(encoding="utf-8").strip()

    term_key = ""
    terminal_json = "[]"
    if TERMINAL_ENV.is_file():
        term_key = TERMINAL_ENV.read_text(encoding="utf-8").split("=", 1)[1].strip()
        terminal = [
            {
                "id": "ralfia-terminal",
                "name": "RalfIA Terminal (LAN)",
                "url": f"http://host.docker.internal:{TERMINAL_PORT}",
                "key": term_key,
                "auth_type": "bearer",
                "enabled": True,
                "info": {"id": "ralfia-terminal", "name": "RalfIA Terminal (LAN)"},
                "config": {"enable": True, "access_grants": []},
            }
        ]
        terminal_json = json.dumps(terminal)

    lines = [
        f"WEBUI_SECRET_KEY={secret}",
        "WEBUI_URL=http://192.168.1.4:3000",
        "OLLAMA_BASE_URL=http://192.168.1.4:11434",
        "ENABLE_PERSISTENT_CONFIG=true",
        "ENABLE_DIRECT_CONNECTIONS=true",
        "ENABLE_MCP=true",
        "ENABLE_WEB_SEARCH=true",
        "WEB_SEARCH_ENGINE=ddgs",
        "ENABLE_LOCAL_WEB_FETCH=true",
        "MCP_INITIALIZE_TIMEOUT=120",
        "AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER=300",
        "AIOHTTP_CLIENT_ALLOW_REDIRECTS=false",
        # 0.10.x — más iteraciones tool-call (evita cortar a medias)
        "CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS=64",
        # User-Agent real para web fetch (Cloudflare, Wikipedia)
        'USER_AGENT=Mozilla/5.0 (compatible; RalfIA-OpenWebUI/1.0)',
        'DEFAULT_MODEL_PARAMS={"function_calling":"native","temperature":0.25,"stream_response":false}',
        f"TOOL_SERVER_CONNECTIONS={tool_json}",
        f"TERMINAL_SERVER_CONNECTIONS={terminal_json}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)
    print(f"OK {ENV_FILE} ({len(lines)} vars)")


if __name__ == "__main__":
    main()
