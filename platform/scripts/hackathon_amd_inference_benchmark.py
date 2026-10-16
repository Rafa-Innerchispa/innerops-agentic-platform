#!/usr/bin/env python3
"""Benchmark reproducible vLLM local (AMD/ROCm) para hackathon — salida JSON medible."""
from __future__ import annotations

import json
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8000/v1/chat/completions"
DEFAULT_MODEL = "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"
OUT = ROOT.parent / "var" / "evidence" / "hackathon_amd_inference_benchmark.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rocm_info() -> dict:
    info: dict = {"hostname": socket.gethostname()}
    try:
        proc = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        info["rocm_smi_excerpt"] = (proc.stdout or proc.stderr or "")[:2000]
    except Exception as exc:
        info["rocm_error"] = str(exc)[:200]
    return info


def _one_completion(
    *,
    url: str,
    model: str,
    user: str,
    max_tokens: int,
) -> dict:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
    ).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"http_{e.code}", "latency_s": time.perf_counter() - t0}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "latency_s": time.perf_counter() - t0}
    dt = time.perf_counter() - t0
    usage = data.get("usage") or {}
    comp_tok = int(usage.get("completion_tokens") or 0)
    text = ""
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        pass
    return {
        "ok": True,
        "latency_s": round(dt, 4),
        "completion_tokens": comp_tok,
        "prompt_tokens": usage.get("prompt_tokens"),
        "tokens_per_s": round(comp_tok / max(dt, 1e-6), 2),
        "text_preview": text[:120],
    }


def _bench_suite(url: str, model: str) -> list[dict]:
    cases = [
        {"name": "hackathon_ping", "prompt": "Responde solo: INFERENCIA_OK", "max_tokens": 16, "runs": 5},
        {
            "name": "coding_snippet",
            "prompt": "Escribe una función Python que devuelva la suma de una lista. Solo código, sin markdown.",
            "max_tokens": 128,
            "runs": 3,
        },
        {
            "name": "short_reasoning",
            "prompt": "En una frase: ventaja de inferencia local vs cloud para datos privados.",
            "max_tokens": 64,
            "runs": 3,
        },
    ]
    results: list[dict] = []
    for case in cases:
        latencies: list[float] = []
        tps: list[float] = []
        samples: list[dict] = []
        for _ in range(case["runs"]):
            r = _one_completion(url=url, model=model, user=case["prompt"], max_tokens=case["max_tokens"])
            samples.append(r)
            if r.get("ok"):
                latencies.append(float(r["latency_s"]))
                tps.append(float(r["tokens_per_s"]))
            time.sleep(0.3)
        entry = {
            "case": case["name"],
            "runs": case["runs"],
            "ok_runs": sum(1 for s in samples if s.get("ok")),
            "latency_s_p50": round(statistics.median(latencies), 4) if latencies else None,
            "latency_s_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 4) if latencies else None,
            "tokens_per_s_mean": round(statistics.mean(tps), 2) if tps else None,
            "samples": samples,
        }
        results.append(entry)
    return results


def main() -> int:
    url = __import__("os").environ.get("HACKATHON_VLLM_URL", DEFAULT_URL)
    model = __import__("os").environ.get("HACKATHON_VLLM_MODEL", DEFAULT_MODEL)
    report = {
        "schema": "ralfia.hackathon.inference_benchmark.v1",
        "generated_at": _utc(),
        "host": socket.gethostname(),
        "endpoint": url,
        "model": model,
        "stack": {
            "inference_server": "vLLM",
            "hardware": "AMD Radeon AI PRO R9700",
            "stack_note": "ROCm + vLLM AWQ Qwen3-Coder-30B en nodo AMD (.5); router Intel (.4) enruta coding local",
        },
        "rocm": _rocm_info(),
        "suites": _bench_suite(url, model),
    }
    ok_all = all(s.get("ok_runs", 0) == s.get("runs") for s in report["suites"])
    report["ok"] = ok_all
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": ok_all, "path": str(OUT), "suites": [{k: s.get(k) for k in ("case", "ok_runs", "latency_s_p50", "tokens_per_s_mean")} for s in report["suites"]]}, indent=2))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
