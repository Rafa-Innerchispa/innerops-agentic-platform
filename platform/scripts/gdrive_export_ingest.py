#!/usr/bin/env python3
"""Ingesta Google Drive + Takeout local → Qdrant inneros_kb (source=gdrive)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai.settings import OLLAMA_URL, QDRANT_COLLECTION, QDRANT_URL  # noqa: E402

DEFAULT_ROOTS = [
    "/home/rlopez/data/google_drive",
    "/home/rlopez/data/google_takeout/extracted",
]
STATE_PATH = Path("/home/rlopez/data/google_drive/.ingest_state.json")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
SOURCE_TAG = "gdrive"
SKIP_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".mp3", ".wav", ".flac", ".jpg", ".jpeg",
    ".png", ".gif", ".webp", ".zip", ".rar", ".7z", ".iso", ".pst", ".mbox", ".tar",
    ".gz", ".bz2", ".exe", ".dll", ".so", ".bin", ".dat", ".heic", ".cr2",
}
SUPPORTED = {".txt", ".csv", ".md", ".log", ".rtf", ".xlsx", ".xlsm", ".xls", ".ods",
             ".docx", ".docm", ".odt", ".pdf", ".htm", ".html", ".json", ".eml"}
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS_PER_DOC", "40"))
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "16"))


def _log(msg: str) -> None:
    print(msg, flush=True)


def _http(method: str, url: str, *, json_body: dict | None = None, timeout: float = 120.0) -> dict:
    with httpx.Client(timeout=timeout) as client:
        r = client.request(method, url, json=json_body)
        data = r.json() if r.content else {}
        if r.is_success:
            return data
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {data}")


def embed_batch(texts: list[str]) -> list[list[float]]:
    resp = _http("POST", f"{OLLAMA_URL.rstrip('/')}/api/embed",
                 json_body={"model": EMBED_MODEL, "input": texts}, timeout=300.0)
    embs = resp.get("embeddings")
    if not embs:
        raise RuntimeError("embedding_failed")
    return embs


def chunk_text(text: str, size: int = 1500, overlap: int = 200) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i:i + size])
        i += size - overlap
    return [c.strip() for c in chunks if c.strip()]


def brand_of(path: str) -> str:
    t = path.lower()
    for k, v in [("pcdoctor", "PC Doctor"), ("innerchispa", "InnerChispa"), ("innerspark", "InnerSpark"),
                 ("iskcon", "ISKCON"), ("domotika", "Domotika"), ("ralphi", "RalfIA")]:
        if k in t:
            return v
    return "General"


def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".csv", ".md", ".log", ".rtf", ".htm", ".html", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if ext == ".eml":
        msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        parts = [f"Subject: {msg.get('subject', '')}", f"From: {msg.get('from', '')}",
                 f"Date: {msg.get('date', '')}"]
        body = msg.get_body(preferencelist=("plain", "html"))
        if body:
            parts.append(body.get_content())
        return "\n".join(parts)
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:80])
    if ext in {".docx", ".docm"}:
        from docx import Document
        return "\n".join(p.text for p in Document(str(path)).paragraphs if p.text.strip())
    if ext in {".xlsx", ".xlsm", ".xls", ".ods"}:
        import pandas as pd
        engine = "openpyxl" if ext != ".xls" else "xlrd"
        parts = []
        for sheet, df in pd.read_excel(str(path), sheet_name=None, header=None, dtype=str, engine=engine).items():
            df = df.fillna("")
            for _, row in df.head(200).iterrows():
                cells = [str(c).strip() for c in row if str(c).strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    return ""


def iter_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.name.startswith("."):
                continue
            if "_staging" in p.parts or "node_modules" in p.parts:
                continue
            ext = p.suffix.lower()
            if ext in SKIP_EXT:
                continue
            if ext not in SUPPORTED:
                continue
            out.append(p)
    out.sort()
    return out


def load_state() -> dict:
    if STATE_PATH.is_file():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"done_files": [], "total_chunks": 0}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ingest(*, roots: list[str], resume: bool = False, limit: int | None = None) -> dict:
    root_paths = [Path(r) for r in roots]
    files = iter_files(root_paths)
    if limit:
        files = files[:limit]
    state = load_state() if resume else {"done_files": [], "total_chunks": 0, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    done = set(state.get("done_files") or [])
    _log(f"GDrive ingest: {len(files)} archivos indexables")

    dim = len(embed_batch(["probe"])[0])
    base = QDRANT_URL.rstrip("/")
    try:
        _http("GET", f"{base}/collections/{QDRANT_COLLECTION}")
    except Exception:
        _http("PUT", f"{base}/collections/{QDRANT_COLLECTION}",
              json_body={"vectors": {"size": dim, "distance": "Cosine"}})

    pending, total, errors = [], int(state.get("total_chunks") or 0), 0

    def flush() -> None:
        nonlocal pending, total
        if not pending:
            return
        vecs = embed_batch([p["text"] for p in pending])
        points = [{"id": p["id"], "vector": v, "payload": p["payload"]} for p, v in zip(pending, vecs)]
        _http("PUT", f"{base}/collections/{QDRANT_COLLECTION}/points?wait=true",
              json_body={"points": points}, timeout=180.0)
        total += len(points)
        pending = []

    for idx, path in enumerate(files, 1):
        rel = str(path)
        if resume and rel in done:
            continue
        try:
            text = read_file(path).strip()
            if len(text) < 30:
                done.add(rel)
                continue
            title = path.stem[:200]
            brand = brand_of(rel)
            for ci, ch in enumerate(chunk_text(text)[:MAX_CHUNKS]):
                pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gdrive:{rel}:{ci}"))
                pending.append({"id": pid, "text": ch, "payload": {
                    "source": SOURCE_TAG, "title": title, "brand": brand,
                    "file_path": rel, "chunk": ci, "text": ch,
                }})
                if len(pending) >= EMBED_BATCH:
                    flush()
            done.add(rel)
        except Exception as exc:
            errors += 1
            _log(f"  [warn] {path.name}: {exc}")
        if idx % 50 == 0:
            flush()
            state["done_files"] = sorted(done)
            state["total_chunks"] = total
            save_state(state)
            _log(f"  progreso: {idx}/{len(files)}, chunks={total}, err={errors}")
    flush()
    state["done_files"] = sorted(done)
    state["total_chunks"] = total
    state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)
    return {"ok": True, "files": len(files), "chunks": total, "errors": errors}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    args = ap.parse_args()
    print(json.dumps(ingest(roots=args.roots, resume=args.resume, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
