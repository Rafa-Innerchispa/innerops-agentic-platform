#!/usr/bin/env bash
# InnerOS — Clonar despliegue SIN datos PC Doctor
# Uso: bash clone_deployment.sh <nuevo_slug> <entity_id> [destino]
# Ejemplo: bash clone_deployment.sh acme-corp ent_acme /opt/inneros-acme
set -euo pipefail

SLUG="${1:?Usage: clone_deployment.sh <slug> <entity_id> [dest_dir]}"
ENTITY_ID="${2:?entity_id requerido}"
DEST="${3:-/home/rlopez/inneros/deployments/$SLUG}"
SRC="/home/rlopez/inneros/inneros_core"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "Clonando InnerOS core → $DEST (sin tenant pcdoctor)"

mkdir -p "$DEST"
rsync -a \
  --exclude 'tenants/pcdoctor/' \
  --exclude 'platform/.env' \
  --exclude 'platform/venv/' \
  --exclude 'platform/__pycache__/' \
  --exclude 'platform/backups/' \
  --exclude '.git/' \
  "$SRC/" "$DEST/"

# Nuevo tenant desde template
mkdir -p "$DEST/tenants/$SLUG"
cp "$SRC/tenants/template/tenant.yaml" "$DEST/tenants/$SLUG/tenant.yaml"
sed -i "s/TEMPLATE_SLUG/$SLUG/g; s/ent_TEMPLATE/$ENTITY_ID/g; s/enabled: false/enabled: true/" \
  "$DEST/tenants/$SLUG/tenant.yaml"

# Company config
mkdir -p "$DEST/companies/$SLUG/config"
if [[ -f "$SRC/companies/template/config/entity.yaml" ]]; then
  cp "$SRC/companies/template/config/entity.yaml" "$DEST/companies/$SLUG/config/entity.yaml"
  sed -i "s/ent_TEMPLATE/$ENTITY_ID/g; s/TEMPLATE COMPANY/$SLUG/g" \
    "$DEST/companies/$SLUG/config/entity.yaml"
fi

mkdir -p "/home/rlopez/data/tenants/$SLUG"

cat > "$DEST/INNEROS_ENV.sh" <<EOF
export INNEROS_ROOT="$(dirname "$DEST")"
export INNEROS_CORE="$DEST"
export INNEROS_PLATFORM="$DEST/platform"
export INNEROS_AGENTS_POOL="$DEST/agents_pool"
export INNEROS_TENANT=$SLUG
export INNEROS_ENTITY_ID=$ENTITY_ID
EOF

log "Listo: $DEST"
log "Activar: source $DEST/INNEROS_ENV.sh"
log "Datos: /home/rlopez/data/tenants/$SLUG"
log "Tenants incluidos: innerchispa (referencia), $SLUG (nuevo) — SIN pcdoctor"
