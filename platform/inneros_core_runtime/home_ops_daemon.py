#!/usr/bin/env python3
"""Daemon local AG-32/AG-25 — email poll + HA snapshot + digest Ollama (sin créditos cloud)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import mongo_store, ralfia_time  # noqa: E402


def _ollama_summarize(prompt: str, *, model: str | None = None) -> str:
    model = model or os.getenv("HOME_OPS_OLLAMA_MODEL", "llama3.1:8b")
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/generate"
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return str(data.get("response") or "").strip()[:2000]
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return f"(resumen local omitido: {exc})"


def run_cycle() -> dict:
    ts = ralfia_time.format_log()
    out: dict = {"ts": ts, "steps": []}

    # Fase A — email poll vía Swarm primary
    if os.getenv("HOME_OPS_EMAIL_POLL", "1") == "1":
        try:
            from raphiia_openai.notifications import email_monitor

            ep = email_monitor.trigger_email_poll()
            out["steps"].append({"email_poll": ep})
        except Exception as exc:
            out["steps"].append({"email_poll": {"ok": False, "error": str(exc)[:200]}})

    # Fase C — Home Assistant snapshot
    if os.getenv("HOME_OPS_HA_SNAPSHOT", "1") == "1":
        try:
            from raphiia_openai import homeassistant_client as ha

            snap = ha.snapshot_cache()
            out["steps"].append({"ha_snapshot": {"ok": snap.get("ok"), "lights": len(snap.get("lights") or [])}})
        except Exception as exc:
            out["steps"].append({"ha_snapshot": {"ok": False, "error": str(exc)[:200]}})

    # Fase B — digest local (Ollama) → log Mongo + archivo
    digest_path = Path(os.getenv("HOME_OPS_DIGEST_FILE", "/home/rlopez/data/ralfia/home_ops_digest.jsonl"))
    if os.getenv("HOME_OPS_DIGEST", "1") == "1":
        try:
            from raphiia_openai import homeassistant_client as ha
            from raphiia_openai.notifications import email_monitor

            recent = email_monitor.list_recent_emails(importance="alta", limit=5)
            ha_cache = ha.read_cached_snapshot()
            ctx = {
                "recent_high_email": recent.get("messages", [])[:5],
                "lights_on": [x for x in (ha_cache.get("lights") or []) if x.get("state") == "on"],
                "steps": out["steps"],
            }
            prompt = (
                "Eres el digest operativo de RalfIA para Rafael. Resume en 5 bullets en español:\n"
                f"{json.dumps(ctx, ensure_ascii=False, default=str)[:6000]}\n"
                "Solo hechos; si falta token HA o correo, dilo en una línea."
            )
            summary = _ollama_summarize(prompt)
            entry = {"ts": ts, "summary": summary, "ctx_keys": list(ctx.keys())}
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            with digest_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            out["digest"] = summary[:500]
            mongo_store.log_coordination(
                agent="AG-32_HOME_OPS",
                summary=summary[:400],
                event="home_ops_digest",
                project="ralfia-home",
            )
        except Exception as exc:
            out["digest_error"] = str(exc)[:200]

    out["ok"] = True
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    run_cycle()
