"""Contexto por usuario — memoria privada vs compartida empresa."""

from __future__ import annotations

from typing import Any

from raphiia_openai import daily_memory, mongo_store
from raphiia_openai.hybrid_context import get_rafael_context, hybrid_search, qdrant_health
from raphiia_openai.settings import RALFIA_OWNER_ID


def get_user_context(
    *,
    user: dict[str, Any],
    query: str | None = None,
    entity_id: str | None = None,
    max_chars: int = 9000,
) -> dict[str, Any]:
    """Contexto filtrado por usuario autenticado."""
    owner_id = str(user.get("owner_id") or RALFIA_OWNER_ID)
    is_admin = bool(user.get("is_admin")) or owner_id == RALFIA_OWNER_ID
    allowed = user.get("allowed_privacy") or ["INTERNAL_WORK", "PROJECT", "PUBLIC"]

    if is_admin:
        return get_rafael_context(query=query, entity_id=entity_id, max_chars=max_chars)

    q = (query or "PC Doctor InnerSpark InnerChispa tecnología procesos").strip()
    parts: list[str] = [
        f"=== RalfIA — sesión {user.get('display_name') or owner_id} ===",
        "Acceso: memoria compartida de empresa (INTERNAL_WORK, PROJECT, PUBLIC).",
        "No tienes acceso a memoria personal privada de Rafael.",
        "=== Proyectos compartidos ===",
        "- PC Doctor — MSP, soporte, cotizaciones",
        "- InnerSpark — IA aplicada, Smart Quoter",
        "- InnerChispa — contenido, editorial",
    ]

    mem = daily_memory.search_memory(
        {
            "query": q,
            "actor": owner_id,
            "owner_id": None,
            "allowed_privacy": list(allowed),
            "limit": 10,
            "entity_id": entity_id,
        }
    )
    for item in mem.get("items") or []:
        parts.append(f"[memoria|{item.get('score')}] {item.get('title')}\n{(item.get('body') or '')[:500]}")

    own = daily_memory.search_memory(
        {
            "query": q,
            "actor": owner_id,
            "owner_id": owner_id,
            "allowed_privacy": list(allowed),
            "limit": 6,
        }
    )
    for item in own.get("items") or []:
        parts.append(f"[tu memoria|{item.get('score')}] {item.get('title')}\n{(item.get('body') or '')[:400]}")

    hybrid = hybrid_search(q, limit=10, entity_id=entity_id, include_memory=False)
    for row in hybrid.get("results") or []:
        if row.get("source") == "qdrant":
            parts.append(f"[kb|{row.get('score')}] {row.get('title')}\n{(row.get('text') or '')[:500]}")

    try:
        summary = mongo_store.get_context_summary()
        parts.insert(
            1,
            f"Ops PC Doctor: clientes={summary.get('clients', '?')} ideas={summary.get('ideas', '?')}",
        )
    except Exception:
        pass

    blob = "\n\n".join(parts)
    if len(blob) > max_chars:
        blob = blob[: max_chars - 80] + "\n\n...[contexto truncado]"

    return {
        "ok": True,
        "owner_id": owner_id,
        "context": blob,
        "char_count": len(blob),
        "meta": {
            "is_admin": False,
            "allowed_privacy": allowed,
            "hybrid_count": hybrid.get("count"),
            "memory_count": mem.get("count"),
        },
    }


def user_search(
    *,
    user: dict[str, Any],
    query: str,
    limit: int = 10,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Búsqueda híbrida filtrada por permisos del usuario."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query vacío"}

    owner_id = str(user.get("owner_id") or RALFIA_OWNER_ID)
    is_admin = bool(user.get("is_admin")) or owner_id == RALFIA_OWNER_ID
    if is_admin:
        return hybrid_search(q, limit=limit, entity_id=entity_id)

    allowed = user.get("allowed_privacy") or ["INTERNAL_WORK", "PROJECT", "PUBLIC"]
    results: list[dict[str, Any]] = []

    shared = daily_memory.search_memory(
        {
            "query": q,
            "actor": owner_id,
            "owner_id": None,
            "allowed_privacy": list(allowed),
            "limit": max(4, limit // 2),
            "entity_id": entity_id,
        }
    )
    for item in shared.get("items") or []:
        results.append(
            {
                "source": "memory",
                "score": float(item.get("score") or 0),
                "title": item.get("title") or item.get("kind") or "memory",
                "text": (item.get("body") or "")[:1200],
                "memory_id": item.get("memory_id"),
                "project": item.get("project"),
            }
        )

    own = daily_memory.search_memory(
        {
            "query": q,
            "actor": owner_id,
            "owner_id": owner_id,
            "allowed_privacy": list(allowed),
            "limit": max(3, limit // 3),
        }
    )
    for item in own.get("items") or []:
        results.append(
            {
                "source": "memory",
                "score": float(item.get("score") or 0),
                "title": item.get("title") or item.get("kind") or "memory",
                "text": (item.get("body") or "")[:1200],
                "memory_id": item.get("memory_id"),
                "project": item.get("project"),
            }
        )

    hybrid = hybrid_search(q, limit=limit, entity_id=entity_id, include_memory=False)
    results.extend(hybrid.get("results") or [])

    results.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return {
        "ok": True,
        "query": q,
        "count": min(len(results), limit),
        "results": results[:limit],
        "owner_id": owner_id,
        "allowed_privacy": allowed,
    }
