#!/usr/bin/env bash
# Instala timer user: vigila gateway+ngrok cada 1 minuto y recupera solo.
set -euo pipefail
DEST="${HOME}/.config/systemd/user"
COORD="/home/rlopez/data/ai_coordination/systemd/user"
ROOT="/home/rlopez/projects/raphiia-openai"
mkdir -p "$DEST" "$COORD"
chmod +x "$ROOT/scripts/public_https_watchdog.sh" "$ROOT/scripts/public_https_watchdog.py"

for name in public-https-watchdog.service public-https-watchdog.timer; do
  :
done

cat >"$COORD/public-https-watchdog.service" <<'UNIT'
[Unit]
Description=RalfIA public HTTPS watchdog (gateway :5188 + ngrok)
After=network.target

[Service]
Type=oneshot
ExecStart=/home/rlopez/projects/raphiia-openai/scripts/public_https_watchdog.sh

[Install]
WantedBy=default.target
UNIT

cat >"$COORD/public-https-watchdog.timer" <<'UNIT'
[Unit]
Description=RalfIA public HTTPS watchdog every 1 minute

[Timer]
OnBootSec=45s
OnUnitActiveSec=1min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
UNIT

cp "$COORD/public-https-watchdog.service" "$DEST/"
cp "$COORD/public-https-watchdog.timer" "$DEST/"

systemctl --user daemon-reload
systemctl --user enable --now public-https-watchdog.timer
systemctl --user list-timers public-https-watchdog.timer --no-pager
echo "OK public-https-watchdog.timer — log: /tmp/public-https-watchdog.log"
