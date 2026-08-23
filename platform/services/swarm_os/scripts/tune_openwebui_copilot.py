#!/usr/bin/env python3
"""Afinar Open WebUI 0.10.2 — preset RalfIA Copilot con integraciones por defecto."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

WEBUI_DB = Path("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
ENV_FILE = Path("/mnt/datos_agentes/ai-server-v2/open-webui/openwebui.env")
TERMINAL_ENV = Path("/home/rlopez/data/open-terminal/open-terminal.env")
TERMINAL_PORT = int(__import__("os").environ.get("OPEN_TERMINAL_PORT", "8010"))
CONTAINER = __import__("os").environ.get("OPENWEBUI_CONTAINER", "open-webui")
RAPHI_ENV = Path("/home/rlopez/projects/raphiia-openai/.env")

MODEL_ID = "ralfia-offline"
DISPLAY_NAME = "RalfIA Copilot (qwen 14B)"
BASE_MODEL = "qwen2.5:14b-instruct-q4_K_M"
MCP_TOOL_ID = "server:mcp:ralfia-mcp-local"
TERMINAL_ID = "ralfia-terminal"
COMFYUI_URL = "http://192.168.1.4:8188"

# Presets adicionales (ajuste por modelo / VRAM)
EXTRA_PRESETS = [
    {
        "id": "ralfia-fast",
        "name": "RalfIA Fast (qwen 7B)",
        "base": "qwen2.5:7b",
        "num_ctx": 8192,
        "temperature": 0.3,
        "note": "Más rápido y estable en tools; menos razonamiento que 14B.",
    },
    {
        "id": "ralfia-vision",
        "name": "RalfIA Vision (llava 7B)",
        "base": "llava:7b",
        "num_ctx": 4096,
        "temperature": 0.2,
        "note": "Describir/analizar imágenes. Sin MCP pesado — descarga qwen antes.",
        "mcp": False,
        "features": [],
    },
]

# MCP ampliado (~23 tools): ops + imagen local ComfyUI
COPILOT_TOOLS = [
    "bootstrap_context",
    "get_project_map",
    "get_coordination_summary",
    "read_coordination_file",
    "search_coordination_docs",
    "get_agent_mailboxes",
    "list_recent_changes",
    "search",
    "search_memory",
    "get_context_summary",
    "fetch",
    "describe_tool",
    "system_health",
    "get_whatsapp_status",
    "list_ops_contacts",
    "save_memory",
    "save_knowledge_seed",
    "save_ops_contact",
    "send_whatsapp_draft",
    "log_coordination_event",
    "generate_local_image",
    "local_image_health",
    "list_local_image_backends",
]

# Alias legacy
OFFLINE_TOOLS = COPILOT_TOOLS

SYSTEM_PROMPT = """Eres RalfIA Copilot en Open WebUI — asistente operativo de Rafael (PC Doctor / InnerSpark).

## Qué puedes hacer (usa MCP, no simules)
- **Contexto:** bootstrap_context, get_project_map, read_coordination_file, get_agent_mailboxes (INBOX agentes).
- **Buscar:** search (clientes, ideas, pipeline), search_memory, search_coordination_docs.
- **Recordar:** save_memory (preferencias, metas, datos duraderos) y save_knowledge_seed (hechos operativos).
- **Contactos/WhatsApp:** list_ops_contacts, save_ops_contact; envíos solo con send_whatsapp_draft (borrador). Nunca send_whatsapp_message directo.
- **Coordinación:** log_coordination_event para hitos importantes.

## Reglas
1. Responde en español: ## Encontré / ## Puedo hacer / ## Siguiente paso.
2. PROHIBIDO inventar JavaScript, webpack, JSON o simular tools en texto. Solo datos de tools reales.
3. WhatsApp: redacta borrador y pide confirmación explícita de Rafael antes de enviar.
4. Informes técnicos nuevos o clientes por RUC: aún no hay tool MCP — usa search para buscar existentes o Open Terminal (curl API :8100/:8101) si Rafael lo pide.
- **Imagen local:** generate_local_image (ComfyUI RealVisXL :8188). Si falla por VRAM, avisa que hay que liberar GPU (qwen ocupa ~8GB).

PRIORIDAD: MCP → Knowledge → Memory UI → Terminal → web search.
Puertos: 8101 API clientes, 8102 MCP, 8100 swarm, 3000 Open WebUI, 8010 terminal."""


def _load_mcp_key() -> str:
    for line in RAPHI_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("MCP_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("MCP_API_KEY missing")


def _set(conn: sqlite3.Connection, key: str, value: str) -> None:
    """value must be valid JSON string (Open WebUI 0.10 parses all config as JSON)."""
    if conn.execute("SELECT 1 FROM config WHERE key=?", (key,)).fetchone():
        conn.execute("UPDATE config SET value=? WHERE key=?", (value, key))
    else:
        conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, value))


def main() -> None:
    api_key = _load_mcp_key()
    conn = sqlite3.connect(WEBUI_DB)
    admin_id = conn.execute("SELECT id FROM user WHERE role='admin' LIMIT 1").fetchone()[0]

    # --- MCP ---
    mcp = {
        "type": "mcp",
        "url": "http://192.168.1.4:8102/mcp",
        "auth_type": "bearer",
        "key": api_key,
        "info": {
            "id": "ralfia-mcp-local",
            "name": "RalfIA MCP (LAN)",
            "description": "Mongo pcdoctor_swarm + ai_coordination (LAN). Usar para datos del servidor.",
        },
        "config": {
            "enable": True,
            "access_grants": [],
            "function_name_filter_list": ",".join(COPILOT_TOOLS),
        },
    }
    _set(conn, "tool_server.connections", json.dumps([mcp]))
    (WEBUI_DB.parent / "tool_server_connections.json").write_text(json.dumps([mcp]), encoding="utf-8")

    # --- Terminal (id top-level requerido por 0.10) ---
    term_key = ""
    if TERMINAL_ENV.is_file():
        term_key = TERMINAL_ENV.read_text(encoding="utf-8").split("=", 1)[1].strip()
    terminal = [
        {
            "id": TERMINAL_ID,
            "name": "RalfIA Terminal (LAN)",
            "url": f"http://host.docker.internal:{TERMINAL_PORT}",
            "key": term_key,
            "auth_type": "bearer",
            "enabled": True,
            "info": {"id": TERMINAL_ID, "name": "RalfIA Terminal (LAN)"},
            "config": {"enable": True, "access_grants": []},
        }
    ]
    _set(conn, "terminal_server.connections", json.dumps(terminal))

    # --- Features 0.10 ---
    _set(conn, "web.search.enable", "true")
    _set(conn, "web.search.engine", "ddgs")
    _set(conn, "web.search.confirmation.enable", "false")
    _set(conn, "memories.enable", "true")
    _set(conn, "memories.system_context.enable", "true")
    _set(conn, "memories.background_review.enable", "true")
    # 0.10 — compaction chats largos (off por defecto; umbral alto)
    _set(conn, "chat.context_compaction.enable", "false")
    _set(conn, "chat.context_compaction.token_threshold", "120000")
    _set(conn, "notes.enable", "true")
    _set(conn, "automations.enable", "true")
    _set(conn, "calendar.enable", "true")
    _set(conn, "direct.enable", "true")
    _set(conn, "code_interpreter.enable", "false")
    # Imagen local ComfyUI (SDXL turbo en :8188 — comparte GPU con Ollama)
    _set(conn, "image_generation.enable", json.dumps(True))
    _set(conn, "image_generation.engine", json.dumps("comfyui"))
    _set(conn, "image_generation.comfyui.base_url", json.dumps(COMFYUI_URL))
    _set(conn, "images.edit.comfyui.base_url", json.dumps(COMFYUI_URL))
    # workflow/nodes/model los fija fix_openwebui_image_config.py (evita ckpt_name vacío)
    _set(conn, "image_generation.size", json.dumps("1024x1024"))
    _set(conn, "image_generation.steps", json.dumps(8))
    _set(conn, "images.edit.enable", json.dumps(False))
    _set(conn, "models.default_params", json.dumps({
        "function_calling": "native",
        "temperature": 0.3,
        "top_p": 0.9,
    }))

    # --- Preset modelo ---
    kb_row = conn.execute("SELECT id, name FROM knowledge WHERE name LIKE 'RalfIA%' LIMIT 1").fetchone()
    knowledge = [{"id": kb_row[0], "name": kb_row[1]}] if kb_row else []

    now = int(time.time())
    params = {
        "system": SYSTEM_PROMPT,
        "function_calling": "native",
        "temperature": 0.25,
        "top_p": 0.9,
        "num_ctx": 8192,
        "stream_response": False,
        "keep_alive": "30s",
    }
    meta = {
        "description": "Asistente principal: MCP + terminal + Knowledge + memoria + web. Integraciones ON por defecto.",
        "tags": [{"name": "ralfia"}, {"name": "copilot"}],
        "toolIds": [MCP_TOOL_ID],
        "terminalId": TERMINAL_ID,
        "defaultFeatureIds": ["web_search", "image_generation"],
        "knowledge": knowledge,
        "capabilities": {
            "code_interpreter": False,
            "terminal": True,
            "builtin_tools": True,
            "file_context": True,
            "memory": True,
            "web_search": True,
            "image_generation": True,
        },
    }

    if conn.execute("SELECT 1 FROM model WHERE id=?", (MODEL_ID,)).fetchone():
        conn.execute(
            "UPDATE model SET name=?, base_model_id=?, params=?, meta=?, updated_at=?, is_active=1 WHERE id=?",
            (DISPLAY_NAME, BASE_MODEL, json.dumps(params), json.dumps(meta), now, MODEL_ID),
        )
    else:
        conn.execute(
            "INSERT INTO model (id,user_id,base_model_id,name,params,meta,created_at,updated_at,is_active) VALUES (?,?,?,?,?,?,?,?,1)",
            (MODEL_ID, admin_id, BASE_MODEL, DISPLAY_NAME, json.dumps(params), json.dumps(meta), now, now),
        )

    for preset in EXTRA_PRESETS:
        pid = preset["id"]
        pparams = {
            "function_calling": "native",
            "temperature": preset["temperature"],
            "num_ctx": preset["num_ctx"],
            "stream_response": False,
        }
        pmeta = {
            "description": preset.get("note", ""),
            "tags": [{"name": "ralfia"}],
            "capabilities": {
                "memory": True,
                "web_search": preset.get("mcp", True),
                "image_generation": preset["id"] != "ralfia-vision",
                "terminal": preset.get("mcp", True),
                "builtin_tools": True,
                "code_interpreter": False,
            },
        }
        if preset.get("mcp", True):
            pmeta["toolIds"] = [MCP_TOOL_ID]
            pmeta["terminalId"] = TERMINAL_ID
            pmeta["defaultFeatureIds"] = ["web_search", "image_generation"]
            pmeta["knowledge"] = knowledge
        else:
            pmeta["defaultFeatureIds"] = []
        if conn.execute("SELECT 1 FROM model WHERE id=?", (pid,)).fetchone():
            conn.execute(
                "UPDATE model SET name=?, base_model_id=?, params=?, meta=?, updated_at=?, is_active=1 WHERE id=?",
                (preset["name"], preset["base"], json.dumps(pparams), json.dumps(pmeta), now, pid),
            )
        else:
            conn.execute(
                "INSERT INTO model (id,user_id,base_model_id,name,params,meta,created_at,updated_at,is_active) VALUES (?,?,?,?,?,?,?,?,1)",
                (pid, admin_id, preset["base"], preset["name"], json.dumps(pparams), json.dumps(pmeta), now, now),
            )

    _set(conn, "ui.default_models", json.dumps(MODEL_ID))
    _set(conn, "ui.default_pinned_models", json.dumps([MODEL_ID]))

    conn.commit()
    conn.close()

    subprocess.run(
        ["python3", str(Path(__file__).resolve().parent / "write_openwebui_env.py")],
        check=True,
    )

    proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip() == "true":
        subprocess.run(["docker", "restart", CONTAINER], check=True)

    # Daemon automático GPU (Ollama ↔ ComfyUI) — sin scripts manuales
    svc = Path.home() / ".config/systemd/user/ralfia-gpu-handoff.service"
    if svc.is_file():
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", "ralfia-gpu-handoff.service"], check=False)

    fix_img = Path(__file__).resolve().parent / "fix_openwebui_image_config.py"
    if fix_img.is_file():
        subprocess.run(["python3", str(fix_img)], check=True)

    print("OK RalfIA Copilot tuned")
    print(f"  toolIds: {MCP_TOOL_ID}")
    print(f"  terminalId: {TERMINAL_ID}")
    print("  defaultFeatureIds: web_search, image_generation")
    print("  image_generation: comfyui", COMFYUI_URL)
    print("  MCP tools:", len(COPILOT_TOOLS))


if __name__ == "__main__":
    main()
