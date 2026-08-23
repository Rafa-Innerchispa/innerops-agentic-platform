#!/usr/bin/env bash
# Consolidación final InnerOS — Intel (.4)
set -euo pipefail

INNEROS_ROOT="/home/rlopez/inneros"
CORE="$INNEROS_ROOT/inneros_core"
PLATFORM="$CORE/platform"
OLD="/home/rlopez/projects/raphiia-openai"
RAG="/home/rlopez/projects/inneros"
RAG_NEW="/home/rlopez/projects/inneros-rag-legacy"
STAGING="$RAG/inneros_core"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== 1. Mover inneros_core a ~/inneros/ ==="
mkdir -p "$INNEROS_ROOT"
if [[ -d "$STAGING/platform" ]]; then
  if [[ -d "$CORE/platform" ]]; then
    rsync -a "$STAGING/" "$CORE/"
  else
    mv "$STAGING" "$CORE"
  fi
  rmdir "$RAG/inneros_core" 2>/dev/null || rm -rf "$RAG/inneros_core" 2>/dev/null || true
fi

log "=== 2. Renombrar RAG legacy ==="
if [[ -d "$RAG/.git" && ! -e "$RAG_NEW" ]]; then
  mv "$RAG" "$RAG_NEW"
  log "inneros → inneros-rag-legacy"
fi

log "=== 3. INNEROS_ENV + README ==="
cat > "$INNEROS_ROOT/INNEROS_ENV.sh" <<'EOF'
export INNEROS_ROOT=/home/rlopez/inneros
export INNEROS_CORE=/home/rlopez/inneros/inneros_core
export INNEROS_PLATFORM=/home/rlopez/inneros/inneros_core/platform
export INNEROS_AGENTS_POOL=/home/rlopez/inneros/inneros_core/agents_pool
export INNEROS_COMPANIES=/home/rlopez/inneros/inneros_core/companies
export RAPHIIA_ROOT="$INNEROS_PLATFORM"
export PYTHONPATH="$INNEROS_PLATFORM:${PYTHONPATH:-}"
EOF

log "=== 4. Symlink raphiia-openai ==="
BAK=$(ls -d /home/rlopez/projects/raphiia-openai.bak.* 2>/dev/null | tail -1 || true)
if [[ -d "$OLD" && ! -L "$OLD" ]]; then
  [[ -f "$OLD/.env" && ! -f "$PLATFORM/.env" ]] && cp -a "$OLD/.env" "$PLATFORM/.env"
  [[ -d "$OLD/data" && ! -d "$PLATFORM/data" ]] && cp -a "$OLD/data" "$PLATFORM/data" 2>/dev/null || true
  mv "$OLD" "/home/rlopez/projects/raphiia-openai.pre-inneros.$(date +%s)"
fi
ln -sfn "$PLATFORM" "$OLD"

log "=== 5. venv ==="
if [[ -n "${BAK:-}" && -d "$BAK/venv" ]]; then
  rm -f "$PLATFORM/venv"
  ln -sfn "$BAK/venv" "$PLATFORM/venv"
fi

log "=== 6. agents_pool compat ==="
if [[ -d /home/rlopez/inneros_core && ! -L /home/rlopez/inneros_core ]]; then
  mv /home/rlopez/inneros_core "/home/rlopez/inneros_core.bak.$(date +%s)"
fi
ln -sfn "$CORE/agents_pool" /home/rlopez/inneros_core

mkdir -p /home/rlopez/data/tenants/{pcdoctor,innerchispa,template}

log "=== 7. Reiniciar servicios ==="
systemctl --user daemon-reload
systemctl --user restart ralfia-mcp ralfia-app ralfia-portal ralfia-voice-gateway 2>/dev/null || \
  systemctl --user restart ralfia-mcp ralfia-app ralfia-portal
sleep 6

log "=== 8. Health ==="
for url in "http://127.0.0.1:8102/health" "http://127.0.0.1:8101/status" "http://127.0.0.1:2002/"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 4 "$url" 2>/dev/null || echo "000")
  echo "$url → HTTP $code"
done
systemctl --user is-active ralfia-mcp ralfia-app ralfia-portal
ls -la "$OLD" "$CORE/agents_pool" | head -4
log "DONE Intel"
