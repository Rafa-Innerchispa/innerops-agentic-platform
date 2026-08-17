#!/usr/bin/env bash
# Expone MCP :8102 vía ngrok HTTPS para ChatGPT Connectors.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${MCP_PORT:-8102}"
CONFIG="${ROOT}/scripts/ngrok.mcp.yml"
SWARM_NGROK="${SWARM_NGROK_CONFIG:-/home/rlopez/projects/innerspark-swarm-os-cursor-local/data/ngrok.runtime.yml}"
EXTRA=()
if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  EXTRA+=(--authtoken "$NGROK_AUTHTOKEN")
elif [[ -f "$SWARM_NGROK" ]]; then
  TOKEN="$(grep -E '^authtoken:' "$SWARM_NGROK" | awk '{print $2}')"
  [[ -n "$TOKEN" ]] && EXTRA+=(--authtoken "$TOKEN")
fi
echo "Iniciando túnel ngrok → localhost:${PORT}/mcp"
echo "En ChatGPT Connectors usa: https://TU-SUBDOMINIO.ngrok-free.dev/mcp"
exec ngrok start raphiia-mcp --config "$CONFIG" "${EXTRA[@]}" --log=stdout
