#!/usr/bin/env python3
"""Canario E2E: push con correlación clara + nodo Intel/AMD + Antigravity bounded."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNTIME = Path(os.environ.get("INNEROS_PLATFORM_RUNTIME", "/home/rlopez/inneros/inneros_core/platform"))
sys.path.insert(0, str(RUNTIME))

from inneros_core_runtime import coordination_live as cl  # noqa: E402
from inneros_core_runtime import interactive_ops_orchestrator as ioo  # noqa: E402
from inneros_core_runtime import ops_execution_node_routing as oenr  # noqa: E402
from inneros_core_runtime.coordination_live import OPS_TASKS_COL  # noqa: E402
from inneros_core_runtime.notifications import ops_task_alerts as alerts  # noqa: E402
from inneros_core_runtime import execution_binding as eb  # noqa: E402
from raphiia_openai import mongo_store  # noqa: E402


def _load_env() -> None:
    envf = RUNTIME / ".env.ops-notify"
    if envf.is_file():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("INNEROS_ANTIGRAVITY_SUBSCRIPTION_MODE", "1")


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default="intel", choices=["intel", "amd", "auto"])
    ap.add_argument(
        "--approve",
        action="store_true",
        help="Autoriza+claim en este servidor (NO usar en pruebas owner real; create ya mandó push)",
    )
    ap.add_argument(
        "--extra-auth-push",
        action="store_true",
        help="Solo debug: segundo push de autorización (en uso normal create ya notifica una vez)",
    )
    ap.add_argument("--provider", default="antigravity", choices=["antigravity", "codex", "cursor"])
    args = ap.parse_args()
    corr = f"INTEL-AMD-E2E-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    prov = args.provider.lower()
    marker = "docs/ANTIGRAVITY_CANARY.md" if prov == "antigravity" else "docs/CODEX_CANARY.md"
    objective = (
        f"[{prov}_canary] Referencia {corr}. Solo {marker} en worktree. "
        "Prueba mensajes owner con misma correlación en todos los pasos."
    )
    created = cl.create_ops_task(
        assignee=prov,
        title=f"[E2E nodo {args.node.upper()}] Push correlacionado · {prov}",
        objective=objective,
        correlation_id=corr,
        human_task_id=corr,
        repo="Rafa-Innerchispa/innerops-agentic-platform",
        preferred_provider=prov,
        execution_lane=f"{prov}_interactive",
        do_not_auto_dispatch=True,
        from_agent="inneros_node_e2e",
        payload={
            "interaction_mode": "autonomous",
            "owner_execution_node": args.node,
            "provider_canary": prov if prov == "antigravity" else None,
            "execution_mode": "SYNTHETIC_CANARY" if prov == "antigravity" else None,
            "synthetic_canary": prov == "antigravity",
            "synthetic_canary_issuer": "inneros_ops_provider_bounded_canary",
            "synthetic_canary_auth_token": os.getenv("INNEROS_OPS_SYNTHETIC_CANARY_TOKEN", "").strip() or None,
        },
    )
    report = {"correlation_id": corr, "node": args.node, "create": created, "generated_at": datetime.now(timezone.utc).isoformat()}
    tid = str(created.get("task_id") or "")
    if not (created.get("ok") and tid):
        print(json.dumps(report, indent=2))
        return 1
    oenr.stamp_routing_on_task(tid, provider=prov)
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    os.environ["NOTIFY_OPS_PRIMARY"] = "inneros_push"
    os.environ["NOTIFY_OPS_AUTH_HA"] = "0"
    os.environ["NOTIFY_OPS_INNEROS_LIFECYCLE"] = "1"
    if prov == "antigravity":
        os.environ["INNEROS_OPS_SYNTHETIC_CANARY_AUTH"] = "1"
    notify = {"ok": True, "skipped": "create_ops_task_already_sent_owner_auth"}
    if args.extra_auth_push:
        notify = alerts.notify_ops_owner_authorization_request(
            task, binding=eb.resolve_execution_binding(task), force=True
        )
    report["task_id"] = tid
    report["routing"] = oenr.stamp_routing_on_task(tid, provider=prov)
    report["notify_auth"] = notify
    if args.approve:
        if prov == "antigravity":
            os.environ["INNEROS_OPS_SYNTHETIC_CANARY_AUTH"] = "1"
        out = ioo.owner_order_execute(prov, task_id=tid, owner_actor="RAFAEL", channel="inneros_node_e2e")
        report["owner_execute"] = out
        task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or task
        report["status_after"] = task.get("status")
        report["claim_host"] = task.get("claim_host")
        report["target_node"] = task.get("target_execution_node")
    print(json.dumps(report, indent=2, default=str))
    print(f"\nEn el móvil busca la línea de seguimiento: {corr}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())