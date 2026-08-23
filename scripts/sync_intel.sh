#!/usr/bin/env bash
# Sync InnerOS core AMD (.5) → Intel (.4) + symlinks + reinicio servicios
set -euo pipefail

INTEL="${INNEROS_INTEL_HOST:-rlopez@192.168.1.4}"
SRC_CORE="/home/rlopez/inneros/inneros_core"
SRC_ENV="/home/rlopez/inneros/INNEROS_ENV.sh"
SRC_README="/home/rlopez/inneros/README.md"
REMOTE_INNEROS="/home/rlopez/inneros"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== 1. Preparar destino Intel ==="
ssh -o ConnectTimeout=10 "$INTEL" bash -s <<'PREP'
set -euo pipefail
# ~/inneros legacy puede ser root:root — usar projects/inneros si no hay write
if [[ -w /home/rlopez/inneros ]] 2>/dev/null; then
  DEST_ROOT="/home/rlopez/inneros"
else
  DEST_ROOT="/home/rlopez/projects/inneros"
  echo "WARN: ~/inneros no writable (root) — usando $DEST_ROOT"
  echo "      Ejecutar en Intel: sudo chown -R rlopez:rlopez ~/inneros"
fi
mkdir -p "$DEST_ROOT/inneros_core"
echo "$DEST_ROOT" > /tmp/inneros_dest_root.txt
PREP

REMOTE_INNEROS=$(ssh "$INTEL" 'cat /tmp/inneros_dest_root.txt')
log "Destino Intel: $REMOTE_INNEROS"

log "=== 2. Rsync inneros_core → Intel (sin venv, sin backups) ==="
rsync -az --delete \
  --exclude 'platform/venv/' \
  --exclude 'platform/__pycache__/' \
  --exclude 'platform/backups/' \
  --exclude 'platform/.git/' \
  --exclude '.git/' \
  "$SRC_CORE/" "$INTEL:$REMOTE_INNEROS/inneros_core/"

rsync -az "$SRC_ENV" "$SRC_README" "$INTEL:$REMOTE_INNEROS/"

log "=== 3. Intel: venv + .env + symlinks ==="
ssh "$INTEL" bash -s <<REMOTE
set -euo pipefail
DEST_ROOT="\$(cat /tmp/inneros_dest_root.txt)"
CORE="\$DEST_ROOT/inneros_core"
PLATFORM="\$CORE/platform"
OLD="/home/rlopez/projects/raphiia-openai"

# Preservar venv y .env del árbol legacy Intel
BAK=\$(ls -d /home/rlopez/projects/raphiia-openai.bak.* 2>/dev/null | tail -1 || true)
if [[ -d "\$OLD" && ! -L "\$OLD" ]]; then
  [[ -d "\$OLD/venv" ]] && rm -f "\$PLATFORM/venv" && ln -sfn "\$OLD/venv" "\$PLATFORM/venv"
  [[ -f "\$OLD/.env" && ! -f "\$PLATFORM/.env" ]] && cp -a "\$OLD/.env" "\$PLATFORM/.env"
  mv "\$OLD" "/home/rlopez/projects/raphiia-openai.bak.\$(date +%s)"
  BAK=\$(ls -d /home/rlopez/projects/raphiia-openai.bak.* 2>/dev/null | tail -1)
fi
if [[ -n "\${BAK:-}" && -d "\$BAK/venv" ]]; then
  rm -f "\$PLATFORM/venv"
  ln -sfn "\$BAK/venv" "\$PLATFORM/venv"
fi
ln -sfn "\$PLATFORM" /home/rlopez/projects/raphiia-openai

# agents_pool compat (reemplazar ~/inneros_core dir si existe)
if [[ -d /home/rlopez/inneros_core && ! -L /home/rlopez/inneros_core ]]; then
  mv /home/rlopez/inneros_core "/home/rlopez/inneros_core.bak.\$(date +%s)"
fi
ln -sfn "\$CORE/agents_pool" /home/rlopez/inneros_core

mkdir -p /home/rlopez/data/tenants/{pcdoctor,innerchispa,template}

# INNEROS_ENV adaptado al destino real
cat > "\$DEST_ROOT/INNEROS_ENV.sh" <<EOF
export INNEROS_ROOT=\$DEST_ROOT
export INNEROS_CORE=\$CORE
export INNEROS_PLATFORM=\$PLATFORM
export INNEROS_AGENTS_POOL=\$CORE/agents_pool
export INNEROS_COMPANIES=\$CORE/companies
export RAPHIIA_ROOT=\$PLATFORM
export PYTHONPATH=\$PLATFORM
EOF

echo "INNEROS_ROOT=\$DEST_ROOT"
ls -la /home/rlopez/projects/raphiia-openai /home/rlopez/inneros_core
REMOTE

log "=== 4. Reiniciar servicios user en Intel ==="
ssh "$INTEL" 'systemctl --user daemon-reload; systemctl --user restart ralfia-mcp ralfia-portal ralfia-app ralfia-voice-gateway ralfia-quoteops ralfia-smart-quoter 2>/dev/null || systemctl --user restart ralfia-mcp ralfia-portal ralfia-app'

log "=== 5. Health checks ==="
sleep 3
ssh "$INTEL" bash -s <<'CHECK'
for url in "http://127.0.0.1:8102/health" "http://127.0.0.1:8101/status" "http://127.0.0.1:2002/"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$url" 2>/dev/null || echo "000")
  echo "$url → HTTP $code"
done
systemctl --user is-active ralfia-mcp ralfia-portal ralfia-app
CHECK

log "=== DONE ==="
