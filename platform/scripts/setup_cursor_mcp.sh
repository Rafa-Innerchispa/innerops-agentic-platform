#!/usr/bin/env bash
# Genera .cursor/mcp.json desde .env (no commitear mcp.json con secretos)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
OUT="$ROOT/.cursor/mcp.json"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Falta $ENV_FILE — cp .env.example .env y configura MCP_API_KEY"
  exit 1
fi

KEY="$(grep -E '^MCP_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
if [[ -z "$KEY" || "$KEY" == "change-me-long-random-secret" ]]; then
  echo "Configura MCP_API_KEY real en .env o Panel :2002 → Configuración"
  exit 1
fi

mkdir -p "$ROOT/.cursor"
python3 - <<PY
import json
from pathlib import Path
out = Path("$OUT")
cfg = {
    "mcpServers": {
        "ralfia": {
            "type": "streamable-http",
            "url": "http://127.0.0.1:8102/mcp",
            "headers": {"X-API-Key": "$KEY"},
        }
    }
}
out.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"OK → {out}")
PY
echo "Recarga Cursor (Developer: Reload Window) y revisa Settings → MCP"
