#!/usr/bin/env bash
# Start Cursor My Machines worker (InnerOS). Sourced by systemd or run manually.
set -euo pipefail

NAME="${CURSOR_WORKER_NAME:-inneros-intel-4}"
DIRS="${CURSOR_WORKER_DIRS:-$HOME/innerops-agentic-platform}"

if ! command -v agent >/dev/null 2>&1; then
  echo "cursor agent CLI missing; run setup_cursor_my_machine_worker.sh" >&2
  exit 127
fi

ARGS=(worker start --name "$NAME")
IFS=':' read -ra PARTS <<< "$DIRS"
for d in "${PARTS[@]}"; do
  d="${d// /}"
  [[ -d "$d" ]] && ARGS+=(--worker-dir "$d")
done

exec agent "${ARGS[@]}"