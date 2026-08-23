#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f venv/bin/activate ]] || python3 -m venv venv
source venv/bin/activate
# Server extra obligatorio (fastmcp 3.x) — instalar ANTES de arrancar
pip install -q 'fastmcp-slim[server]>=3.0.0' 'mcp>=1.0.0'
grep -v '^fastmcp' requirements.txt | pip install -q -r /dev/stdin || pip install -q -r requirements.txt
export MCP_PORT="${MCP_PORT:-8102}"
export MCP_HOST="${MCP_HOST:-0.0.0.0}"
export PYTHONPATH="$ROOT"
# Liberar puerto si quedó un MCP anterior (evita Errno 98)
_old_pid="$(lsof -t -i :"${MCP_PORT}" 2>/dev/null || true)"
if [[ -n "${_old_pid}" ]]; then
  echo "Deteniendo MCP anterior PID ${_old_pid} en :${MCP_PORT}..."
  kill ${_old_pid} 2>/dev/null || true
  sleep 1
fi
echo "MCP RaphiIA v2.1 en http://${MCP_HOST}:${MCP_PORT}/mcp"
# -m evita shadowing: raphiia_openai/mcp_catalog vs paquete PyPI mcp
exec python3 -m raphiia_openai.mcp_server
