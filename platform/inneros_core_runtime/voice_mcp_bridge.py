"""Puente voz → herramientas MCP (contexto + ejecución real)."""

from __future__ import annotations

import json
import re
from typing import Any

from raphiia_openai import voice_mcp_executor
from raphiia_openai.voice_user_profile import is_rafael


def rag_preview(user: dict[str, Any], query: str, *, limit: int = 8) -> dict[str, Any]:
    """Vista debug owner-only: hybrid_search + detect_tool_calls + resultados MCP."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query vacío"}

    from raphiia_openai import hybrid_context

    detected = [
        {"tool": name, "args": args}
        for name, args in voice_mcp_executor.detect_tool_calls(user, q)
    ]
    tool_results = voice_mcp_executor.execute_for_message(user, q)
    hybrid = hybrid_context.hybrid_search(q, limit=limit)
    mcp_context = mcp_context_for_message(user, q)

    chunks: list[dict[str, Any]] = []
    for row in hybrid.get("results") or []:
        chunks.append(
            {
                "source": row.get("source"),
                "score": row.get("score"),
                "title": row.get("title"),
                "text": (row.get("text") or "")[:800],
                "url": row.get("url"),
                "brand": row.get("brand"),
                "memory_id": row.get("memory_id"),
                "project": row.get("project"),
                "expediente": row.get("expediente"),
            }
        )

    return {
        "ok": True,
        "query": q,
        "limit": limit,
        "detected_tools": detected,
        "hybrid_search": {
            "count": hybrid.get("count"),
            "qdrant": hybrid.get("qdrant"),
            "chunks": chunks,
        },
        "tool_results": tool_results,
        "mcp_context_preview": mcp_context[:4000] if mcp_context else "",
        "mcp_context_chars": len(mcp_context or ""),
    }


def mcp_context_for_message(user: dict[str, Any], text: str) -> str:
    """Ejecuta herramientas MCP relevantes y devuelve texto para el system/context."""
    if not text or not str(text).strip():
        return ""
    parts: list[str] = []

    executed = voice_mcp_executor.execute_for_message(user, text)
    formatted = voice_mcp_executor.format_tool_results(executed)
    if formatted.strip():
        parts.append(formatted)

    # Capacidades disponibles para el LLM (Rafael vs operador)
    tools = voice_mcp_executor.tools_summary_for_user(user)
    if tools:
        role = "Rafael/admin" if (is_rafael(user) or user.get("is_admin")) else "operador"
        parts.append(
            f"=== MCP disponible ({role}) ===\n"
            + ", ".join(tools[:20])
            + ("\n…" if len(tools) > 20 else "")
            + "\nUsa los resultados ejecutados arriba; no inventes datos de herramientas ni digas que «vas a» ejecutarlas."
        )

    # Fallback legacy si no hubo ejecución pero hay keywords fuertes
    if not executed:
        t = (text or "").lower()
        if is_rafael(user) or user.get("is_admin"):
            if re.search(r"\b(cotiz|quote|presupuesto)\b", t):
                parts.append(
                    "=== MCP cotizaciones ===\nPerfil quoter disponible. "
                    "Pide detalles del cliente y productos para iniciar cotización."
                )

    return "\n\n".join(parts)[:6000]
