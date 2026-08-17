#!/usr/bin/env bash
# Flota Memory Curator — AMD Drive (4 workers) + Intel Notion (2 workers)
set -euo pipefail

PLATFORM="/home/rlopez/inneros/inneros_core/platform"
PY="$PLATFORM/venv/bin/python3"
CLI="$PLATFORM/scripts/run_memory_curator.py"
export PYTHONPATH="$PLATFORM"
export MONGO_URI_PRIMARY="${MONGO_URI_PRIMARY:-mongodb://192.168.1.4:27017/}"
export MEMORY_CURATOR_STRICT=1
export MEMORY_CURATOR_PRIORITY_ROOTS="/home/rlopez/data/google_drive/PC-Doctor- Historico/Clientes|/home/rlopez/data/notion_export|/home/rlopez/data/google_drive"
export MEMORY_CURATOR_INTERVAL="${MEMORY_CURATOR_INTERVAL:-3}"
export MEMORY_CURATOR_BATCH_SIZE="${MEMORY_CURATOR_BATCH_SIZE:-3}"

CMD="${1:-start}"

start_amd() {
  systemctl --user stop ralfia-memory-curator.service 2>/dev/null || true
  for i in 0 1 2 3; do
    systemctl --user enable "ralfia-memory-curator@${i}.service" 2>/dev/null || true
    systemctl --user restart "ralfia-memory-curator@${i}.service"
  done
  echo "AMD: 4 workers Drive activos"
}

start_intel() {
  ssh -o BatchMode=yes rlopez@192.168.1.4 "bash -s" <<'REMOTE'
set -euo pipefail
PLATFORM="/home/rlopez/inneros/inneros_core/platform"
export PYTHONPATH="$PLATFORM"
export MONGO_URI_PRIMARY="mongodb://192.168.1.4:27017/"
export MEMORY_CURATOR_MODEL="qwen2.5:7b"
export MEMORY_CURATOR_INTERVAL=3
export MEMORY_CURATOR_BATCH_SIZE=3
for i in 0 1; do
  systemctl --user enable "ralfia-memory-curator-notion@${i}.service" 2>/dev/null || true
  systemctl --user restart "ralfia-memory-curator-notion@${i}.service"
done
echo "Intel: 2 workers Notion activos"
REMOTE
}

stop_all() {
  for i in 0 1 2 3; do systemctl --user stop "ralfia-memory-curator@${i}.service" 2>/dev/null || true; done
  systemctl --user stop ralfia-memory-curator.service 2>/dev/null || true
  ssh -o BatchMode=yes rlopez@192.168.1.4 'for i in 0 1; do systemctl --user stop ralfia-memory-curator-notion@${i}.service 2>/dev/null || true; done' || true
}

status_all() {
  echo "=== AMD Drive workers ==="
  for i in 0 1 2 3; do systemctl --user is-active "ralfia-memory-curator@${i}.service" 2>/dev/null && echo "  @${i}: active" || echo "  @${i}: inactive"; done
  echo "=== Intel Notion workers ==="
  ssh -o BatchMode=yes rlopez@192.168.1.4 'for i in 0 1; do systemctl --user is-active ralfia-memory-curator-notion@${i}.service 2>/dev/null && echo "  notion@${i}: active" || echo "  notion@${i}: inactive"; done'
  echo "=== Fleet aggregate ==="
  "$PY" "$CLI" --fleet-status
}

test_system() {
  "$PY" "$CLI" --system-test
}

case "$CMD" in
  start)
    start_amd
    start_intel
    sleep 2
    status_all
    ;;
  stop) stop_all ;;
  status) status_all ;;
  test) test_system ;;
  *) echo "Usage: $0 {start|stop|status|test}"; exit 1 ;;
esac
