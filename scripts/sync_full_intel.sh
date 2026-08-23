#!/usr/bin/env bash
# Sync completo AMD → Intel + finalización Intel
set -euo pipefail
INTEL="${INNEROS_INTEL_HOST:-rlopez@192.168.1.4}"
SRC="/home/rlopez/inneros"
log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== Rsync ~/inneros → Intel ==="
ssh -o ConnectTimeout=10 "$INTEL" "mkdir -p /home/rlopez/inneros"
rsync -az --delete \
  --exclude 'inneros_core/platform/venv/' \
  --exclude 'inneros_core/platform/__pycache__/' \
  --exclude 'inneros_core/platform/backups/' \
  --exclude '.git/' \
  "$SRC/" "$INTEL:/home/rlopez/inneros/"

log "=== Finalize Intel ==="
ssh "$INTEL" "bash /home/rlopez/inneros/inneros_core/scripts/finalize_intel_paths.sh"

log "=== Sync complete ==="
