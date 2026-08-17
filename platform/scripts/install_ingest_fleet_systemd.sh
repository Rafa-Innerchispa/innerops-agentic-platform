#!/usr/bin/env bash
# Instala flota ingesta permanente: VKR en AMD + PST en Intel
set -euo pipefail

PLATFORM="/home/rlopez/inneros/inneros_core/platform"
UNIT_DIR="${PLATFORM}/systemd/user"
USER_UNIT="${HOME}/.config/systemd/user"
INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
CMD="${1:-install}"

install_amd() {
  mkdir -p "$USER_UNIT"
  cp "${UNIT_DIR}/ralfia-ingest-vkr@.service" "$USER_UNIT/"
  systemctl --user daemon-reload
  for i in 0 1; do
    systemctl --user enable "ralfia-ingest-vkr@${i}.service"
    systemctl --user restart "ralfia-ingest-vkr@${i}.service"
  done
  echo "AMD: ralfia-ingest-vkr@{0,1} activos"
}

install_intel() {
  scp -q "${UNIT_DIR}/ralfia-ingest-pst@.service" "rlopez@${INTEL}:${USER_UNIT}/"
  scp -q "${PLATFORM}/scripts/run_local_ingest_fleet.py" "rlopez@${INTEL}:${PLATFORM}/scripts/"
  ssh "rlopez@${INTEL}" "bash -s" <<REMOTE
set -euo pipefail
systemctl --user daemon-reload
for i in 0 1 2; do
  systemctl --user enable ralfia-ingest-pst@\${i}.service
  systemctl --user restart ralfia-ingest-pst@\${i}.service
done
echo "Intel: ralfia-ingest-pst@{0,1,2} activos"
REMOTE
}

stop_all() {
  for i in 0 1; do systemctl --user stop "ralfia-ingest-vkr@${i}.service" 2>/dev/null || true; done
  ssh "rlopez@${INTEL}" 'for i in 0 1 2; do systemctl --user stop ralfia-ingest-pst@${i}.service 2>/dev/null || true; done' || true
}

status_all() {
  for i in 0 1; do
    systemctl --user is-active "ralfia-ingest-vkr@${i}.service" 2>/dev/null && echo "AMD vkr-$i: active" || echo "AMD vkr-$i: inactive"
  done
  ssh "rlopez@${INTEL}" 'for i in 0 1 2; do systemctl --user is-active ralfia-ingest-pst@${i}.service 2>/dev/null && echo "Intel pst-$i: active" || echo "Intel pst-$i: inactive"; done' || true
}

case "$CMD" in
  install) install_amd; install_intel ;;
  stop) stop_all ;;
  status) status_all ;;
  *) echo "Usage: $0 {install|stop|status}"; exit 1 ;;
esac
