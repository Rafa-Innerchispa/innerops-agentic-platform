"""Contexto unificado Rafael — Mongo memoria + Qdrant semántico + ops."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.settings import (
    MONGO_DB,
    OLLAMA_URL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RALFIA_OWNER_ID,
)


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 60.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def qdrant_health() -> dict[str, Any]:
    r = _http_json(f"{QDRANT_URL.rstrip('/')}/collections", timeout=5.0)
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    cols = [c.get("name") for c in (r.get("result") or {}).get("collections") or []]
    info: dict[str, Any] = {"ok": True, "collections": cols}
    if QDRANT_COLLECTION in cols:
        detail = _http_json(f"{QDRANT_URL.rstrip('/')}/collections/{QDRANT_COLLECTION}", timeout=5.0)
        info["points_count"] = ((detail.get("result") or {}).get("points_count"))
    else:
        info["ok"] = False
        info["missing_collection"] = QDRANT_COLLECTION
    return info


def qdrant_search(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit), 20))
    emb_resp = _http_json(
        f"{OLLAMA_URL.rstrip('/')}/api/embeddings",
        method="POST",
        body={"model": "nomic-embed-text", "prompt": q},
        timeout=90.0,
    )
    embedding = emb_resp.get("embedding")
    if not embedding:
        return []
    search_resp = _http_json(
        f"{QDRANT_URL.rstrip('/')}/collections/{QDRANT_COLLECTION}/points/search",
        method="POST",
        body={"vector": embedding, "limit": limit, "with_payload": True},
        timeout=60.0,
    )
    hits: list[dict[str, Any]] = []
    for hit in search_resp.get("result") or []:
        payload = hit.get("payload") or {}
        hits.append(
            {
                "source": "qdrant",
                "score": round(float(hit.get("score") or 0), 4),
                "title": payload.get("title") or payload.get("source") or "",
                "text": (payload.get("text") or payload.get("content") or "")[:1200],
                "brand": payload.get("brand"),
                "url": payload.get("url"),
            }
        )
    return hits


def hybrid_search(
    query: str,
    *,
    limit: int = 12,
    entity_id: str | None = None,
    project: str | None = None,
    include_qdrant: bool = True,
    include_memory: bool = True,
    include_ops: bool = True,
    include_docvault: bool = True,
) -> dict[str, Any]:
    """Búsqueda híbrida: memoria personal + Qdrant (Notion/Drive) + Mongo ops."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query vacío"}

    results: list[dict[str, Any]] = []
    qdrant_status: dict[str, Any] = {"ok": False}

    if include_memory:
        mem = mongo_store.search_memory(query=q, limit=max(4, limit // 2), entity_id=entity_id, project=project)
        items = mem if isinstance(mem, list) else mem.get("items") or []
        for item in items:
            results.append(
                {
                    "source": "memory",
                    "score": float(item.get("score") or 0),
                    "title": item.get("title") or item.get("kind") or "memory",
                    "text": (item.get("body") or item.get("content") or "")[:1200],
                    "memory_id": item.get("memory_id"),
                    "project": item.get("project") or (item.get("metadata") or {}).get("project"),
                }
            )

    if include_qdrant:
        qdrant_status = qdrant_health()
        if qdrant_status.get("ok"):
            for hit in qdrant_search(q, limit=max(4, limit // 2)):
                results.append(hit)

    if include_docvault:
        try:
            from raphiia_openai import docvault_store

            dv = docvault_store.search_docvault(q, limit=max(3, limit // 3))
            if dv.get("ok"):
                for hit in dv.get("results") or []:
                    results.append(
                        {
                            "source": "docvault",
                            "score": float(hit.get("score") or 0),
                            "title": hit.get("title") or hit.get("expediente") or "documento",
                            "text": (hit.get("text") or "")[:1200],
                            "expediente": hit.get("expediente"),
                            "file_id": hit.get("file_id"),
                            "match_type": hit.get("match_type"),
                        }
                    )
        except Exception:
            pass

    if include_ops:
        for row in mongo_store.search(q, limit=6):
            results.append(
                {
                    "source": row.get("_collection") or "mongo",
                    "score": 0.5,
                    "title": row.get("title") or row.get("name") or row.get("task_id") or str(row.get("_id")),
                    "text": (row.get("body") or row.get("markdown") or row.get("content") or row.get("summary") or "")[:800],
                }
            )

    results.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return {
        "ok": True,
        "query": q,
        "count": min(len(results), limit),
        "results": results[:limit],
        "qdrant": qdrant_status,
        "owner_id": RALFIA_OWNER_ID,
    }


def get_rafael_context(
    *,
    query: str | None = None,
    entity_id: str | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Paquete de contexto listo para inyectar en LLM (voz, chat, agentes)."""
    from raphiia_openai import daily_memory

    parts: list[str] = []
    meta: dict[str, Any] = {"owner_id": RALFIA_OWNER_ID}

    try:
        summary = mongo_store.get_context_summary()
        meta["summary"] = summary
        parts.append(
            "=== RalfIA snapshot ===\n"
            f"DB: {MONGO_DB}\n"
            f"Clientes: {summary.get('clients', summary.get('client_count', '?'))}\n"
            f"Ideas: {summary.get('ideas', summary.get('idea_count', '?'))}\n"
            f"Pipeline editorial: {summary.get('editorial_pipeline', '?')}\n"
        )
    except Exception as exc:
        meta["summary_error"] = str(exc)

    try:
        state = daily_memory.get_current_state({"owner_id": RALFIA_OWNER_ID})
        if state.get("ok") and state.get("state"):
            doc = state["state"]
            meta["current_state"] = doc
            parts.append(f"[Estado] {doc.get('state_key')}: {doc.get('body') or doc.get('summary')}")
    except Exception as exc:
        meta["state_error"] = str(exc)

    try:
        db = mongo_store.get_db()
        pending_rows = list(
            db["daily_life_pending_items"].find(
                {"owner_id": RALFIA_OWNER_ID, "status": "open"},
                {"_id": 0},
            ).limit(10)
        )
        if pending_rows:
            meta["pending_count"] = len(pending_rows)
            for p in pending_rows[:8]:
                parts.append(f"[Pendiente] {p.get('title') or p.get('body')}")
    except Exception as exc:
        meta["pending_error"] = str(exc)

    q = (query or "Rafael proyectos PC Doctor InnerChispa InnerSpark RalfIA").strip()
    hybrid = hybrid_search(q, limit=14, entity_id=entity_id)
    meta["hybrid"] = {"count": hybrid.get("count"), "qdrant": hybrid.get("qdrant")}
    for row in hybrid.get("results") or []:
        parts.append(
            f"[{row.get('source')}|{row.get('score')}] {row.get('title')}\n{(row.get('text') or '')[:600]}"
        )

    projects = [
        ("ent_pcdoctor", "PC Doctor — MSP, cotizaciones, soporte técnico Ecuador"),
        ("ent_innerchispa", "InnerChispa — contenido, comunidad, editorial"),
        ("ent_innerspark", "InnerSpark — emprendimiento, Smart Quoter, IA aplicada"),
        ("ent_rafael_personal", "Rafael personal — familia, salud, relaciones"),
    ]
    parts.insert(1, "=== Proyectos activos ===\n" + "\n".join(f"- {p}: {d}" for p, d in projects))

    blob = "\n\n".join(parts)
    if len(blob) > max_chars:
        blob = blob[: max_chars - 80] + "\n\n...[contexto truncado]"

    return {
        "ok": True,
        "owner_id": RALFIA_OWNER_ID,
        "context": blob,
        "char_count": len(blob),
        "meta": meta,
    }
