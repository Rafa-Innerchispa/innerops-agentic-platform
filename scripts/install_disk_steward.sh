#!/usr/bin/env bash
# Instala timer AG-37 Disk Steward (user systemd)
set -euo pipefail
USER_SYSTEMD="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SCRIPT="$HOME/inneros/inneros_core/scripts/ag37_disk_steward.sh"
chmod +x "$SCRIPT"
mkdir -p "$USER_SYSTEMD"

ROOT_FS="$(findmnt -no SOURCE -T / 2>/dev/null || true)"
ARCHIVE_BASE=""
for candidate in "$HOME/data" /mnt/datos_agentes /srv/backups; do
  if [ -d "$candidate" ]; then
    candidate_fs="$(findmnt -no SOURCE -T "$candidate" 2>/dev/null || true)"
    if [ -n "$candidate_fs" ] && [ "$candidate_fs" != "$ROOT_FS" ]; then
      ARCHIVE_BASE="$candidate"
      break
    fi
  fi
done
if [ -z "$ARCHIVE_BASE" ]; then
  ARCHIVE_BASE="$HOME/data"
fi

HOST_NAME="$(hostname | tr '[:upper:]' '[:lower:]')"
RALFIA_NODE_VALUE="primary"
case "$HOST_NAME" in
  *amd*|*'.5'*)
    RALFIA_NODE_VALUE="amd"
    ;;
esac

mkdir -p "$ARCHIVE_BASE/backups/off-root" "$ARCHIVE_BASE/backups/disk_steward/archive"

cat > "$USER_SYSTEMD/ralfia-disk-steward.service" <<EOF
[Unit]
Description=AG-37 Disk Steward (multi-disk inventory + WhatsApp approval)
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-$HOME/inneros/INNEROS_ENV.sh
Environment=DISK_CRITICAL_FREE_PCT=20
Environment=DISK_WARN_FREE_PCT=30
Environment=DISK_ARCHIVE_BASE=$ARCHIVE_BASE
Environment=DISK_ARCHIVE_ROOT=$ARCHIVE_BASE/backups/disk_steward/archive
Environment=DISK_MIGRATION_ROOT=$ARCHIVE_BASE/backups/off-root
Environment=DISK_ALLOWED_DEST_ROOTS=$ARCHIVE_BASE/backups,$ARCHIVE_BASE/archive,/home/rlopez/data/backups,/home/rlopez/data/archive,/mnt/datos_agentes/backups
Environment=RALFIA_NODE=$RALFIA_NODE_VALUE
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
echo "AG-37 Disk Steward instalado. archive_base=$ARCHIVE_BASE node=$RALFIA_NODE_VALUE"
