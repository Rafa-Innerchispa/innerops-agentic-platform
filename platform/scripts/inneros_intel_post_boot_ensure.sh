#!/usr/bin/env bash
# Intel post-boot: ensure MCP env + mark degradation snapshot after Mongo is up.
set -euo pipefail
PLATFORM="${INNEROS_PLATFORM_ROOT:-/home/rlopez/inneros/inneros_core/platform}"
ENV_FILE="${PLATFORM}/.env"
TEMPLATE="${PLATFORM}/.env.ops-notify.example"
if [[ ! -f "$ENV_FILE" && -f "$TEMPLATE" ]]; then
  cp "$TEMPLATE" "$ENV_FILE"
  echo "POST_BOOT: created .env from template"
fi
export PYTHONPATH="${PLATFORM}:${PYTHONPATH:-}"
cd "$PLATFORM"
python3 - <<'PY'
from inneros_core_runtime import ops_peer_degradation as opd

print(opd.degradation_snapshot())
PY