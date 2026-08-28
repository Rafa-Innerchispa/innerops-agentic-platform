#!/usr/bin/env bash
# Watchdog HTTPS público (gateway :5188 + ngrok) — cada 1 min vía timer user
set -euo pipefail
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
exec python scripts/public_https_watchdog.py >> /tmp/public-https-watchdog.log 2>&1
