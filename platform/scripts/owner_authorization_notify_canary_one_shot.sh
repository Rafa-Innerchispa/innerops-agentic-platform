#!/usr/bin/env bash
# One-shot: pull P0 notify fix, prep Telegram/HA, create owner-auth canary (no auto-claim).
# Non-interactive. Rafael only confirms on Telegram or Alexa afterward.
set -euo pipefail

export GIT_TERMINAL_PROMPT=0
export DEBIAN_FRONTEND=noninteractive
export NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE="${NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE:-1}"
export NOTIFY_OPS_AUTH_HA="${NOTIFY_OPS_AUTH_HA:-1}"

REPO="${INNEROS_REPO:-$HOME/innerops-agentic-platform}"
cd "$REPO"

git fetch -q origin main
git checkout -q main 2>/dev/null || git checkout -q -B main origin/main
if ! git merge -q --no-edit origin/main 2>/dev/null; then
  if ! git pull -q --no-rebase --no-edit origin main 2>/dev/null; then
    echo '{"ok":false,"error":"git_merge_failed","hint":"resolver conflictos en main o: git stash -u && git checkout main && git reset --hard origin/main (solo si aceptas descartar commits locales en main)","paths":"git status"}'
    git status -sb 2>/dev/null || true
    exit 3
  fi
fi

if ! grep -q '_owner_auth_telegram_direct_enabled' \
  platform/inneros_core_runtime/notifications/ops_task_alerts.py 2>/dev/null; then
  echo '{"ok":false,"error":"pr_283_notify_fix_missing_on_main","hint":"git pull origin main after PR #283 merge"}'
  exit 2
fi

systemctl --user enable --now inneros-telegram-ops-poll.service 2>/dev/null || true
for u in inneros-coordination-cycle inneros-interactive-provider-autopilot; do
  systemctl --user try-restart "${u}.service" 2>/dev/null || true
  systemctl --user try-restart "${u}.timer" 2>/dev/null || true
done

OUT_JSON="${REPO}/var/owner_notify_canary_latest.json"
mkdir -p "${REPO}/var"

python3 <<'PY'
from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd() / "platform"
if not (ROOT / "inneros_core_runtime").exists():
    ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import coordination_live as cl
from inneros_core_runtime import execution_binding as eb
from inneros_core_runtime.coordination_live import OPS_TASKS_COL
from inneros_core_runtime.notifications import ops_task_alerts as alerts
from inneros_core_runtime.notifications import telegram_client as tg
from raphiia_openai import mongo_store

repo_root = Path(os.environ.get("INNEROS_REPO", Path.home() / "innerops-agentic-platform"))
out_path = repo_root / "var" / "owner_notify_canary_latest.json"

cid = f"owner-notify-canary-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
created = cl.create_ops_task(
    assignee="cursor",
    title="[CANARIO] autorización Telegram/Alexa (one-shot)",
    objective=(
        "Prueba humana únicamente: Rafael confirma autorización por Telegram o Alexa. "
        "No modificar archivos ni hacer push."
    ),
    preferred_provider="cursor",
    task_class="verification",
    execution_lane="cursor_interactive",
    correlation_id=cid,
    do_not_auto_dispatch=True,
    from_agent="owner_notify_canary_one_shot",
    repo="Rafa-Innerchispa/innerops-agentic-platform",
    idempotency_key=cid,
)

report: dict = {
    "ok": bool(created.get("ok")),
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "host": socket.gethostname(),
    "correlation_id": cid,
    "create": created,
    "env": {
        "NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE": os.getenv("NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE"),
        "NOTIFY_OPS_AUTH_HA": os.getenv("NOTIFY_OPS_AUTH_HA"),
    },
    "telegram_configured": bool(tg.telegram_enabled() and tg._bot_token()),
    "owner_action_required": (
        "Rafael: pulsa Confirmar en Telegram O aprueba por Alexa (solo una vía). "
        "No ejecutar claim desde terminal."
    ),
}

tid = str(created.get("task_id") or (created.get("task") or {}).get("task_id") or "")
report["task_id"] = tid

if tid:
    task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    binding = eb.resolve_execution_binding(task)
    notify = alerts.notify_ops_owner_authorization_request(
        task, binding=binding, source_agent="owner_notify_canary_one_shot_resend", force=True
    )
    report["notify_resend"] = notify
    task2 = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0}) or {}
    report["task_status"] = str(task2.get("status") or "")
    report["owner_authorized_at"] = task2.get("owner_authorized_at")

out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
print(json.dumps(report, indent=2, default=str))
if not report.get("ok"):
    raise SystemExit(1)
PY

echo ""
echo "Handoff written: ${OUT_JSON}"
echo "Doc: ${REPO}/docs/CURSOR_OWNER_NOTIFY_CANARY_HANDOFF_20261120.md"