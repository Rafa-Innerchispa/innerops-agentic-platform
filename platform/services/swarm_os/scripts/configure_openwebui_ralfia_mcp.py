#!/usr/bin/env python3
"""Configura Open WebUI con MCP RalfIA + ajustes Ollama/ngrok."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

WEBUI_DB = Path("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
SECRET_FILE = Path("/mnt/datos_agentes/ai-server-v2/open-webui/.webui_secret_key")
RAPHI_ENV = Path("/home/rlopez/projects/raphiia-openai/.env")
CONTAINER = os.environ.get("OPENWEBUI_CONTAINER", "open-webui")
MCP_LOCAL = os.environ.get("RALFIA_MCP_URL", "http://192.168.1.4:8102/mcp")
MCP_PUBLIC = os.environ.get(
    "RALFIA_MCP_PUBLIC_URL",
    "https://sworn-profusely-alongside.ngrok-free.dev/raphiia-mcp/mcp",
)
WEBUI_PUBLIC = os.environ.get(
    "OPENWEBUI_PUBLIC_URL",
    "https://sworn-profusely-alongside.ngrok-free.dev/openwebui",
)


def _load_mcp_key() -> str:
    if not RAPHI_ENV.is_file():
        raise SystemExit(f"Missing {RAPHI_ENV}")
    for line in RAPHI_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("MCP_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("MCP_API_KEY not found in raphiia-openai/.env")


def _secret_key() -> str:
    if SECRET_FILE.is_file():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_FILE.write_text(key, encoding="utf-8")
    SECRET_FILE.chmod(0o600)
    return key


def _mcp_connection(api_key: str, *, use_public: bool) -> dict:
    return {
        "type": "mcp",
        "url": MCP_PUBLIC if use_public else MCP_LOCAL,
        "auth_type": "bearer",
        "key": api_key,
        "info": {
            "id": "ralfia-mcp-public" if use_public else "ralfia-mcp-local",
            "name": "RalfIA MCP (ngrok)" if use_public else "RalfIA MCP (LAN)",
            "description": (
                "MongoDB pcdoctor_swarm, ai_coordination, search/save_memory, "
                "get_project_map, get_coordination_summary, Swarm health"
            ),
        },
        "config": {
            "enable": True,
            "access_grants": [],
            "function_name_filter_list": (
                "bootstrap_context,get_project_map,get_coordination_summary,"
                "read_coordination_file,search_coordination_docs,get_agent_mailboxes,"
                "search,search_memory,get_context_summary,"
                "get_whatsapp_status,list_ops_contacts,"
                "save_memory,save_knowledge_seed,save_ops_contact,"
                "send_whatsapp_draft,log_coordination_event"
            ),
        },
    }


def _patch_webui_db(connections: list[dict]) -> None:
    conn = sqlite3.connect(WEBUI_DB)
    merged: list[dict]

    # Open WebUI <0.10: config.id=1 row with JSON blob in `data`
    cols = {r[1] for r in conn.execute("PRAGMA table_info(config)")}
    if "data" in cols:
        row = conn.execute("SELECT data FROM config WHERE id=1").fetchone()
        if not row:
            raise SystemExit("Open WebUI config row missing")
        data = json.loads(row[0])
        data.setdefault("tool_server", {})
        existing = data["tool_server"].get("connections") or []
        keep = [
            c
            for c in existing
            if (c.get("info") or {}).get("id", "").startswith("ralfia-mcp") is False
        ]
        merged = keep + connections
        data["tool_server"]["connections"] = merged
        data.setdefault("direct", {})["enable"] = True
        conn.execute("UPDATE config SET data=? WHERE id=1", (json.dumps(data),))
    else:
        # Open WebUI >=0.10: key/value rows (e.g. tool_server.connections)
        row = conn.execute(
            "SELECT value FROM config WHERE key='tool_server.connections'"
        ).fetchone()
        existing = json.loads(row[0]) if row and row[0] else []
        keep = [
            c
            for c in existing
            if (c.get("info") or {}).get("id", "").startswith("ralfia-mcp") is False
        ]
        merged = keep + connections
        payload = json.dumps(merged)
        if row:
            conn.execute(
                "UPDATE config SET value=? WHERE key='tool_server.connections'",
                (payload,),
            )
        else:
            conn.execute(
                "INSERT INTO config (key, value) VALUES ('tool_server.connections', ?)",
                (payload,),
            )
        direct = conn.execute(
            "SELECT value FROM config WHERE key='direct.enable'"
        ).fetchone()
        if direct:
            conn.execute("UPDATE config SET value='true' WHERE key='direct.enable'")
        else:
            conn.execute(
                "INSERT INTO config (key, value) VALUES ('direct.enable', 'true')"
            )

    conn.commit()
    conn.close()

    out = WEBUI_DB.parent / "tool_server_connections.json"
    out.write_text(json.dumps(merged), encoding="utf-8")
    out.chmod(0o600)


def _docker_env(secret: str) -> None:
    """No sobrescribir openwebui.env completo — delegar a write_openwebui_env.py."""
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parent / "write_openwebui_env.py"
    if script.is_file():
        subprocess.run(["python3", str(script)], check=True)
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip() == "true":
        subprocess.run(["docker", "restart", CONTAINER], check=True)


def main() -> None:
    if not WEBUI_DB.is_file():
        raise SystemExit(f"DB not found: {WEBUI_DB}")
    api_key = _load_mcp_key()
    secret = _secret_key()
    # Prefer LAN from container; public URL as fallback entry (disabled by default if LAN works)
    connections = [_mcp_connection(api_key, use_public=False)]
    _patch_webui_db(connections)
    _docker_env(secret)
    print("OK Open WebUI — MCP RalfIA configurado")
    print(f"  Container: {CONTAINER}")
    print(f"  MCP URL (LAN): {MCP_LOCAL}")
    print(f"  MCP URL (ngrok): {MCP_PUBLIC}")
    print(f"  Open WebUI público: {WEBUI_PUBLIC}")
    print("  Admin → External Tools → verifica 'RalfIA MCP (LAN)' → Enable en chat (+ → Tools)")


if __name__ == "__main__":
    main()
