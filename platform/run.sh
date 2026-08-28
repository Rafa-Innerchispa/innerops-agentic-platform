#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f venv/bin/activate ]] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
export RAPHI_IA_OPENAI_PORT="${RAPHI_IA_OPENAI_PORT:-8101}"
exec python3 main.py
