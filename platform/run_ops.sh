#!/usr/bin/env bash
# Panel único RalfIA — Control Center :2002 + redirect legacy :8800
set -euo pipefail
PORTAL_ROOT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
cd "$PORTAL_ROOT"
chmod +x run_portal.sh run_redirect_8800.sh 2>/dev/null || true
nohup ./run_redirect_8800.sh >/tmp/ralfia-redirect-8800.log 2>&1 &
exec ./run_portal.sh
