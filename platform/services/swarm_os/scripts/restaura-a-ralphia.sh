#!/usr/bin/env bash
# Restaura RALF IA v2.0 — un solo comando para levantar todo tras desastre o máquina nueva.
# Uso:
#   restaura-a-ralphia                    # último backup local
#   restaura-a-ralphia /ruta/backup.tar.gz
#   BACKUP_FROM_CLOUD=1 restaura-a-ralphia   # baja el más reciente de Google Drive
set -euo pipefail

PROJECT="/home/rlopez/projects/innerspark-swarm-os-cursor-local"
BACKUP_ROOT="${BACKUP_ROOT:-/home/rlopez/backups/disaster_recovery}"
RCLONE_REMOTE="${RCLONE_REMOTE:-Ralphi-IA-Gdrive}"
RCLONE_DIR="${RCLONE_DIR:-RalphiIA_Backups/disaster_recovery}"
USER_NAME="${SUDO_USER:-$USER}"

log() { echo "[restaura-a-ralphia] $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { log "ERROR: falta comando $1"; exit 1; }
}

pick_backup() {
  if [[ -n "${1:-}" && -f "$1" ]]; then
    echo "$1"
    return
  fi
  if [[ "${BACKUP_FROM_CLOUD:-0}" = "1" ]] && command -v rclone >/dev/null 2>&1; then
    log "Buscando último backup en ${RCLONE_REMOTE}:${RCLONE_DIR}..."
    local latest
    latest=$(rclone lsf "${RCLONE_REMOTE}:${RCLONE_DIR}/" --files-only 2>/dev/null | grep 'disaster_recovery_.*\.tar\.gz$' | sort | tail -1)
    if [[ -z "$latest" ]]; then
      log "ERROR: no hay backups en la nube"
      exit 1
    fi
    mkdir -p "$BACKUP_ROOT"
    rclone copy "${RCLONE_REMOTE}:${RCLONE_DIR}/${latest}" "$BACKUP_ROOT/"
    echo "$BACKUP_ROOT/$latest"
    return
  fi
  local local_latest
  local_latest=$(ls -1t "$BACKUP_ROOT"/disaster_recovery_*.tar.gz 2>/dev/null | head -1 || true)
  if [[ -z "$local_latest" ]]; then
    log "ERROR: no hay backup local en $BACKUP_ROOT"
    log "Opciones: BACKUP_FROM_CLOUD=1 restaura-a-ralphia  o  restaura-a-ralphia /ruta/archivo.tar.gz"
    exit 1
  fi
  echo "$local_latest"
}

extract_backup() {
  local archive="$1"
  local work
  work=$(mktemp -d)
  log "Extrayendo $archive ..."
  tar -xzf "$archive" -C "$work"
  local inner
  inner=$(find "$work" -mindepth 1 -maxdepth 1 -type d | head -1)
  if [[ -z "$inner" ]]; then
    inner="$work"
  fi
  echo "$inner"
}

restore_code() {
  local dir="$1"
  log "Restaurando código..."
  if [[ -f "$dir/projects_code.tar.gz" ]]; then
    tar -xzf "$dir/projects_code.tar.gz" -C /home/rlopez
  else
    log "AVISO: projects_code.tar.gz no encontrado"
  fi
  if [[ -f "$dir/infra_compose.tar.gz" ]]; then
    tar -xzf "$dir/infra_compose.tar.gz" -C /home/rlopez
  fi
}

restore_mongo() {
  local dir="$1"
  local archive="$dir/mongo_pcdoctor_swarm.archive"
  [[ -f "$archive" ]] || { log "AVISO: sin dump MongoDB"; return 0; }
  log "Restaurando MongoDB pcdoctor_swarm..."
  if docker ps --format '{{.Names}}' | grep -q '^mongodb$'; then
    docker exec -i mongodb mongorestore --archive --drop --nsInclude='pcdoctor_swarm.*' < "$archive"
  else
    need_cmd mongorestore
    mongorestore --archive="$archive" --drop
  fi
}

restore_env() {
  local dir="$1"
  if [[ -f "$dir/envs/swarm-os.env" && ! -f "$PROJECT/.env" ]]; then
    cp "$dir/envs/swarm-os.env" "$PROJECT/.env"
    log "Restaurado .env desde backup"
  fi
}

setup_python() {
  log "Python venv + dependencias..."
  cd "$PROJECT"
  if [[ ! -d venv ]]; then
    python3 -m venv venv
  fi
  # shellcheck disable=SC1091
  source venv/bin/activate
  pip install -q -r requirements.txt
}

setup_admin() {
  log "Admin npm (si hace falta)..."
  cd "$PROJECT/admin"
  if [[ ! -d node_modules ]]; then
    npm install --silent
  fi
}

start_docker() {
  log "Levantando Docker stacks..."
  if [[ -f /home/rlopez/ai-server-v2/docker/docker-compose.yml ]]; then
    (cd /home/rlopez/ai-server-v2/docker && docker compose up -d) || true
  fi
  if [[ -f /home/rlopez/whisper-service/docker-compose.yml ]]; then
    (cd /home/rlopez/whisper-service && docker compose up -d) || true
  fi
  if [[ -f /home/rlopez/projects/inneros/docker-compose.yml ]]; then
    (cd /home/rlopez/projects/inneros && docker compose up -d) || true
  fi
  if [[ -f "$PROJECT/docker/filebrowser-compose.yml" ]]; then
    docker compose -f "$PROJECT/docker/filebrowser-compose.yml" up -d || true
  fi
}

start_systemd() {
  if [[ -f "$PROJECT/scripts/install_services.sh" ]]; then
    log "Habilitando servicios systemd (puede pedir sudo)..."
    bash "$PROJECT/scripts/install_services.sh" || log "AVISO: install_services requiere contraseña sudo"
  fi
}

show_urls() {
  cat <<EOF

=== RALF IA restaurado ===
  Portal:    http://192.168.1.4:8800
  Admin:     http://192.168.1.4:5173
  API:       http://192.168.1.4:8100/docs
  Archivos:  http://192.168.1.4:8081

GitHub (código fuente): ver docs/GITHUB_CONECTAR.md
EOF
}

main() {
  need_cmd docker
  need_cmd python3
  need_cmd tar

  local archive workdir
  archive=$(pick_backup "${1:-}")
  workdir=$(extract_backup "$archive")

  restore_code "$workdir"
  restore_env "$workdir"
  start_docker
  restore_mongo "$workdir"
  setup_python
  setup_admin
  start_systemd
  show_urls
  log "Listo."
}

main "$@"
