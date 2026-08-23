#!/usr/bin/env bash
# InnerOS — Migración completa a /home/rlopez/inneros/inneros_core/
# Ejecutar: bash /home/rlopez/inneros/inneros_core/scripts/migrate_to_inneros_root.sh
set -euo pipefail

INNEROS_ROOT="/home/rlopez/inneros"
CORE="$INNEROS_ROOT/inneros_core"
LEGACY_AGENTS="/home/rlopez/inneros_core/agents_pool"
LEGACY_PLATFORM="/home/rlopez/projects/raphiia-openai"
LEGACY_RALFI_PLATFORM="/home/rlopez/projects/ralfi-ia-platform"
DATA_TENANTS="/home/rlopez/data/tenants"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== 1. Estructura inneros_core ==="
mkdir -p "$CORE"/{agents_pool,platform,companies,tenants,services,infra/systemd,modules,docs,scripts}
mkdir -p "$DATA_TENANTS"/{pcdoctor,innerchispa,template}

log "=== 2. agents_pool ==="
if [[ -d "$LEGACY_AGENTS" && ! -L "$LEGACY_AGENTS" ]]; then
  if [[ ! -d "$CORE/agents_pool/AG-01_network_router" ]]; then
    rsync -a "$LEGACY_AGENTS/" "$CORE/agents_pool/"
    log "agents_pool copiado desde ~/inneros_core/agents_pool"
  fi
fi
# Compat: ~/inneros_core -> agents_pool (ruta histórica)
if [[ -d /home/rlopez/inneros_core && ! -L /home/rlopez/inneros_core ]]; then
  rm -rf /home/rlopez/inneros_core/agents_pool 2>/dev/null || true
  rmdir /home/rlopez/inneros_core 2>/dev/null || mv /home/rlopez/inneros_core "/home/rlopez/inneros_core.bak.$(date +%s)" 2>/dev/null || true
fi
ln -sfn "$CORE/agents_pool" /home/rlopez/inneros_core

log "=== 3. platform (raphiia-openai) ==="
if [[ -d "$LEGACY_PLATFORM" && ! -L "$LEGACY_PLATFORM" ]]; then
  rsync -a \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '.git/' \
    --exclude 'backups/' \
    "$LEGACY_PLATFORM/" "$CORE/platform/"
  log "platform sincronizado desde raphiia-openai"
  # venv: symlink al existente si hay
  if [[ -d "$LEGACY_PLATFORM/venv" && ! -e "$CORE/platform/venv" ]]; then
    ln -sfn "$LEGACY_PLATFORM/venv" "$CORE/platform/venv"
  fi
  # .env
  if [[ -f "$LEGACY_PLATFORM/.env" && ! -f "$CORE/platform/.env" ]]; then
    cp -a "$LEGACY_PLATFORM/.env" "$CORE/platform/.env"
  fi
fi

log "=== 4. companies (multi-tenant) ==="
if [[ -d "$LEGACY_RALFI_PLATFORM/companies" ]]; then
  rsync -a "$LEGACY_RALFI_PLATFORM/companies/" "$CORE/companies/"
fi

log "=== 5. docs nomenclatura ==="
if [[ -d "$LEGACY_RALFI_PLATFORM/docs" ]]; then
  rsync -a "$LEGACY_RALFI_PLATFORM/docs/" "$CORE/docs/"
fi

log "=== 6. módulos satélite (symlinks) ==="
ln -sfn /home/rlopez/projects/ralphiia-quoteops "$CORE/modules/quoteops" 2>/dev/null || true
ln -sfn /home/rlopez/projects/innerspark-smart-quoter "$CORE/modules/smart-quoter" 2>/dev/null || true

log "=== 7. Symlinks legacy projects/ ==="
ln -sfn "$CORE/platform" /home/rlopez/projects/raphiia-openai 2>/dev/null || true
if [[ -d /home/rlopez/projects/raphiia-openai && ! -L /home/rlopez/projects/raphiia-openai ]]; then
  mv /home/rlopez/projects/raphiia-openai "/home/rlopez/projects/raphiia-openai.bak.$(date +%s)"
  ln -sfn "$CORE/platform" /home/rlopez/projects/raphiia-openai
fi
ln -sfn "$CORE" /home/rlopez/projects/ralfi-ia-platform 2>/dev/null || true

log "=== 8. tenants metadata ==="
for t in pcdoctor innerchispa; do
  [[ -f "$CORE/tenants/$t/tenant.yaml" ]] && continue
  mkdir -p "$CORE/tenants/$t"
done

log "=== DONE ==="
echo "INNEROS_ROOT=$INNEROS_ROOT"
echo "INNEROS_CORE=$CORE"
echo "INNEROS_PLATFORM=$CORE/platform"
echo "INNEROS_AGENTS_POOL=$CORE/agents_pool"
ls -la "$INNEROS_ROOT"
ls -la "$CORE"
