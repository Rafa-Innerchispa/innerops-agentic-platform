"""Memoria organizacional REAL — MongoDB + docs del servidor."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from tools.mongo import get_db

DOCS_ROOT = Path(os.getenv("RALPHI_DATA_DOCS", "/home/rlopez/data/docs"))
MAX_CHARS = 14000

_COLLECTIONS: list[tuple[str, list[str]]] = [
    ("sop_visits", ["raw_input", "findings", "pending_tasks", "code", "estado"]),
    ("technical_reports", [
        "resumen_ejecutivo", "hallazgos_clave", "recomendaciones",
        "bitacora", "ubicacion", "findings", "code",
    ]),
    ("reports", ["summary", "findings_text", "recommendations", "work_done", "location"]),
    ("inspections", ["raw_input", "findings", "pending_tasks", "status"]),
    ("documents", ["document_id", "target_type", "target_id", "path", "formato"]),
    ("clients", ["name", "trade_name", "address", "city", "activity"]),
]


def _tokenize(query: str) -> list[str]:
    raw = re.findall(r"[a-záéíóúüñ0-9]{3,}", query.lower())
    stop = {"que", "sabemos", "sobre", "para", "como", "esta", "este", "deberiamos", "ahora"}
    return [t for t in raw if t not in stop][:12]


def _doc_text(doc: dict[str, Any], fields: list[str]) -> str:
    parts: list[str] = []
    for f in fields:
        val = doc.get(f)
        if val is None or val == "" or val == []:
            continue
        if isinstance(val, list):
            val = "; ".join(str(x) for x in val[:6])
        parts.append(f"{f}: {val}")
    return " | ".join(parts)


def _score(text: str, tokens: list[str]) -> int:
    low = text.lower()
    return sum(2 if t in low else 0 for t in tokens)


def _search_mongo(tokens: list[str], limit: int = 8) -> list[dict[str, Any]]:
    db = get_db()
    hits: list[dict[str, Any]] = []
    for coll_name, fields in _COLLECTIONS:
        if coll_name not in db.list_collection_names():
            continue
        cursor = db[coll_name].find({}, {"_id": 0}).sort("updated_at", -1).limit(80)
        for doc in cursor:
            text = _doc_text(doc, fields)
            if not text:
                continue
            score = _score(text, tokens)
            if score <= 0 and tokens:
                continue
            hits.append({
                "source": f"mongodb:{coll_name}",
                "score": score,
                "text": text[:1200],
                "id": doc.get("visit_id") or doc.get("report_id") or doc.get("inspection_id")
                or doc.get("document_id") or doc.get("client_id") or doc.get("code"),
            })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def _search_docs(tokens: list[str], limit: int = 4) -> list[dict[str, Any]]:
    if not DOCS_ROOT.exists():
        return []
    hits: list[dict[str, Any]] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        if path.stat().st_size > 500_000:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        score = _score(content[:8000], tokens)
        if score <= 0:
            continue
        excerpt = content[:1500].strip()
        hits.append({
            "source": f"docs:{path.relative_to(DOCS_ROOT)}",
            "score": score,
            "text": excerpt,
            "id": str(path.name),
        })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def search_organizational_memory(query: str) -> dict[str, Any]:
    """Recupera fragmentos reales de MongoDB y /home/rlopez/data/docs/."""
    tokens = _tokenize(query)
    if not tokens:
        tokens = _tokenize("cámaras seguridad cctv nvr poe switch")

    mongo_hits = _search_mongo(tokens)
    doc_hits = _search_docs(tokens)
    all_hits = sorted(mongo_hits + doc_hits, key=lambda h: h["score"], reverse=True)

    if not all_hits:
        # Último recurso: últimos registros operativos reales (sin inventar texto)
        db = get_db()
        fallback: list[dict[str, Any]] = []
        for coll_name, fields in _COLLECTIONS[:3]:
            doc = db[coll_name].find_one({}, {"_id": 0}, sort=[("updated_at", -1)])
            if doc:
                fallback.append({
                    "source": f"mongodb:{coll_name}:latest",
                    "score": 0,
                    "text": _doc_text(doc, fields)[:1200],
                    "id": doc.get("code") or doc.get("visit_id"),
                })
        all_hits = fallback

    corpus_parts = [f"[{h['source']}] {h['text']}" for h in all_hits]
    corpus = "\n\n".join(corpus_parts)[:MAX_CHARS]
    sources = [h["source"] for h in all_hits]

    from hackathon_band.console_log import log as clog

    mongo_src = [s for s in sources if s.startswith("mongodb:")]
    doc_src = [s for s in sources if s.startswith("docs:")]
    clog(
        "info",
        "mongo",
        f"Memory search: {len(all_hits)} hits, {len(corpus)} chars",
        query=query[:80],
        tokens=tokens,
        collections=list({s.split(":")[1] for s in mongo_src if ":" in s}),
        doc_files=doc_src[:5],
    )

    return {
        "query": query,
        "tokens": tokens,
        "hits": all_hits,
        "sources": sources,
        "corpus": corpus,
        "corpus_chars": len(corpus),
    }


def format_evidence_block(hits: list[dict[str, Any]], *, lang: str = "en", limit: int = 6) -> str:
    """Bloque Markdown con evidencia cruda de MongoDB — no depende del LLM."""
    if not hits:
        return "_(no hits)_" if lang == "en" else "_(sin coincidencias)_"
    title = "## MongoDB Evidence (verified)" if lang == "en" else "## Evidencia MongoDB (verificada)"
    lines = [title, ""]
    for h in hits[:limit]:
        src = h.get("source", "?")
        doc_id = h.get("id") or "—"
        score = h.get("score", 0)
        text = (h.get("text") or "").strip().replace("\n", " ")[:320]
        lines.append(f"- **{src}** · id `{doc_id}` · score {score}")
        lines.append(f"  > {text}")
        lines.append("")
    return "\n".join(lines).strip()
