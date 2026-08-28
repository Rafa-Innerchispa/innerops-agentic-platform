"""Lectura local de archivos: texto, PDF e imágenes (Ollama llava)."""

import base64
import json
from pathlib import Path

import requests

from config import OLLAMA_BASE_URL, OLLAMA_VISION_MODEL


def read_file(path: str | Path, question: str = "") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    ext = path.suffix.lower()
    if ext in {".txt", ".md", ".csv", ".json", ".log"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"kind": "text", "text": text, "file": str(path)}
    if ext == ".pdf":
        return {"kind": "pdf", **read_pdf(path)}
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return {"kind": "image", **describe_image(path, question)}
    raw = path.read_bytes()
    return {
        "kind": "binary",
        "text": f"Archivo binario ({ext}), {len(raw)} bytes. No se pudo extraer texto.",
        "file": str(path),
    }


def read_pdf(path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("Instala pypdf: pip install pypdf") from e
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages[:30], 1):
        pages.append(page.extract_text() or "")
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    return {"text": text or "(PDF sin texto extraíble)", "pages": len(reader.pages), "file": str(path)}


def describe_image(path: Path, question: str = "") -> dict:
    prompt = question or (
        "Describe esta imagen de inspección técnica: equipos, cables, cámaras, "
        "daños visibles y recomendaciones."
    )
    img_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    r = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        json={
            "model": OLLAMA_VISION_MODEL,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        },
        timeout=300,
    )
    r.raise_for_status()
    body = r.json()
    return {
        "text": (body.get("response") or "").strip(),
        "model": OLLAMA_VISION_MODEL,
        "file": str(path),
    }
