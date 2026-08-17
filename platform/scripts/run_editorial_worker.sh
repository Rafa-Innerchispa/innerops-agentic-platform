#!/usr/bin/env bash
set -euo pipefail
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
exec python3 scripts/editorial_worker.py
