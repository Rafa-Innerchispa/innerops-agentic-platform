#!/usr/bin/env python3
"""Prueba chat Open WebUI + MCP (non-stream para qwen 14B)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request

WEBUI = "http://127.0.0.1:3000"
MODEL = "ralfia-offline"
MCP_TOOL = "server:mcp:ralfia-mcp-local"
TERMINAL = "ralfia-terminal"


def _api_key() -> str:
    c = sqlite3.connect("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
    row = c.execute("SELECT key FROM api_key ORDER BY created_at DESC LIMIT 1").fetchone()
    c.close()
    if not row:
        raise SystemExit("No API key")
    return row[0]


def _wait() -> None:
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{WEBUI}/api/config", timeout=3):
                return
        except Exception:
            time.sleep(2)
    raise SystemExit("Open WebUI down")


def _chat(key: str, prompt: str, *, stream: bool) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "tool_ids": [MCP_TOOL],
        "terminal_id": TERMINAL,
        "stream": stream,
    }
    req = urllib.request.Request(
        f"{WEBUI}/api/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    if stream:
        parts: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or choices[0].get("message") or {}
                if delta.get("content"):
                    parts.append(delta["content"])
        return {"content": "".join(parts).strip()}
    return json.loads(raw)


def main() -> None:
    _wait()
    key = _api_key()
    prompt = (
        "Llama get_project_map vía MCP y lista los proyectos reales. "
        "Formato: ## Encontré / ## Puedo hacer / ## Siguiente paso. "
        "No inventes JavaScript ni webpack."
    )
    print("Pregunta MCP (non-stream)...")
    try:
        data = _chat(key, prompt, stream=False)
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read()[:500])
        sys.exit(1)

    msg = (data.get("choices") or [{}])[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    finish = (data.get("choices") or [{}])[0].get("finish_reason")
    tool_calls = msg.get("tool_calls")

    print("\n--- META ---")
    print("finish_reason:", finish)
    print("tool_calls:", bool(tool_calls))
    print("\n--- RESPUESTA ---")
    print(content[:4000] if content else "(vacío)")
    if tool_calls:
        print("\n--- TOOL_CALLS (sin segunda vuelta) ---")
        print(json.dumps(tool_calls, indent=2)[:1500])

    if len(content) < 80 and not tool_calls:
        print("\nFAIL: vacío")
        sys.exit(2)
    bad = any(x in content.lower() for x in ("webpack", "chunk.js", "sourcemappingurl"))
    if bad:
        print("\nFAIL: alucinación webpack/JS")
        sys.exit(3)
    if finish == "tool_calls" and not content:
        print("\nWARN: modelo pidió tools pero API no devolvió texto final (normal en REST sin agentic loop)")
        sys.exit(0)
    if any(w in content.lower() for w in ("proyect", "8102", "ralf", "mongo", "servicio")):
        print("\nOK: respuesta con contexto servidor")
    else:
        print("\nWARN: respuesta sin datos MCP claros")


if __name__ == "__main__":
    main()
