#!/usr/bin/env bash
# Notificaciones cada 5 min — Evolution + email IMAP (Swarm)
set -euo pipefail
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
exec python scripts/ralfia_notify.py >> /tmp/ralfia-notify.log 2>&1
