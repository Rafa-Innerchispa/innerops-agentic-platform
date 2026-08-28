#!/usr/bin/env bash
# TURBO: PST paralelo Intel + VKR GPU AMD (sin cloud)
set -euo pipefail

PLATFORM="/home/rlopez/inneros/inneros_core/platform"
PY="${PLATFORM}/venv/bin/python3"
FLEET="${PLATFORM}/scripts/run_local_ingest_fleet.py"
LOG_DIR="/home/rlopez/data/logs"
INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
MONGO="mongodb://192.168.1.4:27017/"

stop_all() {
  ssh -o BatchMode=yes "rlopez@${INTEL}" 'for f in '"${LOG_DIR}"'/local_ingest_pst_*.pid '"${LOG_DIR}"'/local_ingest_fleet.pid; do
    [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null || true
  done' || true
  for f in "${LOG_DIR}"/local_ingest_vkr_*.pid; do
    [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null || true
  done
}

start_turbo() {
  mkdir -p "$LOG_DIR"
  scp -q "${PLATFORM}/raphiia_openai/ingest_pipeline.py" "rlopez@${INTEL}:${PLATFORM}/raphiia_openai/"
  scp -q "$FLEET" "rlopez@${INTEL}:${PLATFORM}/scripts/"

  stop_all
  sleep 1

  # Intel: 3 workers PST en paralelo (readpst + import threads)
  for i in 0 1 2; do
    ssh -o BatchMode=yes "rlopez@${INTEL}" "bash -s" <<REMOTE
set -euo pipefail
export PYTHONPATH=${PLATFORM}
export MONGO_URI_PRIMARY=${MONGO}
export PST_IMPORT_WORKERS=8
cd ${PLATFORM}
nohup ${PY} ${FLEET} --pst-only --worker-id pst-${i} --pst-per-cycle 1 --max-cycles 1000 --sleep 0 \\
  >> ${LOG_DIR}/local_ingest_pst_${i}.out 2>&1 &
echo \$! > ${LOG_DIR}/local_ingest_pst_${i}.pid
echo "Intel PST worker ${i} PID=\$(cat ${LOG_DIR}/local_ingest_pst_${i}.pid)"
REMOTE
  done

  # AMD: 2 workers VKR en GPU (14B x2 caben en 32GB VRAM)
  export PYTHONPATH="$PLATFORM"
  export MONGO_URI_PRIMARY="$MONGO"
  export OLLAMA_URL="http://127.0.0.1:11434"
  export MEMORY_CURATOR_MODEL="qwen2.5:14b-instruct-q4_K_M"
  for i in 0 1; do
    export INGEST_WORKER_ID="vkr-${i}"
    export INGEST_WORKER_SHARD="$i"
    export INGEST_WORKER_SHARDS="2"
    nohup "$PY" "$FLEET" --vkr-only --email-limit 80 --max-cycles 5000 --sleep 0 \
      >> "${LOG_DIR}/local_ingest_vkr_${i}.out" 2>&1 &
    echo $! > "${LOG_DIR}/local_ingest_vkr_${i}.pid"
    echo "AMD VKR worker ${i} PID=$(cat "${LOG_DIR}/local_ingest_vkr_${i}.pid")"
  done

  echo ""
  echo "TURBO activo. GPU AMD debería subir en ~30s cuando arranque Ollama 14B."
}

status_turbo() {
  echo "=== Intel PST workers ==="
  ssh -o BatchMode=yes "rlopez@${INTEL}" 'for i in 0 1 2; do
    f='"${LOG_DIR}"'/local_ingest_pst_${i}.pid
    if [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; then echo "  pst-$i: RUNNING pid=$(cat "$f")"; else echo "  pst-$i: stopped"; fi
  done
  pgrep -af readpst | head -3 || echo "  (sin readpst activo ahora)"'
  echo "=== AMD VKR workers ==="
  for i in 0 1; do
    f="${LOG_DIR}/local_ingest_vkr_${i}.pid"
    if [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; then
      echo "  vkr-$i: RUNNING pid=$(cat "$f")"
    else
      echo "  vkr-$i: stopped"
    fi
  done
  rocm-smi --showuse 2>/dev/null | grep "GPU use" || true
  curl -s http://127.0.0.1:11434/api/ps 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for m in d.get('models',[]):
  print('  ollama:', m.get('name'), 'vram', round((m.get('size_vram') or 0)/1e9,1),'GB')
" 2>/dev/null || true
  "$PY" - <<'PY'
import os, sys
sys.path.insert(0, os.environ.get("PLATFORM", "/home/rlopez/inneros/inneros_core/platform"))
from raphiia_openai import ingest_pipeline, mongo_store
db = mongo_store.get_db()
cp = db.ingest_pipeline_checkpoint.find_one({"_id": "pst"}) or {}
print("PST", len(cp.get("pst_hashes") or []), "/22 | correos pst", db.email_messages.count_documents({"source":"pst_import"}))
print("VKR pending", ingest_pipeline.count_vkr_pending())
print("VKR canonical", db.ralfia_memory_records.count_documents({"verification_status":"canonical"}))
PY
}

case "${1:-start}" in
  start) start_turbo ;;
  stop) stop_all ;;
  status) status_turbo ;;
  *) echo "Usage: $0 {start|stop|status}"; exit 1 ;;
esac
