"""DocVault — búsqueda de expedientes y recuperación de documentos completos."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from raphiia_openai.settings import OLLAMA_URL, QDRANT_URL

DOCVAULT_COLLECTION = "docvault"
DOCVAULT_ROOT = Path("/home/rlopez/data/docvault")
EMBED_MODEL = "nomic-embed-text"

EXPEDIENTE_RE = re.compile(
    r"(?:exp(?:ediente)?|caso|file|folio|n[°o]?)\s*[:#-]?\s*(\d{3,6}(?:\s*[-/]\s*\d{1,4})?)",
    re.I,
)
NUM_RE = re.compile(r"\b(\d{4,6}[-/]\d{1,4})\b")


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


def _embed(text: str) -> list[float] | None:
    resp = _http_json(
        f"{OLLAMA_URL.rstrip('/')}/api/embeddings",
        method="POST",
        body={"model": EMBED_MODEL, "prompt": text[:4000]},
        timeout=120.0,
    )
    return resp.get("embedding")


def extract_expediente_query(query: str) -> str | None:
    q = (query or "").strip()
    for pat in (EXPEDIENTE_RE, NUM_RE):
        m = pat.search(q)
        if m:
            return re.sub(r"\s+", "", m.group(1))
    return None


def docvault_health(qdrant_url: str | None = None) -> dict[str, Any]:
    base = (qdrant_url or QDRANT_URL).rstrip("/")
    r = _http_json(f"{base}/collections/{DOCVAULT_COLLECTION}", timeout=5.0)
    if r.get("error") or not r.get("result"):
        return {"ok": False, "collection": DOCVAULT_COLLECTION, "error": r.get("error") or "missing"}
    return {
        "ok": True,
        "collection": DOCVAULT_COLLECTION,
        "points_count": r["result"].get("points_count"),
        "root": str(DOCVAULT_ROOT),
    }


def search_docvault(
    query: str,
    *,
    limit: int = 8,
    expediente: str | None = None,
    qdrant_url: str | None = None,
) -> dict[str, Any]:
    """Búsqueda semántica + filtro por número de expediente."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query vacío"}

    health = docvault_health(qdrant_url)
    if not health.get("ok"):
        return {"ok": False, "error": "docvault_not_ready", "health": health}

    exp = expediente or extract_expediente_query(q)
    base = (qdrant_url or QDRANT_URL).rstrip("/")
    limit = max(1, min(int(limit), 20))

    # Búsqueda exacta por expediente
    if exp:
        scroll = _http_json(
            f"{base}/collections/{DOCVAULT_COLLECTION}/points/scroll",
            method="POST",
            body={
                "filter": {"must": [{"key": "expediente", "match": {"value": exp}}]},
                "limit": limit,
                "with_payload": True,
            },
            timeout=30.0,
        )
        exact: list[dict[str, Any]] = []
        for pt in scroll.get("result", {}).get("points") or []:
            payload = pt.get("payload") or {}
            exact.append(_hit_from_payload(payload, score=1.0, match_type="expediente_exacto"))
        if exact:
            seen: set[str] = set()
            unique = []
            for h in exact:
                fid = h.get("file_id") or ""
                if fid and fid in seen:
                    continue
                seen.add(fid)
                unique.append(h)
            return {"ok": True, "query": q, "expediente": exp, "count": len(unique), "results": unique[:limit]}

    vector = _embed(q)
    if not vector:
        return {"ok": False, "error": "embedding_failed"}

    search = _http_json(
        f"{base}/collections/{DOCVAULT_COLLECTION}/points/search",
        method="POST",
        body={"vector": vector, "limit": limit, "with_payload": True},
        timeout=60.0,
    )
    hits: list[dict[str, Any]] = []
    for row in search.get("result") or []:
        payload = row.get("payload") or {}
        hits.append(_hit_from_payload(payload, score=float(row.get("score") or 0), match_type="semantico"))
    return {"ok": True, "query": q, "expediente": exp, "count": len(hits), "results": hits}


def _hit_from_payload(payload: dict[str, Any], *, score: float, match_type: str) -> dict[str, Any]:
    return {
        "source": "docvault",
        "match_type": match_type,
        "score": round(score, 4),
        "file_id": payload.get("file_id"),
        "expediente": payload.get("expediente"),
        "title": payload.get("title") or payload.get("filename"),
        "text": (payload.get("text") or "")[:1200],
        "text_path": payload.get("text_path"),
        "original_path": payload.get("original_path"),
        "chunk_index": payload.get("chunk_index"),
    }


def get_document(identifier: str) -> dict[str, Any]:
    """Recupera texto completo por expediente, file_id o nombre de archivo."""
    ident = (identifier or "").strip()
    if not ident:
        return {"ok": False, "error": "identifier_required"}

    meta_dir = DOCVAULT_ROOT / "meta"
    text_dir = DOCVAULT_ROOT / "text"

    # Meta por file_id
    meta_path = meta_dir / f"{ident}.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return _load_full_doc(meta)

    # Buscar en metadatos por expediente o filename
    for mp in meta_dir.glob("*.json"):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("expediente") == ident or meta.get("filename") == ident:
            return _load_full_doc(meta)

    # Fallback Qdrant
    found = search_docvault(ident, limit=1, expediente=extract_expediente_query(ident))
    if found.get("ok") and found.get("results"):
        hit = found["results"][0]
        fid = hit.get("file_id")
        if fid:
            mp = meta_dir / f"{fid}.json"
            if mp.is_file():
                return _load_full_doc(json.loads(mp.read_text(encoding="utf-8")))
        text_path = hit.get("text_path")
        if text_path and Path(text_path).is_file():
            text = Path(text_path).read_text(encoding="utf-8", errors="replace")
            return {
                "ok": True,
                "file_id": fid,
                "expediente": hit.get("expediente"),
                "title": hit.get("title"),
                "char_count": len(text),
                "text": text[:50000],
                "truncated": len(text) > 50000,
                "text_path": text_path,
            }

    return {"ok": False, "error": "document_not_found", "identifier": ident}


def _load_full_doc(meta: dict[str, Any]) -> dict[str, Any]:
    text_path = Path(meta.get("text_path") or "")
    if not text_path.is_file():
        text_path = DOCVAULT_ROOT / "text" / f"{meta.get('file_id')}.txt"
    if not text_path.is_file():
        return {"ok": False, "error": "text_file_missing", "meta": meta}
    text = text_path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "file_id": meta.get("file_id"),
        "expediente": meta.get("expediente"),
        "title": meta.get("filename"),
        "char_count": len(text),
        "text": text[:50000],
        "truncated": len(text) > 50000,
        "text_path": str(text_path),
        "original_path": meta.get("original_path"),
        "meta": meta,
    }
