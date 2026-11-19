#!/usr/bin/env bash
# Pull coordination P0 onto Intel runtime and reload user timers (no destructive deploy).
set -euo pipefail

REPO="${INNEROS_REPO:-$HOME/innerops-agentic-platform}"
cd "$REPO"
git fetch origin main
git pull origin main

export NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE="${NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE:-1}"
export NOTIFY_OPS_AUTH_HA="${NOTIFY_OPS_AUTH_HA:-1}"

for u in inneros-coordination-cycle.timer inneros-interactive-provider-autopilot.timer; do
  systemctl --user try-restart "${u%.timer}.service" 2>/dev/null || true
done

python3 "$REPO/platform/scripts/verify_cursor_auto_claim_pipeline.py" || true
echo "P0 notify flags: TELEGRAM_DIRECT_ON_CREATE=$NOTIFY_OPS_TELEGRAM_DIRECT_ON_CREATE NOTIFY_OPS_AUTH_HA=$NOTIFY_OPS_AUTH_HA"
echo "Restart MCP/coordination services if your install uses separate units for :8102."