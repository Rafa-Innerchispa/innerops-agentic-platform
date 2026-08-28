#!/usr/bin/env bash
# Sincronización final Contífico → Mongo (ejecutar ANTES de cancelar la suscripción).
# Tarda ~1–3 h por throttling de la API. Reanuda documentos ya importados (resume=true).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source venv/bin/activate
LOG="/tmp/contifico-final-sync-$(date +%Y%m%d_%H%M%S).log"
echo "[$(date -Iseconds)] Inicio sync Contífico → $LOG"

python - <<'PY' | tee -a "$LOG"
from raphiia_openai import contifico_bridge, contifico_normalize, contifico_ledger, mongo_store

print("=== 1/4 Estado previo ===")
st = contifico_bridge.get_contifico_sync_status()
db = mongo_store.get_db()
print("Mongo docs:", db.contifico_documents.count_documents({}))
print("Última sync:", st.get("updated_at"), "status:", st.get("status"))

print("\n=== 2/4 Import API (resume) ===")
imp = contifico_bridge.import_contifico_full_sync(dry_run=False, resume=True)
print("import ok:", imp.get("ok"), "nuevos docs:", imp.get("documents_imported_this_run"))

print("\n=== 3/4 Normalizar personas + ledger ===")
norm = contifico_normalize.normalize_contifico_all(fetch_personas_api=True, link_crm=False, normalize_ledger=True)
print("normalize ok:", norm.get("ok"))

print("\n=== 4/4 Resumen final ===")
inv = contifico_ledger.ledger_inventory_summary()
print(inv)
print("sync status:", contifico_bridge.get_contifico_sync_status())
PY

echo "[$(date -Iseconds)] Fin sync — log: $LOG"
