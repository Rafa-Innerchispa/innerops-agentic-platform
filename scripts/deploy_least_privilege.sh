#!/usr/bin/env bash
# deploy_least_privilege.sh — Setup least-privilege IAM, Model Armor, and audit Y->Z->R deployment.
set -euo pipefail

PROJECT_ID="innerops-agentic-platform"
REGION="us-central1"
SA_NAME="inneros-runtime"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
TEMPLATE_NAME="inneros-default"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== 1. Habilitando APIs de Google Cloud ==="
gcloud services enable \
  modelarmor.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  --project="$PROJECT_ID"

log "=== 2. Creando Service Account de Mínimo Privilegio ==="
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" \
    --description="Dedicated runtime identity for governed InnerOS/ARIA agents" \
    --display-name="InnerOS Governed Runtime" \
    --project="$PROJECT_ID"
  log "Service Account creada: $SA_EMAIL"
else
  log "Service Account ya existe: $SA_EMAIL"
fi

log "=== 3. Asignando Roles IAM a la Cuenta de Servicio ==="
ROLES=(
  "roles/datastore.user"
  "roles/pubsub.publisher"
  "roles/pubsub.viewer"
  "roles/aiplatform.user"
  "roles/logging.logWriter"
)
for role in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$role" \
    --quiet \
    &>/dev/null
  log "Rol asignado: $role"
done

log "=== 4. Creando Plantilla por Defecto en Model Armor ==="
if ! gcloud alpha model-armor templates describe "$TEMPLATE_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  gcloud alpha model-armor templates create "$TEMPLATE_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --user-prompt-filter-settings="piAndJailbreakFilterSettings={filterState=ENABLED}" \
    --model-response-filter-settings="piAndJailbreakFilterSettings={filterState=ENABLED}" \
    --quiet || log "Advertencia: Falló la creación de la plantilla de Model Armor (puede requerir configuración manual)."
else
  log "Plantilla de Model Armor ya existe: $TEMPLATE_NAME"
fi

log "=== 5. Actualizando Cloud Run Service 'inneros' ==="
gcloud run services update inneros \
  --service-account="$SA_EMAIL" \
  --set-env-vars="INNEROS_MODEL_ARMOR_TEMPLATE=$TEMPLATE_NAME,INNEROS_MODEL_ARMOR_LOCATION=$REGION" \
  --region="$REGION" \
  --project="$PROJECT_ID"

log "=== 6. Obteniendo Trazabilidad de Despliegue (Y -> Z -> R) ==="
COMMIT_SHA=$(git rev-parse HEAD)
REVISION_NAME=$(gcloud run services describe inneros --region="$REGION" --project="$PROJECT_ID" --format="value(status.latestReadyRevisionName)")
IMAGE_DIGEST=$(gcloud run services describe inneros --region="$REGION" --project="$PROJECT_ID" --format="value(spec.template.spec.containers[0].image)")

log "Commit SHA (Y): $COMMIT_SHA"
log "Cloud Run Revision (R): $REVISION_NAME"
log "Image Digest (Z): $IMAGE_DIGEST"

log "=== 7. Registrando Evidencia de Despliegue en Firestore ==="
PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python3 -c "
from google.cloud import firestore
from inneros_core_runtime.gemini_runtime import _get_google_credentials

credentials, project = _get_google_credentials()
db = firestore.Client(project=project, credentials=credentials)
db.collection('deployments_audit').add({
    'commit_sha': '$COMMIT_SHA',
    'image_digest': '$IMAGE_DIGEST',
    'cloud_run_revision': '$REVISION_NAME',
    'timestamp': firestore.SERVER_TIMESTAMP,
    'deployed_by': 'antigravity-reconciler',
    'status': 'success'
})
"

log "=== DESPLIEGUE FINALIZADO Y TRAZABILIDAD REGISTRADA ==="
