#!/usr/bin/env bash
# Instala timer AG-37 Disk Steward (user systemd)
set -euo pipefail
USER_SYSTEMD="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SCRIPT="$HOME/inneros/inneros_core/scripts/ag37_disk_steward.sh"
chmod +x "$SCRIPT"
mkdir -p "$USER_SYSTEMD"

cat > "$USER_SYSTEMD/ralfia-disk-steward.service" <<EOF
[Unit]
Description=AG-37 Disk Steward (multi-disk inventory + WhatsApp approval)
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-$HOME/inneros/INNEROS_ENV.sh
Environment=DISK_CRITICAL_FREE_PCT=20
Environment=DISK_WARN_FREE_PCT=30
ExecStart=$SCRIPT
EOF

cat > "$USER_SYSTEMD/ralfia-disk-steward.timer" <<EOF
[Unit]
Description=AG-37 Disk Steward timer (every 30 min)

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ralfia-disk-steward.timer
systemctl --user list-timers ralfia-disk-steward.timer --no-pager
echo "AG-37 Disk Steward instalado."
