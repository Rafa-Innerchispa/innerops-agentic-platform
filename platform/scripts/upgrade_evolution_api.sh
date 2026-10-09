#!/usr/bin/env bash
# Actualiza Evolution API (Docker) en Intel .4 y/o AMD .5 — sin perder volúmenes.
set -euo pipefail

TARGET_IMAGE="${EVOLUTION_IMAGE:-evoapicloud/evolution-api:2.4.0-rc2}"
NODE="${1:-both}" # primary | amd | both

log() { echo "[upgrade-evolution] $*"; }

upgrade_primary() {
  log "Intel (.4) — /home/rlopez/evolution-api"
  ssh -o ConnectTimeout=15 ralfiia-intel bash -s <<EOF
set -euo pipefail
cd /home/rlopez/evolution-api
docker compose pull
docker compose up -d --force-recreate
sleep 4
curl -sf http://127.0.0.1:8082/ | head -c 200
echo
EOF
}

upgrade_amd() {
  log "AMD (.5) — evolution-amd.docker-compose.yaml"
  COMPOSE="/home/rlopez/projects/ralfiia-amd-standby/docker/evolution-amd.docker-compose.yaml"
  if [[ ! -f "$COMPOSE" ]]; then
    log "compose no encontrado: $COMPOSE"
    return 1
  fi
  docker compose -f "$COMPOSE" pull
  docker compose -f "$COMPOSE" up -d --force-recreate
  sleep 4
  curl -sf http://127.0.0.1:8082/ | head -c 200 || true
  echo
}

case "$NODE" in
  primary|intel|.4) upgrade_primary ;;
  amd|backup|.5) upgrade_amd ;;
  both)
    upgrade_primary || log "primary falló (continúo AMD si aplica)"
    upgrade_amd || log "AMD falló (chip/WA puede estar offline)"
    ;;
  *) echo "Uso: $0 [primary|amd|both]"; exit 2 ;;
esac

log "Listo. Imagen por defecto: 2.4.0-rc2 — activar licencia en cada nodo (docs/EVOLUTION_LICENSE.md)."
