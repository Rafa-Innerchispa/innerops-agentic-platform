#!/usr/bin/env bash
# Flota ingesta local — PST en Intel (readpst) + VKR Ollama local
set -euo pipefail

PLATFORM="/home/rlopez/inneros/inneros_core/platform"
PY="${PLATFORM}/venv/bin/python3"
FLEET="$PLATFORM/scripts/run_local_ingest_fleet.py"
LOG_DIR="/home/rlopez/data/logs"
PID_FILE="$LOG_DIR/local_ingest_fleet.pid"
OUT_LOG="$LOG_DIR/local_ingest_fleet.out"
INTEL="${RALFIA_INTEL_HOST:-192.168.1.4}"
CMD="${1:-start}"

export PYTHONPATH="$PLATFORM"
export MONGO_URI_PRIMARY="${MONGO_URI_PRIMARY:-mongodb://192.168.1.4:27017/}"
export MEMORY_CURATOR_MODEL="${MEMORY_CURATOR_MODEL:-qwen2.5:7b}"

_run_intel() {
  ssh -o BatchMode=yes "rlopez@${INTEL}" "bash -s" <<REMOTE
set -euo pipefail
mkdir -p "$LOG_DIR"
export PYTHONPATH="$PLATFORM"
export MONGO_URI_PRIMARY="$MONGO_URI_PRIMARY"
export MEMORY_CURATOR_MODEL="$MEMORY_CURATOR_MODEL"
cd "$PLATFORM"
nohup $PY "$FLEET" --email-limit 75 --chatgpt-limit 0 --max-cycles 500 --sleep 8 \\
  >> "$OUT_LOG" 2>&1 &
echo \$! > "$PID_FILE"
echo "Intel ingest fleet PID=\$(cat $PID_FILE)"
REMOTE
}

_run_local() {
  mkdir -p "$LOG_DIR"
  cd "$PLATFORM"
  nohup "$PY" "$FLEET" --email-limit 75 --chatgpt-limit 0 --max-cycles 500 --sleep 8 \
    >> "$OUT_LOG" 2>&1 &
  echo $! > "$PID_FILE"
  echo "Local ingest fleet PID=$(cat "$PID_FILE")"
}

_status() {
  ssh -o BatchMode=yes "rlopez@${INTEL}" "bash -s" <<'REMOTE' 2>/dev/null || true
PID_FILE="/home/rlopez/data/logs/local_ingest_fleet.pid"
OUT_LOG="/home/rlopez/data/logs/local_ingest_fleet.out"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Intel fleet: RUNNING pid=$(cat "$PID_FILE")"
else
  echo "Intel fleet: stopped"
fi
tail -n 5 "$OUT_LOG" 2>/dev/null || true
REMOTE
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "AMD fleet: RUNNING pid=$(cat "$PID_FILE")"
  else
    echo "AMD fleet: stopped"
  fi
}

_stop() {
  ssh -o BatchMode=yes "rlopez@${INTEL}" '[[ -f /home/rlopez/data/logs/local_ingest_fleet.pid ]] && kill $(cat /home/rlopez/data/logs/local_ingest_fleet.pid) 2>/dev/null || true' || true
  [[ -f "$PID_FILE" ]] && kill "$(cat "$PID_FILE")" 2>/dev/null || true
}

case "$CMD" in
  start-intel) _run_intel ;;
  start-local) _run_local ;;
  start)
    rsync -az --delete \
      "$PLATFORM/raphiia_openai/ingest_pipeline.py" \
      "$PLATFORM/scripts/run_local_ingest_fleet.py" \
      "$PLATFORM/scripts/run_local_ingest_fleet.sh" \
      "rlopez@${INTEL}:${PLATFORM}/" 2>/dev/null || true
    rsync -az "$PLATFORM/raphiia_openai/ingest_pipeline.py" "rlopez@${INTEL}:${PLATFORM}/raphiia_openai/" 2>/dev/null || true
    rsync -az "$PLATFORM/scripts/" "rlopez@${INTEL}:${PLATFORM}/scripts/" 2>/dev/null || true
    _run_intel
    ;;
  stop) _stop ;;
  status) _status ;;
  *) echo "Usage: $0 {start|start-intel|start-local|stop|status}"; exit 1 ;;
esac
