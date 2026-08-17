#!/usr/bin/env python3
"""Diagnóstico Google Gemini/Imagen — T-035 Antigravity.

Ejecutar EN EL SERVIDOR (192.168.1.4). NO imprime la clave completa.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/home/rlopez/projects/raphiia-openai")
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

KEY = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
IMAGE_MODEL = os.getenv("IMAGE_GEN_MODEL", "imagen-3.0-generate-002")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")


def _mask(k: str) -> str:
    if not k:
        return "(vacía)"
    if len(k) <= 8:
        return k[:2] + "…"
    return f"{k[:4]}…{k[-4:]} (len={len(k)})"


def _post(url: str, body: dict, *, use_header: bool = True) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if use_header and KEY:
        headers["x-goog-api-key"] = KEY
    req_url = url if use_header else f"{url}?key={KEY}"
    req = urllib.request.Request(req_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:500]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]


def _sdk_test() -> tuple[str, str]:
    try:
        from google import genai
    except ImportError:
        return "SKIP", "google-genai no instalado — pip install google-genai"
    try:
        client = genai.Client(api_key=KEY)
        r = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents="di ok")
        text = (getattr(r, "text", None) or "")[:80]
        return "OK", text or str(r)[:120]
    except Exception as exc:
        return "FAIL", f"{type(exc).__name__}: {exc}"[:300]


def main() -> None:
    print("=== RalfIA Google API Diagnostic T-035 ===")
    print(f"project: {ROOT}")
    print(f"env file exists: {(ROOT / '.env').is_file()}")
    print(f"GOOGLE_API_KEY: {_mask(KEY)}")
    print(f"IMAGE_GEN_MODEL: {IMAGE_MODEL}")
    print(f"GEMINI_IMAGE_MODEL: {GEMINI_IMAGE_MODEL}")
    print(f"GEMINI_TEXT_MODEL: {GEMINI_TEXT_MODEL}")
    print()

    if not KEY:
        print("ERROR: GOOGLE_API_KEY / GEMINI_API_KEY no configurada en .env")
        sys.exit(1)

    prefix = KEY[:3]
    print(f"key_prefix: {prefix!r} ({'Auth key AQ.' if prefix == 'AQ.' else 'Legacy/other'})")
    print()

    tests = [
        (
            "gemini_text_header",
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TEXT_MODEL}:generateContent",
            {"contents": [{"parts": [{"text": "responde solo: ok"}]}]},
            True,
        ),
        (
            "gemini_text_query",
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TEXT_MODEL}:generateContent",
            {"contents": [{"parts": [{"text": "responde solo: ok"}]}]},
            False,
        ),
        (
            "imagen_predict",
            f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_MODEL}:predict",
            {
                "instances": [{"prompt": "simple blue square icon"}],
                "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
            },
            True,
        ),
        (
            "gemini_image_gen",
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent",
            {
                "contents": [{"parts": [{"text": "blue square icon"}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
            True,
        ),
    ]

    for name, url, body, header in tests:
        code, body_text = _post(url, body, use_header=header)
        status = "OK" if 200 <= code < 300 else "FAIL"
        print(f"[{status}] {name} HTTP {code}")
        print(f"  auth: {'x-goog-api-key' if header else '?key='}")
        print(f"  body: {body_text[:280]}")
        print()

    sdk_status, sdk_msg = _sdk_test()
    print(f"[{sdk_status}] google-genai SDK ({GEMINI_TEXT_MODEL})")
    print(f"  {sdk_msg}")
    print()
    print("=== Checklist AI Studio (Rafael) ===")
    print("1. https://aistudio.google.com/apikey")
    print("2. Key type: Auth (AQ.) — restrict to Gemini API only")
    print("3. Si Unrestricted o Blocked → nueva clave o restricción")
    print("4. Billing habilitado si la cuenta lo exige")
    print("5. Tras fix: systemctl --user restart ralfia-editorial-worker && reiniciar :8101")
    print()
    print("Doc: antigravity/specs/T-035_GOOGLE_API_IMAGEN_HANDOFF.md")


if __name__ == "__main__":
    main()
