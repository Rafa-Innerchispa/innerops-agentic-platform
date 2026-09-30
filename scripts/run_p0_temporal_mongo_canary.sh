#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ACK="I_UNDERSTAND_ISOLATED_TEMPORAL_CANARY"
if [[ "${INNEROS_P0_TEMPORAL_CANARY_ACK:-}" != "${EXPECTED_ACK}" ]]; then
  echo "REFUSED: set INNEROS_P0_TEMPORAL_CANARY_ACK=${EXPECTED_ACK}" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

BRANCH="$(git branch --show-current)"
if [[ "${BRANCH}" != "repair/coordination-recovery-20260929" ]]; then
  echo "REFUSED: expected repair branch, got ${BRANCH}" >&2
  exit 3
fi

mkdir -p "${ROOT}/.canary/worktrees"

exec env \
  PYTHONPATH="${ROOT}/platform" \
  INNEROS_P0_TEMPORAL_CANARY_ACK="${EXPECTED_ACK}" \
  INNEROS_TEMPORAL_ADDRESS="127.0.0.1:7233" \
  INNEROS_TEMPORAL_NAMESPACE="default" \
  INNEROS_TEMPORAL_TASK_QUEUE="inneros-p0-canary" \
  MONGODB_URI="mongodb://127.0.0.1:27017" \
  MONGO_URI="mongodb://127.0.0.1:27017" \
  INNEROS_MONGO_DB="pcdoctor_swarm_canary" \
  INNEROS_WORKTREE_BASE="${ROOT}/.canary/worktrees" \
  INNEROS_NATS_ENABLED="false" \
  INNEROS_OTEL_ENABLED="false" \
  "${ROOT}/.venv-p0-canary/bin/python" \
  "${ROOT}/scripts/run_p0_temporal_mongo_canary.py"
