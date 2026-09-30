#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ACK="I_UNDERSTAND_ISOLATED_SMALL_CANARY"
if [[ "${INNEROS_P0_SMALL_CANARY_ACK:-}" != "${EXPECTED_ACK}" ]]; then
  echo "REFUSED: set INNEROS_P0_SMALL_CANARY_ACK=${EXPECTED_ACK}" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

BRANCH="$(git branch --show-current)"
if [[ "${BRANCH}" != "repair/coordination-recovery-20260929" ]]; then
  echo "REFUSED: expected repair branch, got ${BRANCH}" >&2
  exit 3
fi

PYTHON="${ROOT}/.venv-p0-canary/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  echo "REFUSED: missing ${PYTHON}" >&2
  exit 4
fi

"${PYTHON}" - <<'PY'
import socket
import sys


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0

if not listening(18102):
    print("REFUSED: monolith canary 127.0.0.1:18102 is not listening", file=sys.stderr)
    raise SystemExit(5)
if listening(18103):
    print("REFUSED: MCP Small canary port 18103 is already in use", file=sys.stderr)
    raise SystemExit(6)
if not listening(8102):
    print("REFUSED: production MCP 127.0.0.1:8102 is not listening", file=sys.stderr)
    raise SystemExit(7)
PY

mkdir -p .canary
cat > .canary/mcp-small-profiles.json <<JSON
{
  "default_profile": "profile_minimal",
  "allow_admin_profile": false,
  "profiles": {
    "profile_minimal": {
      "label": "P0 Small Canary Read Only",
      "allow_all": false,
      "max_tools": 15,
      "tools": [
        "mcp_version",
        "diagnose_mcp_session",
        "list_mcp_tool_profiles",
        "route_mcp_tools",
        "bootstrap_context",
        "get_coordination_live",
        "poll_agent_inbox",
        "list_ops_tasks",
        "a2a_status",
        "a2a_agent_cards",
        "project_runtime_bootstrap",
        "dev_swarm_scope_status",
        "dev_swarm_scheduler_status"
      ],
      "sandboxing": {
        "enabled": true,
        "read_only": true,
        "allowed_paths": ["${ROOT}/.canary"]
      }
    },
    "profile_admin": {
      "label": "Admin Full",
      "allow_all": true,
      "max_tools": 1000,
      "requires_auth": true,
      "tools": []
    }
  },
  "backends": {
    "monolith_canary": {
      "name": "P0 Monolith Canary",
      "url": "http://127.0.0.1:18102/mcp",
      "default": true,
      "prefixes": ["*"],
      "timeout_sec": 30
    }
  }
}
JSON

printf '%s\n' \
  "P0_MCP_SMALL_CANARY=STARTING_FOREGROUND" \
  "branch=${BRANCH}" \
  "head=$(git rev-parse HEAD)" \
  "bind=127.0.0.1:18103" \
  "backend=http://127.0.0.1:18102/mcp" \
  "profile=profile_minimal" \
  "admin_profile=false" \
  "production_port_8102=untouched" \
  "stop=Ctrl+C"

exec env PYTHONPATH="${ROOT}/platform" \
  "${PYTHON}" -m inneros_core_runtime.mcp_gateway.server \
  --host 127.0.0.1 \
  --port 18103 \
  --profile profile_minimal \
  --config "${ROOT}/.canary/mcp-small-profiles.json"
