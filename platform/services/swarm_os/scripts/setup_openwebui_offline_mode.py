#!/usr/bin/env python3
"""Preset Open WebUI para resiliencia offline: modelo, MCP filtrado, terminal, memoria."""

from __future__ import annotations

import json
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path

WEBUI_DB = Path("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
ENV_FILE = Path("/mnt/datos_agentes/ai-server-v2/open-webui/openwebui.env")
TERMINAL_ENV = Path("/home/rlopez/data/open-terminal/open-terminal.env")
TERMINAL_PORT = int(__import__("os").environ.get("OPEN_TERMINAL_PORT", "8010"))
CONTAINER = __import__("os").environ.get("OPENWEBUI_CONTAINER", "open-webui")

MODEL_ID = "ralfia-offline"  # id interno estable; nombre visible cambia abajo
BASE_MODEL = "qwen2.5:14b-instruct-q4_K_M"
DISPLAY_NAME = "RalfIA Copilot (qwen 14B)"

OFFLINE_TOOLS = [
    "bootstrap_context",
    "get_project_map",
    "get_coordination_summary",
    "read_coordination_file",
    "search_coordination_docs",
    "search",
    "save_memory",
    "health_check",
    "system_health",
    "list_service_registry",
    "log_coordination_event",
    "describe_tool",
]

SYSTEM_PROMPT = """Eres RalfIA Copilot, asistente principal de Rafael en Open WebUI.

MODO NORMAL (hay internet):
- Puedes usar búsqueda web, herramientas nativas y razonar con normalidad.
- Para datos del servidor (Mongo, coordinación, puertos): usa MCP RalfIA (LAN).
- Para archivos/carpetas en el servidor: Open Terminal.

MODO RESILIENCIA (sin internet externo):
- Siguen activos en LAN: MCP :8102, Mongo, Ollama, Open WebUI, terminal :8010.
- No dependas de ngrok ni APIs cloud; usa MCP + Knowledge + terminal local.

AL INICIAR (si tienes MCP activo en el chat):
1. bootstrap_context o get_project_map
2. search_memories si necesitas contexto personal

PRIORIDAD:
- Servidor/coordinación → MCP RalfIA
- Shell/mkdir/scripts → Open Terminal
- Docs estáticos → Knowledge adjunta
- Datos personales → Memory

Responde en español, pasos concretos. Puertos canónicos: 8101 health, 8102 MCP, 8100 swarm."""


def _load_mcp_key() -> str:
    env = Path("/home/rlopez/projects/raphiia-openai/.env")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("MCP_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("MCP_API_KEY missing")


def _set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    if conn.execute("SELECT 1 FROM config WHERE key=?", (key,)).fetchone():
        conn.execute("UPDATE config SET value=? WHERE key=?", (value, key))
    else:
        conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, value))


def _patch_mcp_filter(conn: sqlite3.Connection, api_key: str) -> None:
    mcp = {
        "type": "mcp",
        "url": "http://192.168.1.4:8102/mcp",
        "auth_type": "bearer",
        "key": api_key,
        "info": {
            "id": "ralfia-mcp-local",
            "name": "RalfIA MCP (LAN)",
            "description": "Offline: Mongo + ai_coordination en LAN",
        },
        "config": {
            "enable": True,
            "access_grants": [],
            "function_name_filter_list": ",".join(OFFLINE_TOOLS),
        },
    }
    payload = json.dumps([mcp])
    _set_config(conn, "tool_server.connections", payload)
    (WEBUI_DB.parent / "tool_server_connections.json").write_text(payload, encoding="utf-8")


def _patch_terminal(conn: sqlite3.Connection) -> None:
    if not TERMINAL_ENV.is_file():
        return
    api_key = TERMINAL_ENV.read_text(encoding="utf-8").split("=", 1)[1].strip()
    terminal = [
        {
            "url": f"http://host.docker.internal:{TERMINAL_PORT}",
            "key": api_key,
            "auth_type": "bearer",
            "info": {"id": "ralfia-terminal", "name": "RalfIA Terminal (LAN)"},
            "config": {"enable": True, "access_grants": []},
        }
    ]
    _set_config(conn, "terminal_server.connections", json.dumps(terminal))


def _upsert_offline_model(conn: sqlite3.Connection, admin_id: str) -> None:
    now = int(time.time())
    params = {
        "system": SYSTEM_PROMPT,
        "function_calling": "native",
        "temperature": 0.35,
        "top_p": 0.9,
    }
    meta = {
        "description": "Asistente principal: qwen 14B + MCP LAN + Knowledge + memoria + terminal. Internet OK.",
        "tags": [{"name": "ralfia"}, {"name": "copilot"}],
        "capabilities": {
            "code_interpreter": False,
            "terminal": True,
            "builtin_tools": True,
            "file_context": True,
            "memory": True,
        },
    }
    row = conn.execute("SELECT id FROM model WHERE id=?", (MODEL_ID,)).fetchone()
    if row:
        conn.execute(
            "UPDATE model SET name=?, base_model_id=?, params=?, meta=?, updated_at=?, is_active=1 WHERE id=?",
            (DISPLAY_NAME, BASE_MODEL, json.dumps(params), json.dumps(meta), now, MODEL_ID),
        )
    else:
        conn.execute(
            "INSERT INTO model (id, user_id, base_model_id, name, params, meta, created_at, updated_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                MODEL_ID,
                admin_id,
                BASE_MODEL,
                DISPLAY_NAME,
                json.dumps(params),
                json.dumps(meta),
                now,
                now,
            ),
        )
    _set_config(conn, "ui.default_models", json.dumps(MODEL_ID))
    _set_config(conn, "ui.default_pinned_models", json.dumps([MODEL_ID]))
    default_params = {"function_calling": "native", "temperature": 0.35}
    _set_config(conn, "models.default_params", json.dumps(default_params))
    _set_config(conn, "memories.enable", "true")
    _set_config(conn, "memories.system_context.enable", "true")


def _write_env(secret: str, tool_json: str, terminal_json: str) -> None:
    lines = []
    if ENV_FILE.is_file():
        lines = [
            ln
            for ln in ENV_FILE.read_text(encoding="utf-8").splitlines()
            if not ln.startswith(
                (
                    "TOOL_SERVER_CONNECTIONS=",
                    "TERMINAL_SERVER_CONNECTIONS=",
                    "DEFAULT_MODEL_PARAMS=",
                    "WEBUI_URL=",
                )
            )
        ]
    lines.extend(
        [
            f"WEBUI_SECRET_KEY={secret}",
            "ENABLE_DIRECT_CONNECTIONS=true",
            "MCP_INITIALIZE_TIMEOUT=120",
            "AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER=300",
            "WEBUI_URL=http://192.168.1.4:3000",
            "OLLAMA_BASE_URL=http://192.168.1.4:11434",
            "ENABLE_MCP=true",
            f'TOOL_SERVER_CONNECTIONS={tool_json}',
            f'TERMINAL_SERVER_CONNECTIONS={terminal_json}',
            'DEFAULT_MODEL_PARAMS={"function_calling":"native","temperature":0.35}',
        ]
    )
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)


def main() -> None:
    secret_file = WEBUI_DB.parent / ".webui_secret_key"
    secret = secret_file.read_text(encoding="utf-8").strip() if secret_file.is_file() else secrets.token_hex(32)
    api_key = _load_mcp_key()

    conn = sqlite3.connect(WEBUI_DB)
    admin_id = conn.execute("SELECT id FROM user WHERE role='admin' LIMIT 1").fetchone()[0]
    _patch_mcp_filter(conn, api_key)
    _patch_terminal(conn)
    _upsert_offline_model(conn, admin_id)
    conn.commit()
    conn.close()

    tool_json = (WEBUI_DB.parent / "tool_server_connections.json").read_text(encoding="utf-8").strip()
    terminal_json = "[]"
    if TERMINAL_ENV.is_file():
        tconn = sqlite3.connect(WEBUI_DB)
        row = tconn.execute("SELECT value FROM config WHERE key='terminal_server.connections'").fetchone()
        tconn.close()
        if row:
            terminal_json = row[0]
    _write_env(secret, tool_json, terminal_json)

    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip() == "true":
        subprocess.run(["docker", "restart", CONTAINER], check=True)

    print("OK Modo offline Open WebUI")
    print(f"  Modelo preset: {MODEL_ID} ({BASE_MODEL})")
    print(f"  MCP tools filtradas: {len(OFFLINE_TOOLS)} (mejor para 14B local)")
    print(f"  Runbook: offline-knowledge/RALFIA_OFFLINE_RUNBOOK.md → subir a Knowledge una vez")
    print("  En chat: + → Integrations → activar MCP + Open Terminal (una vez por chat)")


if __name__ == "__main__":
    main()
