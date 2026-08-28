#!/usr/bin/env bash
# Instala timer de notificaciones WhatsApp (Evolution) en nodos RalfIA secundarios.
set -euo pipefail
SRC="${RALFIA_NOTIFY_SRC:-/home/rlopez/projects/raphiia-openai}"
DEST="${HOME}/.config/systemd/user"
COORD="/home/rlopez/data/ai_coordination/systemd/user"
mkdir -p "$DEST"

install_unit() {
  local name="$1"
  if [[ -f "$COORD/$name" ]]; then
    cp "$COORD/$name" "$DEST/"
  elif [[ -f "$HOME/.config/systemd/user/$name" ]]; then
    cp "$HOME/.config/systemd/user/$name" "$DEST/"
  fi
}

install_unit ralfia-notify.service
install_unit ralfia-notify.timer

if [[ ! -f "$DEST/ralfia-notify.service" ]]; then
  cat >"$DEST/ralfia-notify.service" <<'UNIT'
[Unit]
Description=RalfIA notifications (Evolution WhatsApp + email poll)
After=network.target

[Service]
Type=oneshot
ExecStart=/home/rlopez/projects/raphiia-openai/scripts/ralfia_notify.sh

[Install]
WantedBy=default.target
UNIT
fi

if [[ ! -f "$DEST/ralfia-notify.timer" ]]; then
  cat >"$DEST/ralfia-notify.timer" <<'UNIT'
[Unit]
Description=RalfIA notifications every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
fi

systemctl --user daemon-reload
systemctl --user enable --now ralfia-notify.timer
systemctl --user list-timers ralfia-notify.timer --no-pager
echo "OK ralfia-notify.timer en $(hostname)"
