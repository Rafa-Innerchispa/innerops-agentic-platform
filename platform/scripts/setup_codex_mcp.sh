#!/usr/bin/env bash
# Merge MCP RalfIA en ~/.codex/config.toml o crea .codex/config.toml del proyecto
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
PROJECT_CODEX="$ROOT/.codex/config.toml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Falta $ENV_FILE"
  exit 1
fi

KEY="$(grep -E '^MCP_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
if [[ -z "$KEY" ]]; then
  echo "MCP_API_KEY vacío en .env"
  exit 1
fi

mkdir -p "$ROOT/.codex"
cat > "$PROJECT_CODEX" <<EOF
[projects."/home/rlopez/projects/raphiia-openai"]
trust_level = "trusted"

[mcp_servers.ralfia]
url = "http://127.0.0.1:8102/mcp"
http_headers = { "X-API-Key" = "$KEY" }
startup_timeout_sec = 20
tool_timeout_sec = 120
enabled = true
EOF

chmod 600 "$PROJECT_CODEX" 2>/dev/null || true

GLOBAL_CODEX="$HOME/.codex/config.toml"
mkdir -p "$HOME/.codex"
if [[ -f "$GLOBAL_CODEX" ]] && grep -q '\[mcp_servers\.ralfia\]' "$GLOBAL_CODEX" 2>/dev/null; then
  echo "Global $GLOBAL_CODEX ya tiene ralfia"
else
  cat >> "$GLOBAL_CODEX" <<EOF

[projects."/home/rlopez/projects/raphiia-openai"]
trust_level = "trusted"

[mcp_servers.ralfia]
url = "http://127.0.0.1:8102/mcp"
http_headers = { "X-API-Key" = "$KEY" }
startup_timeout_sec = 20
tool_timeout_sec = 120
enabled = true
EOF
  chmod 600 "$GLOBAL_CODEX" 2>/dev/null || true
  echo "OK → $GLOBAL_CODEX (merge global)"
fi

echo "OK → $PROJECT_CODEX"
echo "Verifica: codex mcp list  o  /mcp en TUI"
