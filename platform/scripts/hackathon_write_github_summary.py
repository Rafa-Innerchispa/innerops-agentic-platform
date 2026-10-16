#!/usr/bin/env python3
"""Agrega JSON de evidencia hackathon → summary + handoff ChatGPT."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT.parent / "var" / "evidence"


def _load(name: str) -> dict | None:
    p = EV / name
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    bench = _load("hackathon_amd_inference_benchmark.json") or {}
    router = _load("hackathon_router_intel.json")
    cross = _load("coordination_cross_test_report.json")
    demo = _load("hackathon_inferencia_demo.json")

    summary = {
        "schema": "ralfia.hackathon.github_summary.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline_metrics": {},
        "artifacts": [],
        "coordination": {},
        "story_bullets_es": [],
    }

    if bench.get("ok"):
        ping = next((s for s in bench.get("suites", []) if s.get("case") == "hackathon_ping"), {})
        code = next((s for s in bench.get("suites", []) if s.get("case") == "coding_snippet"), {})
        summary["headline_metrics"] = {
            "model": bench.get("model"),
            "gpu": "AMD Radeon AI PRO R9700 (ROCm)",
            "inference_ping_p50_s": ping.get("latency_s_p50"),
            "inference_ping_tokens_per_s": ping.get("tokens_per_s_mean"),
            "coding_snippet_p50_s": code.get("latency_s_p50"),
            "coding_snippet_tokens_per_s": code.get("tokens_per_s_mean"),
        }
        summary["artifacts"].append(str(EV / "hackathon_amd_inference_benchmark.json"))

    if router:
        summary["headline_metrics"]["router_backend"] = (router.get("route") or {}).get("backend")
        summary["headline_metrics"]["router_node"] = (router.get("route") or {}).get("selected_node")
        summary["headline_metrics"]["router_latency_s"] = router.get("latency_s")
        summary["artifacts"].append(str(EV / "hackathon_router_intel.json"))

    if cross:
        summary["coordination"] = {
            "ok": cross.get("ok"),
            "externals_ok": sum(1 for x in cross.get("externals", []) if x.get("ok")),
            "carriles_ok": sum(1 for x in cross.get("carriles", []) if x.get("ok")),
        }
        summary["artifacts"].append(str(EV / "coordination_cross_test_report.json"))

    summary["story_bullets_es"] = [
        "Inferencia coding en AMD con vLLM + AWQ (Qwen3-Coder-30B) sobre ROCm — métricas p50/tokens/s en JSON.",
        "Router Intel enruta task_type=coding al nodo AMD sin depender de APIs cloud.",
        "8 carriles Dev Swarm + 6 agentes IDE (Antigravity/Codex/Cursor ×2 nodos) demostrables con nonce Alexa/Mongo.",
        "Reproducible: scripts en platform/scripts/hackathon_*.py y docs/hackathon/HACKATHON_EVIDENCE.md.",
    ]

    out = EV / "hackathon_github_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    handoff = f"""# Handoff ChatGPT — Hackathon AMD inferencia local (InnerOS/RalfIA)

Copia este bloque para mejorar README, devpost o slide.

## Métricas publicables (medidas hoy UTC)

```json
{json.dumps(summary.get("headline_metrics"), indent=2, ensure_ascii=False)}
```

## Coordinación multi-agente (sin créditos cloud IDE en smoke)

```json
{json.dumps(summary.get("coordination"), indent=2, ensure_ascii=False)}
```

## Narrativa (ES)

- **Problema:** equipos agentic dependen de APIs caras y envían código privado fuera de LAN.
- **Solución:** InnerOS enruta desde Intel; **vLLM en AMD R9700 (ROCm)** ejecuta Qwen3-Coder AWQ; Dev Swarm gobierna concurrencia.
- **Prueba:** benchmarks JSON + cross-smoke con nonce (no frases memorizadas).
- **Repo paths:** `platform/scripts/hackathon_amd_inference_benchmark.py`, `coordination_cross_smoke_v2.py`, `docs/hackathon/HACKATHON_EVIDENCE.md`.
- **Evidencia:** `var/evidence/hackathon_amd_inference_benchmark.json`, `hackathon_github_summary.json`.

## Comandos one-liner para jurado

```bash
# AMD
venv/bin/python3 platform/scripts/hackathon_amd_inference_benchmark.py
# Intel
PYTHONPATH=platform venv/bin/python3 platform/scripts/coordination_cross_smoke_v2.py
```

## Qué puede mejorar ChatGPT

1. Redactar README hero + tabla de métricas para GitHub.
2. Slide 3 bullets + gráfico latencia p50 (usar headline_metrics).
3. Comparativa coste evitado (tokens × precio GPT-4o mini) — pedir al agente nueva corrida N=20 si hace falta.
4. No inventar métricas: solo usar JSON citados arriba.

Generado: {summary.get("generated_at")}
"""
    (EV / "CHATGPT_HANDOFF_HACKATHON.md").write_text(handoff, encoding="utf-8")
    print(json.dumps({"ok": True, "summary": str(out), "handoff": str(EV / "CHATGPT_HANDOFF_HACKATHON.md")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
