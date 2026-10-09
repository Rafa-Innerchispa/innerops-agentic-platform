#!/usr/bin/env bash
# Estado de licencia Evolution 2.4+ en Intel y/o AMD (solo LAN).
set -euo pipefail

NODE="${1:-both}"
APIKEY="${EVOLUTION_API_KEY:-swarm_os_evolution_key_2026}"
INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
AMD="${RALFIA_AMD_HOST:-192.168.1.5}"
PORT=8082

check_one() {
  local name="$1" host="$2"
  echo "=== $name ($host:$PORT) ==="
  if ! ver=$(curl -sf -m 8 "http://${host}:${PORT}/" 2>/dev/null); then
    echo "  unreachable"
    return 1
  fi
  echo "$ver" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  version:', d.get('version'))" 2>/dev/null || true
  curl -sf -m 8 "http://${host}:${PORT}/license/status" | python3 -m json.tool 2>/dev/null || echo "  (no /license/status — ¿2.3.x?)"
  echo
}

case "$NODE" in
  intel|primary|.4) check_one "Intel" "$INTEL" ;;
  amd|backup|.5) check_one "AMD" "$AMD" ;;
  both)
    check_one "Intel" "$INTEL" || true
    check_one "AMD" "$AMD" || true
    ;;
  *) echo "Uso: $0 [intel|amd|both]"; exit 2 ;;
esac
