#!/usr/bin/env python3
"""Canario limpio: autorización + (opcional) demo del ciclo completo de pushes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNTIME = Path(os.environ.get("INNEROS_PLATFORM_RUNTIME", "/home/rlopez/inneros/inneros_core/platform"))
REPO = Path(os.environ.get("INNEROS_REPO", Path.home() / "innerops-agentic-platform"))
sys.path = [p for p in sys.path if p and Path(p).resolve() not in {REPO, REPO / "platform"}]
sys.path.insert(0, str(RUNTIME))

from inneros_core_runtime import coordination_live as cl  # noqa: E402
from inneros_core_runtime import execution_binding as eb  # noqa: E402
from inneros_core_runtime.coordination_live import OPS_TASKS_COL  # noqa: E402
from inneros_core_runtime.notifications import inneros_owner_lifecycle as life  # noqa: E402
from inneros_core_runtime.notifications import ops_task_alerts as alerts  # noqa: E402
from raphiia_openai import mongo_store  # noqa: E402


def _env():
    for name in ("INNEROS_PLATFORM_RUNTIME",):
        envf = RUNTIME / ".env.ops-notify"
        if envf.is_file():
            for line in envf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="cursor", choices=["cursor", "codex", "antigravity"])
    ap.add_argument("--reset", action="store_true", help="Limpia inbox/dedupe antes")
    ap.add_argument("--demo-cycle", action="store_true", help="Tras crear, simula 5 pushes (sin gastar IDE)")
    ap.add_argument("--apply-reset", action="store_true")
    args = ap.parse_args()
    if args.reset:
        import subprocess

        cmd = [sys.executable, str(Path(__file__).resolve().parent / "owner_push_reset_clean.py"), "--apply"]
        if args.apply_reset:
            cmd.append("--fence-canaries")
        subprocess.check_call(cmd)

    cid = f"notify-e2e-{uuid.uuid4().hex[:8]}"
    prov = args.provider.lower()
    created = cl.create_ops_task(
        assignee=prov,
        title=f"[CANARIO E2E] Push completo · {prov.upper()}",
        objective="Prueba notificaciones: autorizar → iniciar → ejecutar → terminar. Sin trabajo real.",
        preferred_provider=prov,
        execution_lane="ide_inbox",
        correlation_id=cid,
        do_not_auto_dispatch=True,
        from_agent="inneros_notify_e2e",
    )
    report = {"create": created, "correlation_id": cid, "provider": prov, "generated_at": datetime.now(timezone.utc).isoformat()}
    tid = created.get("task_id")
    if not (created.get("ok") and tid):
        print(json.dumps(report, indent=2))
        return 1
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    os.environ["NOTIFY_OPS_PRIMARY"] = "inneros_push"
    os.environ["NOTIFY_OPS_AUTH_HA"] = "0"
    notify = alerts.notify_ops_owner_authorization_request(task, binding=eb.resolve_execution_binding(task), force=True)
    report["task_id"] = tid
    report["human_task_id"] = task.get("human_task_id")
    report["notify_auth"] = {"ok": notify.get("ok"), "delivery_mode": notify.get("delivery_mode"), "inneros": notify.get("inneros_push")}
    if args.demo_cycle:
        task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or task
        steps = [
            ("authorized", "Owner autorizó (demo)."),
            ("claimed", "Agente tomó la tarea (demo)."),
            ("in_progress", "Ejecutando paso de prueba (demo)."),
            ("verification", "Verificando resultado (demo)."),
            ("completed", "Canario E2E terminado OK (demo)."),
        ]
        report["demo_cycle"] = []
        for ev, detail in steps:
            time.sleep(2)
            out = life.notify_lifecycle(task, event=ev, detail=detail, force=True)
            report["demo_cycle"].append({"event": ev, "out": out})
    out_path = REPO / "var" / "inneros_notify_e2e_latest.json"
    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"\nAutoriza en ntfy/InnerOS → Pendientes. ID: {task.get('human_task_id')}")
    return 0 if report["notify_auth"].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())