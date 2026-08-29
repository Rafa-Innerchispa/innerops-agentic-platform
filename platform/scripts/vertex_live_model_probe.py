#!/usr/bin/env python3
"""Live Vertex model probe for ops_75de50f2671d — records exact HTTP errors."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

PROJECT = "innerops-agentic-platform"
REGION = "us-central1"
MODELS = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash")


def _token() -> str:
    out = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True)
    return out.strip()


def _probe(model: str, token: str) -> dict:
    url = (
        f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/{REGION}/publishers/google/models/{model}:generateContent"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with exactly: ok"}]}],
        "generationConfig": {"maxOutputTokens": 8},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            usage = payload.get("usageMetadata") or {}
            return {
                "model": model,
                "http_status": resp.status,
                "live": True,
                "prompt_tokens": usage.get("promptTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        return {"model": model, "http_status": exc.code, "live": False, "error": detail}


def main() -> int:
    token = _token()
    results = [_probe(model, token) for model in MODELS]
    live = [r for r in results if r.get("live")]
    print(json.dumps({"project": PROJECT, "region": REGION, "results": results}, indent=2))
    if not live:
        print("BLOCKER: no live Vertex model in probe set", file=sys.stderr)
        return 2
    print(f"LIVE_MODEL={live[0]['model']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
