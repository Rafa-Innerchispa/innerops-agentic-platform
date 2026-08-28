#!/usr/bin/env bash
# Desde Intel (.4): despliega ngrok en AMD (.5) sin sudo interactivo en Windows.
set -euo pipefail
AMD="${RALFIA_AMD_HOST:-192.168.1.5}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== 1/3 Sync authtoken (Intel) ==="
bash "$ROOT/scripts/sync_ngrok_authtoken.sh"

echo "=== 2/3 Copiar token a AMD (SSH) ==="
TOKEN=""
if [[ -f /home/rlopez/projects/innerspark-swarm-os-cursor-local/.env ]]; then
  TOKEN=$(grep -E '^NGROK_AUTHTOKEN=' /home/rlopez/projects/innerspark-swarm-os-cursor-local/.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d '\r')
fi
if [[ -z "$TOKEN" ]]; then
  for cfg in /home/rlopez/snap/ngrok/*/.config/ngrok/ngrok.yml "$HOME/.config/ngrok/ngrok.yml"; do
    [[ -f "$cfg" ]] || continue
    TOKEN=$(grep -E '^\s*authtoken:' "$cfg" | head -1 | awk '{print $2}' | tr -d '"'"'" || true)
    [[ -n "$TOKEN" ]] && break
  done
fi
[[ -n "$TOKEN" ]] || { echo "No authtoken en Intel"; exit 1; }

ssh -o BatchMode=yes -o ConnectTimeout=10 "rlopez@${AMD}" bash -s <<REMOTE
set -euo pipefail
mkdir -p ~/.config/ngrok
printf 'version: "2"\nauthtoken: ${TOKEN}\n' > ~/.config/ngrok/ngrok.yml
chmod 600 ~/.config/ngrok/ngrok.yml
echo "OK token en AMD"
REMOTE

echo "=== 3/3 install_ngrok_amd.sh en AMD ==="
ssh -o BatchMode=yes "rlopez@${AMD}" "bash $ROOT/scripts/install_ngrok_amd.sh"
