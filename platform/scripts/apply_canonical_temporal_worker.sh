#!/usr/bin/env bash
# Fija inneros-temporal-worker a inneros_core/platform (canonical), no p0-*-release.
set -euo pipefail
PLATFORM="${INNEROS_PLATFORM_ROOT:-/home/rlopez/inneros/inneros_core/platform}"
DROPIN_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/inneros-temporal-worker.service.d"
mkdir -p "$DROPIN_DIR"
_host="$(hostname -s 2>/dev/null || hostname)"
_role="${INNEROS_NODE_ROLE:-}"
_is_intel=0
if [[ "$_role" == "intel" ]] || [[ "$_host" == *intel* ]] || [[ "$_host" == *ver-10* ]]; then
  _is_intel=1
fi
if [[ "$_role" == "amd" ]] || [[ "$_host" == *amd* ]]; then
  _is_intel=0
fi
if [[ "$_is_intel" == 1 ]]; then
  QUEUES="${TEMPORAL_WORKER_QUEUES:-inneros-general-ops,inneros-intel-ops}"
else
  QUEUES="${TEMPORAL_WORKER_QUEUES:-inneros-general-ops,inneros-amd-gpu-ops}"
fi
cat >"$DROPIN_DIR/canonical-platform.conf" <<EOF
[Service]
WorkingDirectory=$PLATFORM
Environment=PYTHONPATH=$PLATFORM
ExecStart=
ExecStart=$PLATFORM/venv/bin/python3 -m inneros_core_runtime.temporal_worker --queues $QUEUES
EOF
# Desactiva override legacy p0-release si existe (canonical gana por orden alfabético: c > p)
if [[ -f "$DROPIN_DIR/p0-release-c8042acc.conf" ]]; then
  mv "$DROPIN_DIR/p0-release-c8042acc.conf" "$DROPIN_DIR/p0-release-c8042acc.conf.disabled"
fi
systemctl --user daemon-reload
systemctl --user restart inneros-temporal-worker.service
systemctl --user is-active inneros-temporal-worker.service
echo "OK canonical temporal worker → $PLATFORM queues=$QUEUES"
