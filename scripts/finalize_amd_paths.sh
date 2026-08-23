#!/usr/bin/env bash
# AMD: unificar raphiia-openai → inneros platform + renombrar RAG legacy
set -euo pipefail

CORE="/home/rlopez/inneros/inneros_core"
PLATFORM="$CORE/platform"
OLD="/home/rlopez/projects/raphiia-openai"
RAG="/home/rlopez/projects/inneros"
RAG_NEW="/home/rlopez/projects/inneros-rag-legacy"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== 1. Renombrar repo RAG (no confundir con InnerOS producto) ==="
if [[ -d "$RAG/.git" && ! -e "$RAG_NEW" ]]; then
  mv "$RAG" "$RAG_NEW"
  log "inneros → inneros-rag-legacy"
fi

log "=== 2. Symlink raphiia-openai → platform ==="
if [[ -d "$OLD" && ! -L "$OLD" ]]; then
  # .env y data locales
  [[ -f "$OLD/.env" && ! -f "$PLATFORM/.env" ]] && cp -a "$OLD/.env" "$PLATFORM/.env"
  [[ -d "$OLD/data" && ! -d "$PLATFORM/data" ]] && cp -a "$OLD/data" "$PLATFORM/data"
  mv "$OLD" "/home/rlopez/projects/raphiia-openai.pre-inneros.$(date +%s)"
fi
ln -sfn "$PLATFORM" "$OLD"

log "=== 3. venv ==="
BAK=$(ls -d /home/rlopez/projects/raphiia-openai.bak.* 2>/dev/null | tail -1 || true)
if [[ -n "${BAK:-}" && -d "$BAK/venv" ]]; then
  rm -f "$PLATFORM/venv"
  ln -sfn "$BAK/venv" "$PLATFORM/venv"
fi

log "=== 4. Verificar servicios ==="
if systemctl --user is-active ralfia-mcp &>/dev/null; then
  systemctl --user restart ralfia-mcp ralfia-app ralfia-portal 2>/dev/null || true
  sleep 5
fi
for url in "http://127.0.0.1:8102/health" "http://127.0.0.1:8101/status"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$url" 2>/dev/null || echo "000")
  echo "$url → $code"
done
ls -la "$OLD" "$PLATFORM/venv/bin/python3" 2>/dev/null | head -3
log "DONE"
