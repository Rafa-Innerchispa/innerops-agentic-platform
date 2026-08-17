#!/usr/bin/env bash
# Sincroniza NGROK_AUTHTOKEN desde snap/config → innerspark .env (sin imprimir secretos).
set -euo pipefail
SWARM_ROOT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
ENV_FILE="$SWARM_ROOT/.env"
EXAMPLE="$SWARM_ROOT/.env.example"

_resolve_token() {
  local cfg token
  for cfg in \
    "$SWARM_ROOT/data/ngrok.runtime.yml" \
    /home/rlopez/snap/ngrok/*/.config/ngrok/ngrok.yml \
    "$HOME/.config/ngrok/ngrok.yml"; do
    [[ -f "$cfg" ]] || continue
    token=$(grep -E '^\s*authtoken:' "$cfg" 2>/dev/null | head -1 | awk '{print $2}' | tr -d '"'"'" || true)
    if [[ -n "$token" ]]; then
      echo "$token"
      return 0
    fi
  done
  if [[ -f "$ENV_FILE" ]]; then
    token=$(grep -E '^NGROK_AUTHTOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)
    [[ -n "$token" ]] && echo "$token" && return 0
  fi
  return 1
}

TOKEN="$(_resolve_token || true)"
if [[ -z "$TOKEN" ]]; then
  echo "sync_ngrok_authtoken: no se encontró authtoken" >&2
  exit 1
fi

[[ -f "$ENV_FILE" ]] || cp -n "$EXAMPLE" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"

python3 - <<PY
from pathlib import Path
import re

env = Path("$ENV_FILE")
token = """$TOKEN"""
text = env.read_text(encoding="utf-8") if env.is_file() else ""
lines = []
found = False
for line in text.splitlines():
    if line.startswith("NGROK_AUTHTOKEN="):
        lines.append(f"NGROK_AUTHTOKEN={token}")
        found = True
    else:
        lines.append(line)
if not found:
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"NGROK_AUTHTOKEN={token}")
env.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
env.chmod(0o600)
print("OK sync_ngrok_authtoken →", env)
PY
