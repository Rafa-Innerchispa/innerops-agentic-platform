#!/usr/bin/env bash
# Instala units canónicas en ~/.config/systemd/user (Intel/AMD) incl. temporal-worker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST"
for u in inneros-temporal-worker.service inneros-telegram-ops-poll.service; do
  src="$ROOT/systemd/user/$u"
  [[ -f "$src" ]] || continue
  install -m 0644 "$src" "$DEST/$u"
  echo "installed $DEST/$u"
done
systemctl --user daemon-reload
systemctl --user enable inneros-temporal-worker.service 2>/dev/null || true
systemctl --user enable inneros-telegram-ops-poll.service 2>/dev/null || true
echo "OK ensure_systemd_user_units"
