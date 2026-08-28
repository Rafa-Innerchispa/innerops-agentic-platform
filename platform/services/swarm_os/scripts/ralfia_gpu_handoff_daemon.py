#!/usr/bin/env python3
"""Libera VRAM de Ollama cuando ComfyUI empieza a generar imagen (automático, sin intervención)."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
POLL_SEC = float(os.environ.get("GPU_HANDOFF_POLL_SEC", "2"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s gpu-handoff %(message)s")
log = logging.getLogger("gpu-handoff")


def _get_json(url: str, timeout: float = 5.0) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("GET %s failed: %s", url, exc)
        return None


def _post_json(url: str, body: dict, timeout: float = 30.0) -> bool:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        log.warning("POST %s failed: %s", url, exc)
        return False


def ollama_loaded_models() -> list[str]:
    data = _get_json(f"{OLLAMA_URL}/api/ps")
    if not isinstance(data, dict):
        return []
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def unload_ollama_models() -> None:
    names = ollama_loaded_models()
    if not names:
        return
    log.info("ComfyUI ocupando GPU → descargando Ollama: %s", ", ".join(names))
    for name in names:
        ok = _post_json(
            f"{OLLAMA_URL}/api/generate",
            {"model": name, "keep_alive": 0, "prompt": ""},
        )
        if ok:
            log.info("  unload OK: %s", name)
        else:
            log.warning("  unload falló: %s", name)


def comfyui_queue_depth() -> int:
    data = _get_json(f"{COMFYUI_URL}/queue")
    if not isinstance(data, dict):
        return 0
    running = data.get("queue_running") or []
    pending = data.get("queue_pending") or []
    return len(running) + len(pending)


def main() -> None:
    log.info("Inicio — Ollama %s · ComfyUI %s", OLLAMA_URL, COMFYUI_URL)
    was_busy = False
    while True:
        depth = comfyui_queue_depth()
        busy = depth > 0
        if busy and not was_busy:
            unload_ollama_models()
        was_busy = busy
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
