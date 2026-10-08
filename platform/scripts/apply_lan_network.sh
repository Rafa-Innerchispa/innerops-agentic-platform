#!/usr/bin/env bash
# Aplica network-lan.env sobre platform/.env (idempotente). Usar en servidores Intel/AMD.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
LAN_FILE="${HOME}/.config/ralphiia/network-lan.env"

if [[ ! -f "$LAN_FILE" ]]; then
  echo "Missing $LAN_FILE"
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

python3 /home/rlopez/inneros/inneros_core/platform/scripts/patch_env_lan_peers.py "$ENV_FILE"
python3 - "$ENV_FILE" "$LAN_FILE" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
lan_path = Path(sys.argv[2])
updates = {}
for line in lan_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    updates[k.strip()] = v.strip()

lines = env_path.read_text(encoding="utf-8").splitlines()
seen = set()
out = []
for line in lines:
    if "=" not in line or line.strip().startswith("#"):
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, val in updates.items():
    if key not in seen:
        out.append(f"{key}={val}")
env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print(f"OK merged LAN ({len(updates)} keys) -> {env_path}")
PY

echo "Restart MCP: systemctl --user daemon-reload && systemctl --user restart ralfia-mcp.service ralfia-mcp-profile@chatgpt_compact.service"
