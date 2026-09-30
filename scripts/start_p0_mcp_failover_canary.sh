#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ACK="I_UNDERSTAND_ISOLATED_MCP_FAILOVER_CANARY"
if [[ "${INNEROS_P0_FAILOVER_ACK:-}" != "${EXPECTED_ACK}" ]]; then
  echo "REFUSED: set INNEROS_P0_FAILOVER_ACK=${EXPECTED_ACK}" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
if [[ "$(git branch --show-current)" != "repair/coordination-recovery-20260929" ]]; then
  echo "REFUSED: unexpected branch" >&2
  exit 3
fi
if [[ -n "$(git status --porcelain | grep -vE '^\?\? (\.venv-p0-canary|\.canary)/' || true)" ]]; then
  echo "REFUSED: Intel canary checkout is not clean" >&2
  exit 4
fi

PYTHON="${ROOT}/.venv-p0-canary/bin/python"
"${PYTHON}" - <<'PY'
import socket


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0

checks = {
    8102: True,   # production must remain up
    18212: True,  # SSH tunnel to AMD canary
    18113: False, # failover gateway canary must be free
    18999: False, # deliberately unavailable primary
}
for port, expected in checks.items():
    actual = listening(port)
    if actual != expected:
        raise SystemExit(
            f"REFUSED: port {port} listening={actual}, expected={expected}"
        )
PY

mkdir -p .canary
cat > .canary/mcp-failover-profiles.json <<'JSON'
{
  "default_profile": "profile_minimal",
  "allow_admin_profile": false,
  "profiles": {
    "profile_minimal": {
      "label": "P0 Failover Read Only",
      "allow_all": false,
      "max_tools": 15,
      "tools": [
        "mcp_version",
        "diagnose_mcp_session",
        "get_coordination_live",
        "list_ops_tasks",
        "a2a_status",
        "a2a_agent_cards",
        "dev_swarm_scheduler_status"
      ],
      "sandboxing": {
        "enabled": true,
        "read_only": true,
        "allowed_paths": []
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
    "intel_primary_unavailable": {
      "name": "Intel Primary Deliberately Unavailable",
      "url": "http://127.0.0.1:18999/mcp",
      "default": true,
      "prefixes": ["*"],
      "timeout_sec": 2
    },
    "amd_canary_tunnel": {
      "name": "AMD Clean Canary via SSH Tunnel",
      "url": "http://127.0.0.1:18212/mcp",
      "default": false,
      "prefixes": [],
      "timeout_sec": 10
    }
  }
}
JSON

printf '%s\n' \
  "P0_MCP_FAILOVER_CANARY=STARTING_FOREGROUND" \
  "head=$(git rev-parse HEAD)" \
  "bind=127.0.0.1:18113" \
  "primary=http://127.0.0.1:18999/mcp_deliberately_unavailable" \
  "secondary=http://127.0.0.1:18212/mcp_amd_tunnel" \
  "failover_enabled=true" \
  "read_only=true" \
  "production_port_8102=untouched" \
  "stop=Ctrl+C"

exec env \
  PYTHONPATH="${ROOT}/platform" \
  INNEROS_MCP_FAILOVER_ENABLED="true" \
  "${PYTHON}" -m inneros_core_runtime.mcp_gateway.server \
  --host 127.0.0.1 \
  --port 18113 \
  --profile profile_minimal \
  --config "${ROOT}/.canary/mcp-failover-profiles.json"
