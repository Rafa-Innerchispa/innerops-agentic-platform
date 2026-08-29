#!/usr/bin/env bash
set -euo pipefail
CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
VENV="${ROCM_CANARY_VENV:-$CANARY_DIR/venv-rocm-canary}"
ROCM10_INSTALL="${ROCM10_INSTALL:-$CANARY_DIR/rocm-10-install/rocm/core-10.0}"
PORT="${CANARY_HEALTH_PORT:-8001}"
PIDFILE="$CANARY_DIR/canary_health.pid"
LOG="$CANARY_DIR/canary_health.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -x "$VENV/bin/python" ]] || { echo "FAIL: venv $VENV" >&2; exit 1; }
if ss -ltnp 2>/dev/null | grep -q ":${PORT} "; then
  echo "INFO: :${PORT} already up"; curl -sf "http://127.0.0.1:${PORT}/health" | head -c 300; exit 0; fi
export ROCM_CANARY_DIR CANARY_DIR ROCM10_INSTALL CANARY_HEALTH_PORT="$PORT" ROCM_PATH="$ROCM10_INSTALL"
export PATH="$ROCM10_INSTALL/bin:$PATH"
export LD_LIBRARY_PATH="$ROCM10_INSTALL/lib:$ROCM10_INSTALL/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
nohup "$VENV/bin/python" "$SCRIPT_DIR/canary_health_server.py" >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"; sleep 1
curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null && echo "PASS: health :${PORT} pid $(cat "$PIDFILE")" || { tail -15 "$LOG" >&2; exit 1; }
