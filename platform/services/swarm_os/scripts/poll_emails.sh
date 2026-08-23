#!/usr/bin/env bash
# Revisa correos IMAP y envía alertas WhatsApp — cron cada 5 min:
# */5 * * * * /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/poll_emails.sh >> /tmp/ralphi-email-poll.log 2>&1
set -euo pipefail
API="${RALPHI_API_URL:-http://127.0.0.1:8100/api/v1}"
curl -sf -X POST "${API}/email/poll" | head -c 2000
echo
