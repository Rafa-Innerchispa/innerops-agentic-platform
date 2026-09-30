#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ACK="I_UNDERSTAND_ISOLATED_AMD_MCP_CANARY"
if [[ "${INNEROS_P0_AMD_MCP_ACK:-}" != "${EXPECTED_ACK}" ]]; then
  echo "REFUSED: set INNEROS_P0_AMD_MCP_ACK=${EXPECTED_ACK}" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
EXPECTED_ROOT="/home/rlopez/inneros-p0-amd-canary-20260930"
if [[ "${ROOT}" != "${EXPECTED_ROOT}" ]]; then
  echo "REFUSED: expected AMD clean canary root ${EXPECTED_ROOT}, got ${ROOT}" >&2
  exit 3
fi

BRANCH="$(git branch --show-current)"
if [[ "${BRANCH}" != "repair/coordination-recovery-20260929" ]]; then
  echo "REFUSED: unexpected branch ${BRANCH}" >&2
  exit 4
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "REFUSED: AMD canary checkout is not clean" >&2
  git status --short >&2
  exit 5
fi

PRODUCTION_PYTHON="/home/rlopez/inneros/inneros_core/platform/venv/bin/python"
if [[ ! -x "${PRODUCTION_PYTHON}" ]]; then
  echo "REFUSED: production Python runtime unavailable" >&2
  exit 6
fi

"${PRODUCTION_PYTHON}" - <<'PY'
import socket


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0

if not listening(8102):
    raise SystemExit("REFUSED: AMD production MCP 8102 is not listening")
if listening(18202):
    raise SystemExit("REFUSED: AMD canary port 18202 is already in use")
PY

CANARY_ROOT="${ROOT}/.canary"
mkdir -p "${CANARY_ROOT}/coordination"

export PYTHONPATH="${ROOT}/platform"
export MCP_HOST="127.0.0.1"
export MCP_PORT="18202"
export MCP_PUBLIC_URL="http://127.0.0.1:18202"
export MCP_LAN_URL="http://127.0.0.1:18202"
export MCP_TOOL_PROFILE="contifico_analytics"
export MONGO_URI="mongodb://127.0.0.1:27017/"
export MONGO_URI_PRIMARY="mongodb://127.0.0.1:27017/"
export MONGO_URI_LOCAL="mongodb://127.0.0.1:27017/"
export MONGO_DB="pcdoctor_swarm_canary"
export INNEROS_MONGO_DB="pcdoctor_swarm_canary"
export HA_STATE_FILE="${CANARY_ROOT}/ha_state.json"
export AI_COORDINATION_ROOT="${CANARY_ROOT}/coordination"
export INNEROS_TEMPORAL_ADDRESS="127.0.0.1:7233"
export INNEROS_TEMPORAL_NAMESPACE="default"
export INNEROS_TEMPORAL_TASK_QUEUE="inneros-p0-amd-canary"
export INNEROS_NATS_ENABLED="false"
export INNEROS_OTEL_ENABLED="false"

printf '%s\n' \
  "P0_AMD_MCP_CANARY=STARTING_FOREGROUND" \
  "branch=${BRANCH}" \
  "head=$(git rev-parse HEAD)" \
  "bind=127.0.0.1:18202" \
  "profile=contifico_analytics" \
  "mongo_db=pcdoctor_swarm_canary" \
  "nats_enabled=false" \
  "production_port_8102=untouched" \
  "live_checkout=untouched" \
  "stop=Ctrl+C"

exec "${PRODUCTION_PYTHON}" scripts/launch_p0_mcp_canary.py
