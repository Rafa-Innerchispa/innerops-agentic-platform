#!/usr/bin/env bash
# AG-25 — arrancar daemon de coordinación (foreground)
set -euo pipefail
cd /home/rlopez/data/ai_coordination
export COORD_DAEMON_INTERVAL="${COORD_DAEMON_INTERVAL:-120}"
export COORD_OLLAMA_ROUTER="${COORD_OLLAMA_ROUTER:-0}"
source /home/rlopez/projects/raphiia-openai/venv/bin/activate
exec python3 scripts/coordination_daemon.py
