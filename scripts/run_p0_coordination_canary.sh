#!/usr/bin/env bash
set -euo pipefail

# Offline canary only. This script does not restart services, bind ports,
# connect to production databases, or deploy code.

if [[ "${INNEROS_P0_CANARY_ACK:-}" != "I_UNDERSTAND_NO_DEPLOY" ]]; then
  echo "REFUSED: set INNEROS_P0_CANARY_ACK=I_UNDERSTAND_NO_DEPLOY" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
HEAD_SHA="$(git rev-parse HEAD)"
if [[ "$BRANCH" != "repair/coordination-recovery-20260929" ]]; then
  echo "REFUSED: expected repair branch, got '$BRANCH'" >&2
  exit 3
fi

case "$ROOT" in
  /home/rlopez/inneros/inneros_core|/home/rlopez/inneros/inneros_core/*)
    echo "REFUSED: do not run the offline canary inside the production checkout" >&2
    exit 4
    ;;
esac

if [[ -n "$(git status --porcelain)" ]]; then
  echo "REFUSED: canary checkout must be clean" >&2
  exit 5
fi

VENV="$ROOT/.venv-p0-canary"
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --quiet \
  'pymongo>=4.6,<5' \
  'temporalio>=1.8,<2' \
  'nest-asyncio>=1.6,<2' \
  'pydantic>=2.5,<3' \
  'python-dotenv>=1,<2' \
  'fastmcp-slim[server]>=3,<4'

export PYTHONPATH="$ROOT/platform"

"$VENV/bin/python" platform/tests/test_coordination_recovery_p0.py -v
"$VENV/bin/python" -m py_compile \
  platform/inneros_core_runtime/mcp_diagnostics.py \
  platform/inneros_core_runtime/temporal_worker.py \
  platform/inneros_core_runtime/temporal_workflows.py \
  platform/inneros_core_runtime/temporal_activities.py \
  platform/inneros_core_runtime/durable_coordination_spine.py \
  platform/inneros_core_runtime/coordination_live.py \
  platform/inneros_core_runtime/memory/agent_messages.py \
  platform/inneros_core_runtime/mcp_server.py \
  platform/tests/test_coordination_recovery_p0.py
git diff --check

printf '%s\n' \
  "P0_CANARY=PASS" \
  "branch=$BRANCH" \
  "head=$HEAD_SHA" \
  "root=$ROOT" \
  "production_deploy=false" \
  "services_restarted=false"