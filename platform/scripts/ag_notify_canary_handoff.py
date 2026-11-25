#!/usr/bin/env python3
"""Antigravity owner-auth notify canary (runtime PYTHONPATH; avoid stdlib platform shadow)."""
from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("INNEROS_REPO", Path.home() / "innerops-agentic-platform")).resolve()
RUNTIME = Path(
    os.environ.get(
        "INNEROS_PLATFORM_RUNTIME",
        "/home/rlopez/inneros/inneros_core/platform",
    )
).resolve()

# Cwd repo root or PYTHONPATH=.../platform shadows stdlib `platform` via ./platform/
sys.path = [p for p in sys.path if p and Path(p).resolve() not in {REPO, REPO / "platform"}]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from inneros_core_runtime import coordination_live as cl  # noqa: E402
from inneros_core_runtime import execution_binding as eb  # noqa: E402
from inneros_core_runtime.coordination_live import OPS_TASKS_COL  # noqa: E402
from inneros_core_runtime.notifications import ops_task_alerts as alerts  # noqa: E402
from inneros_core_runtime.notifications import telegram_client as tg  # noqa: E402
from raphiia_openai import mongo_store  # noqa: E402


def main() -> int:
    sha_file = RUNTIME / "var" / "deployed_main_sha.txt"
    cid = "ag-notify-canary-" + uuid.uuid4().hex[:8]
    created = cl.create_ops_task(
        assignee="antigravity",
        title="[CANARIO] AG notify Telegram+Alexa",
        objective="Solo prueba notify. No ejecutar.",
        preferred_provider="antigravity",
        execution_lane="antigravity_interactive",
        correlation_id=cid,
        do_not_auto_dispatch=True,
        from_agent="local_handoff_ag_canary",
    )
    report: dict = {
        "phase": "C_ag_notify_canary",
        "ok": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "runtime_sha": sha_file.read_text().strip() if sha_file.is_file() else None,
        "correlation_id": cid,
        "create": created,
        "env": {
            "NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE": os.getenv("NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE"),
            "NOTIFY_OPS_AUTH_HA": os.getenv("NOTIFY_OPS_AUTH_HA"),
            "NOTIFY_OPS_TELEGRAM": os.getenv("NOTIFY_OPS_TELEGRAM"),
        },
        "telegram_configured": bool(tg.telegram_enabled() and tg._bot_token() and tg.configured()),
        "owner_action_required": "Rafael: Confirmar o Cancelar en Telegram (una vía).",
    }
    tid = created.get("task_id")
    if created.get("ok") and tid:
        task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
        notify = alerts.notify_ops_owner_authorization_request(
            task, binding=eb.resolve_execution_binding(task), force=True
        )
        report["task_id"] = tid
        report["notify"] = notify
        tg_out = notify.get("telegram") or {}
        report["ok"] = bool(notify.get("ok")) and (
            bool(tg_out.get("ok")) or "telegram" in str(notify.get("delivery_mode") or "")
        )
    out_dir = REPO / "var"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"ag_notify_canary_{stamp}.json"
    latest = out_dir / "ag_notify_canary_latest.json"
    text = json.dumps(report, indent=2, default=str)
    out_path.write_text(text + "\n", encoding="utf-8")
    latest.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())