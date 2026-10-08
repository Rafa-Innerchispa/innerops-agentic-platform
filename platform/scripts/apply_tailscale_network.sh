#!/usr/bin/env bash
# DEPRECATED en servidores: usa apply_lan_network.sh (192.168.1.4/5).
# Solo ejecutar apply_tailscale_network si trabajas desde laptop fuera de LAN.
set -euo pipefail
echo "WARN: prefer apply_lan_network.sh on Intel/AMD servers" >&2
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
TS_FILE="${HOME}/.config/ralphiia/network-tailscale.env"

if [[ ! -f "$TS_FILE" ]]; then
  echo "Missing $TS_FILE"
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

python3 - "$ENV_FILE" "$TS_FILE" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
ts_path = Path(sys.argv[2])
updates = {}
for line in ts_path.read_text(encoding="utf-8").splitlines():
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

marker = "# --- tailscale canonical (managed by apply_tailscale_network.sh) ---"
if marker not in "\n".join(out):
    out.append("")
    out.append(marker)

env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print(f"OK updated {env_path} ({len(updates)} keys)")
PY

echo "Restart MCP if needed: systemctl --user restart ralfia-mcp.service ralfia-mcp-profile@chatgpt_compact.service"
