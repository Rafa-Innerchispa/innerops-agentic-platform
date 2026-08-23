#!/usr/bin/env python3
"""Repara config JSON de imagen Open WebUI + presets Imagen HD / Rápida."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from comfyui_image_profiles import (  # noqa: E402
    IMAGE_PROMPT_TEMPLATE,
    IMAGEN_RAPIDA_SYSTEM,
    IMAGEN_SYSTEM,
    build_workflow,
    pick_quality_checkpoint,
    profile_for,
    workflow_nodes,
)

WEBUI_DB = Path("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
COMFYUI_URL = "http://192.168.1.4:8188"


def _upsert_json(conn: sqlite3.Connection, key: str, value) -> None:
    payload = json.dumps(value)
    if conn.execute("SELECT 1 FROM config WHERE key=?", (key,)).fetchone():
        conn.execute("UPDATE config SET value=? WHERE key=?", (payload, key))
    else:
        conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, payload))


def fix_image_config(conn: sqlite3.Connection) -> str:
    ckpt = pick_quality_checkpoint()
    profile = profile_for(ckpt)
    _upsert_json(conn, "image_generation.enable", True)
    _upsert_json(conn, "image_generation.engine", "comfyui")
    _upsert_json(conn, "image_generation.comfyui.base_url", COMFYUI_URL)
    _upsert_json(conn, "images.edit.comfyui.base_url", COMFYUI_URL)
    _upsert_json(conn, "image_generation.comfyui.api_key", "")
    _upsert_json(conn, "images.edit.comfyui.api_key", "")
    _upsert_json(conn, "image_generation.comfyui.workflow", json.dumps(build_workflow(profile)))
    _upsert_json(conn, "image_generation.comfyui.nodes", workflow_nodes(profile))
    _upsert_json(conn, "image_generation.size", "1024x1024")
    _upsert_json(conn, "image_generation.model", ckpt)
    _upsert_json(conn, "image_generation.steps", profile["steps"])
    _upsert_json(conn, "image_generation.prompt.enable", True)
    _upsert_json(conn, "task.image.prompt_template", IMAGE_PROMPT_TEMPLATE)
    _upsert_json(conn, "images.edit.enable", False)
    return ckpt


def unstuck_chats(conn: sqlite3.Connection) -> int:
    n = 0
    for cid, chat_raw in conn.execute("SELECT id, chat FROM chat"):
        ch = json.loads(chat_raw)
        msgs = ch.get("history", {}).get("messages", {})
        changed = False
        for m in msgs.values():
            if m.get("role") == "assistant" and not m.get("done"):
                m["done"] = True
                if not (m.get("content") or "").strip():
                    m["content"] = (
                        "Generación interrumpida. Recarga con Ctrl+F5 y usa "
                        "**RalfIA Imagen HD (local)** para fotorrealismo."
                    )
                changed = True
                n += 1
        if changed:
            conn.execute("UPDATE chat SET chat=? WHERE id=?", (json.dumps(ch), cid))
    return n


def _upsert_preset(
    conn: sqlite3.Connection,
    *,
    pid: str,
    name: str,
    base: str,
    system: str,
    description: str,
    tags: list[str],
) -> None:
    admin_id = conn.execute("SELECT id FROM user WHERE role='admin' LIMIT 1").fetchone()[0]
    now = int(time.time())
    params = {
        "function_calling": "legacy",
        "temperature": 0.6,
        "stream_response": True,
        "keep_alive": "30s",
        "system": system,
    }
    meta = {
        "description": description,
        "tags": [{"name": t} for t in tags],
        "defaultFeatureIds": ["image_generation"],
        "toolIds": [],
        "knowledge": [],
        "capabilities": {
            "image_generation": True,
            "web_search": False,
            "memory": False,
            "terminal": False,
            "code_interpreter": False,
            "builtin_tools": True,
            "file_context": False,
        },
    }
    if conn.execute("SELECT 1 FROM model WHERE id=?", (pid,)).fetchone():
        conn.execute(
            "UPDATE model SET name=?, base_model_id=?, params=?, meta=?, updated_at=?, is_active=1 WHERE id=?",
            (name, base, json.dumps(params), json.dumps(meta), now, pid),
        )
    else:
        conn.execute(
            "INSERT INTO model (id,user_id,base_model_id,name,params,meta,created_at,updated_at,is_active) VALUES (?,?,?,?,?,?,?,?,1)",
            (pid, admin_id, base, name, json.dumps(params), json.dumps(meta), now, now),
        )


def add_imagen_presets(conn: sqlite3.Connection, ckpt: str) -> None:
    hd = ckpt != "sd_xl_turbo_1.0_fp16.safetensors"
    _upsert_preset(
        conn,
        pid="ralfia-imagen",
        name="RalfIA Imagen HD (local)" if hd else "RalfIA Imagen (local — turbo)",
        base="qwen2.5:7b",
        system=IMAGEN_SYSTEM,
        description=(
            "Fotorrealismo RealVisXL: personas reales, futurista, detalle. "
            "~30–60 s por imagen en RTX 3060."
            if hd
            else "Solo turbo instalado — ejecuta install_comfyui_realvis_checkpoint.sh para HD."
        ),
        tags=["ralfia", "imagen", "hd" if hd else "turbo"],
    )
    _upsert_preset(
        conn,
        pid="ralfia-imagen-rapida",
        name="RalfIA Imagen Rápida",
        base="qwen2.5:7b",
        system=IMAGEN_RAPIDA_SYSTEM,
        description="SDXL turbo ~8 pasos — bocetos rápidos, estilo más cartoon.",
        tags=["ralfia", "imagen", "rapida"],
    )


def main() -> None:
    conn = sqlite3.connect(WEBUI_DB)
    ckpt = fix_image_config(conn)
    unstuck = unstuck_chats(conn)
    add_imagen_presets(conn, ckpt)
    conn.commit()
    conn.close()
    subprocess.run(["docker", "restart", "open-webui"], check=False)
    profile = profile_for(ckpt)
    print(
        f"OK image config: {ckpt} ({profile['label']}), "
        f"steps={profile['steps']}, unstuck={unstuck}"
    )


if __name__ == "__main__":
    main()
