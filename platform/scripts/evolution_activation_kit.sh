#!/usr/bin/env bash
# Imprime URLs LAN y datos para activar Evolution (Intel + AMD). No usa Tailscale.
set -euo pipefail

LAN_INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
LAN_AMD="${RALFIA_AMD_HOST:-192.168.1.5}"
PORT=8082
APIKEY="${EVOLUTION_API_KEY:-swarm_os_evolution_key_2026}"

hdr() { echo; echo "=== $* ==="; }

hdr "Evolution API — activación (solo LAN)"
echo "API key global (header apikey): ${APIKEY}"
echo "Intel LAN: ${LAN_INTEL}  |  AMD LAN: ${LAN_AMD}"

hdr "Intel — instancia primary"
echo "Manager:     http://${LAN_INTEL}:${PORT}/manager"
echo "API base:    http://${LAN_INTEL}:${PORT}"
echo "Instancia:   RalphiIA-pcdoctor"
echo "Health:      curl -sf -H \"apikey: ${APIKEY}\" http://${LAN_INTEL}:${PORT}/"

hdr "AMD — línea Innerchispa"
echo "Manager:     http://${LAN_AMD}:${PORT}/manager"
echo "API base:    http://${LAN_AMD}:${PORT}"
echo "Instancia:   Innerchispa"
echo "Chip E.164:  593962546650 (0962546650)"
echo "Emparejar:   curl -sS -H \"apikey: ${APIKEY}\" \"http://${LAN_AMD}:${PORT}/instance/connect/Innerchispa?number=593962546650\""

hdr "Estado actual"
for node in intel amd; do
  if [[ "$node" == "intel" ]]; then host="$LAN_INTEL"; else host="$LAN_AMD"; fi
  if curl -sf -m 4 -H "apikey: ${APIKEY}" "http://${host}:${PORT}/instance/fetchInstances" >/tmp/evo_inst.json 2>/dev/null; then
    python3 - <<'PY' "$node"
import json, sys
node = sys.argv[1]
for i in json.load(open("/tmp/evo_inst.json")):
    print(f"{node}: {i.get('name')} number={i.get('number')} status={i.get('connectionStatus')} owner={i.get('ownerJid')}")
PY
  else
    echo "${node}: unreachable at http://${host}:${PORT}"
  fi
done
