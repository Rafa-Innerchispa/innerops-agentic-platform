#!/usr/bin/env python3
"""Lanza prueba Antigravity en AMD: anuncio Alexa vía Home Assistant (sin auto-approve)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNTIME = Path(os.environ.get("INNEROS_PLATFORM_RUNTIME", "/home/rlopez/inneros/inneros_core/platform"))
sys.path.insert(0, str(RUNTIME))

from inneros_core_runtime import coordination_live as cl  # noqa: E402
from inneros_core_runtime import ops_execution_node_routing as oenr  # noqa: E402


def main() -> int:
    envf = RUNTIME / ".env.ops-notify"
    if envf.is_file():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    corr = f"AMD-ALEXA-AG-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    phrase = "Hola Ralfi, soy el servidor AMD ejecutando la tarea antigravity."
    created = cl.create_ops_task(
        assignee="antigravity",
        title="[Competencia/Externo/ANTIGRAVITY] Anuncio Alexa AMD",
        objective=phrase,
        correlation_id=corr,
        human_task_id=corr,
        from_agent="inneros_amd_alexa_launch",
        preferred_provider="antigravity",
        execution_lane="antigravity_interactive",
        do_not_auto_dispatch=True,
        payload={
            "interaction_mode": "autonomous",
            "owner_execution_node": "amd",
            "competition_announce_phrase": phrase,
            "alexa_announce_phrase": phrase,
        },
    )
    tid = str(created.get("task_id") or "")
    routing = oenr.stamp_routing_on_task(tid, provider="antigravity") if tid else {}
    report = {
        "ok": bool(created.get("ok")),
        "correlation_id": corr,
        "task_id": tid,
        "target_node": "amd",
        "phrase": phrase,
        "create": created,
        "routing": routing,
        "owner_next_step": "Aprueba en ntfy/PWA (pop-up). Ejecuta en AMD tras aprobar.",
        "pwa": os.getenv("INNEROS_OWNER_PUSH_PUBLIC_URL", "http://100.94.99.12:8244") + f"/owner-ops/?task_id={tid}",
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())