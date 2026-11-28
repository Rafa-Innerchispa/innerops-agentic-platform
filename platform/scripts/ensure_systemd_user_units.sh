#!/usr/bin/env bash
# Instala units canónicas en ~/.config/systemd/user (Intel/AMD) incl. temporal-worker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST"
for u in \
  inneros-temporal-worker.service \
  inneros-telegram-ops-poll.service \
  inneros-ha-liveness.service \
  inneros-ha-liveness.timer \
  inneros-mongo-coordination-backup.service \
  inneros-mongo-coordination-backup.timer \
  inneros-mongo-full-backup.service \
  inneros-mongo-full-backup.timer \
  atlas-cloud-runtime-backup.service; do
  src="$ROOT/systemd/user/$u"
  [[ -f "$src" ]] || continue
  install -m 0644 "$src" "$DEST/$u"
  echo "installed $DEST/$u"
done
chmod +x "$ROOT/scripts/inneros_mongo_coordination_backup.sh" 2>/dev/null || true
chmod +x "$ROOT/scripts/atlas_cloud_runtime_backup.py" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable inneros-temporal-worker.service 2>/dev/null || true
systemctl --user enable inneros-telegram-ops-poll.service 2>/dev/null || true
systemctl --user enable --now inneros-ha-liveness.timer 2>/dev/null || true
systemctl --user enable --now inneros-mongo-coordination-backup.timer 2>/dev/null || true
systemctl --user enable --now inneros-mongo-full-backup.timer 2>/dev/null || true
echo "OK ensure_systemd_user_units"
