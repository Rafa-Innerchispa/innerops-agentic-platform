#!/usr/bin/env bash
# Configura MCP RalfIA para Cursor + Codex (proyecto + home del usuario).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Falta $ENV_FILE"
  exit 1
fi

KEY="$(grep -E '^MCP_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
if [[ -z "$KEY" || "$KEY" == "change-me-long-random-secret" ]]; then
  echo "Configura MCP_API_KEY en .env o Panel :2002"
  exit 1
fi

echo "==> Cursor (.cursor/mcp.json proyecto + ~/.cursor/mcp.json)"
mkdir -p "$ROOT/.cursor" "$HOME/.cursor"
python3 - <<PY
import json
from pathlib import Path

cfg = {
    "mcpServers": {
        "ralfia": {
            "type": "streamable-http",
            "url": "http://127.0.0.1:8102/mcp",
            "headers": {"X-API-Key": "$KEY"},
        }
    }
}
for path in (
    Path("$ROOT/.cursor/mcp.json"),
    Path.home() / ".cursor/mcp.json",
):
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"  OK {path}")
PY

echo "==> Codex (.codex/config.toml proyecto + ~/.codex/config.toml)"
mkdir -p "$ROOT/.codex" "$HOME/.codex"
python3 - <<PY
from pathlib import Path

root = Path("$ROOT")
key = """$KEY"""
proj_path = "/home/rlopez/projects/raphiia-openai"

block = f'''
[projects."{proj_path}"]
trust_level = "trusted"

[mcp_servers.ralfia]
url = "http://127.0.0.1:8102/mcp"
http_headers = {{ "X-API-Key" = "{key}" }}
startup_timeout_sec = 20
tool_timeout_sec = 120
enabled = true
'''

def merge_codex(path: Path) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "[mcp_servers.ralfia]" in text:
        print(f"  ya tiene ralfia: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\\n" + block, encoding="utf-8")
    path.chmod(0o600)
    print(f"  OK {path}")

for p in (root / ".codex/config.toml", Path.home() / ".codex/config.toml"):
    merge_codex(p)
PY

echo "==> Servicio MCP"
install -D -m 0644 "$ROOT/systemd/user/ralfia-mcp.service" "$HOME/.config/systemd/user/ralfia-mcp.service"
systemctl --user daemon-reload 2>/dev/null || true
if systemctl --user is-active --quiet ralfia-mcp 2>/dev/null; then
  systemctl --user restart ralfia-mcp
  echo "  ralfia-mcp: reiniciado (EnvironmentFile=.env)"
else
  echo "  arrancando ralfia-mcp..."
  systemctl --user enable --now ralfia-mcp 2>/dev/null || systemctl --user start ralfia-mcp || true
fi

echo "==> Codex verificación"
if command -v codex >/dev/null 2>&1; then
  codex mcp list 2>&1 || true
else
  echo "  codex CLI no instalado — instala con: npm i -g @openai/codex"
fi

cat <<EOF

Listo.

Cursor:
  1. Developer → Reload Window  (o reinicia Cursor)
  2. Cursor Settings → Tools & MCP → debe aparecer "ralfia"

Codex:
  1. cd $ROOT && codex   (TUI)
  2. Comando /mcp  o  codex mcp list

URL MCP: http://127.0.0.1:8102/mcp
Auth: header X-API-Key (mismo MCP_API_KEY del .env)
EOF
