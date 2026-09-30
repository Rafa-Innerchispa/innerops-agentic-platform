#!/usr/bin/env bash
set -euo pipefail

# Foreground-only MCP smoke canary. It binds localhost:18102 and writes only
# to an isolated Mongo database and filesystem root. It does not restart or
# replace the production MCP on port 8102.

if [[ "${INNEROS_P0_LIVE_CANARY_ACK:-}" != "I_UNDERSTAND_ISOLATED_CANARY" ]]; then
  echo "REFUSED: set INNEROS_P0_LIVE_CANARY_ACK=I_UNDERSTAND_ISOLATED_CANARY" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "repair/coordination-recovery-20260929" ]]; then
  echo "REFUSED: expected repair branch, got '$BRANCH'" >&2
  exit 3
fi
case "$ROOT" in
  /home/rlopez/inneros/inneros_core|/home/rlopez/inneros/inneros_core/*)
    echo "REFUSED: canary cannot run from the production checkout" >&2
    exit 4
    ;;
esac

DIRTY="$(git status --porcelain | grep -vE '^\?\? (\.venv-p0-canary|\.canary)/' || true)"
if [[ -n "$DIRTY" ]]; then
  echo "REFUSED: canary checkout must be clean" >&2
  printf '%s\n' "$DIRTY" >&2
  exit 5
fi

python3 - <<'PY'
import socket
for port, expected_open in ((8102, True), (18102, False)):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        is_open = sock.connect_ex(("127.0.0.1", port)) == 0
    if is_open != expected_open:
        state = "listening" if is_open else "closed"
        raise SystemExit(f"REFUSED: port {port} is {state}; expected_open={expected_open}")
PY

PRODUCTION_PYTHON="/home/rlopez/inneros/inneros_core/platform/venv/bin/python"
PYTHON_BIN="${INNEROS_CANARY_PYTHON:-$PRODUCTION_PYTHON}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "REFUSED: Python runtime not executable: $PYTHON_BIN" >&2
  exit 6
fi

CANARY_ROOT="$ROOT/.canary"
mkdir -p "$CANARY_ROOT/coordination"

export PYTHONPATH="$ROOT/platform"
export MCP_HOST="127.0.0.1"
export MCP_PORT="18102"
export MCP_PUBLIC_URL="http://127.0.0.1:18102"
export MCP_LAN_URL="http://127.0.0.1:18102"
export MCP_TOOL_PROFILE="contifico_analytics"
export MONGO_URI="mongodb://127.0.0.1:27017/"
export MONGO_URI_PRIMARY="mongodb://127.0.0.1:27017/"
export MONGO_URI_LOCAL="mongodb://127.0.0.1:27017/"
export MONGO_DB="pcdoctor_swarm_canary"
export HA_STATE_FILE="$CANARY_ROOT/ha_state.json"
export AI_COORDINATION_ROOT="$CANARY_ROOT/coordination"
export INNEROS_TEMPORAL_ADDRESS="127.0.0.1:7233"
export INNEROS_TEMPORAL_NAMESPACE="inneros-canary"
export INNEROS_NATS_ENABLED="false"
export INNEROS_OTEL_ENABLED="false"

printf '%s\n' \
  "P0_MCP_CANARY=STARTING_FOREGROUND" \
  "branch=$BRANCH" \
  "head=$(git rev-parse HEAD)" \
  "bind=127.0.0.1:18102" \
  "profile=contifico_analytics" \
  "mongo_db=pcdoctor_swarm_canary" \
  "coordination_root=$AI_COORDINATION_ROOT" \
  "nats_enabled=false" \
  "runtime_fallback=production_checkout_import_only" \
  "production_port=8102_untouched" \
  "stop=Ctrl+C"

exec "$PYTHON_BIN" scripts/launch_p0_mcp_canary.py
