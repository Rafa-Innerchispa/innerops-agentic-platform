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

PYTHON="${ROOT}/.venv-p0-canary/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  echo "REFUSED: missing ${PYTHON}" >&2
  exit 4
fi

"${PYTHON}" - <<'PY'
import socket
import subprocess
import sys


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0

for port, name in ((7233, "Temporal"), (27017, "MongoDB")):
    if not listening(port):
        print(f"REFUSED: {name} 127.0.0.1:{port} is not listening", file=sys.stderr)
        raise SystemExit(5)

probe = subprocess.run(
    ["pgrep", "-af", "temporal_worker.*inneros-p0-canary"],
    text=True,
    capture_output=True,
)
lines = [line for line in probe.stdout.splitlines() if "pgrep -af" not in line]
if lines:
    print("REFUSED: an inneros-p0-canary worker already appears active", file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(6)
PY

mkdir -p "${ROOT}/.canary/worktrees"

printf '%s\n' \
  "P0_TEMPORAL_WORKER_CANARY=STARTING_FOREGROUND" \
  "branch=${BRANCH}" \
  "head=$(git rev-parse HEAD)" \
  "temporal=127.0.0.1:7233" \
  "queue=inneros-p0-canary" \
  "mongo_db=pcdoctor_swarm_canary" \
  "worktree_root=${ROOT}/.canary/worktrees" \
  "nats_enabled=false" \
  "otel_enabled=false" \
  "production_queue=untouched" \
  "production_db=untouched" \
  "stop=Ctrl+C"

exec env \
  PYTHONPATH="${ROOT}/platform" \
  TEMPORAL_HOST="127.0.0.1:7233" \
  TEMPORAL_NAMESPACE="default" \
  INNEROS_TEMPORAL_ADDRESS="127.0.0.1:7233" \
  INNEROS_TEMPORAL_NAMESPACE="default" \
  INNEROS_TEMPORAL_TASK_QUEUE="inneros-p0-canary" \
  MONGODB_URI="mongodb://127.0.0.1:27017" \
  MONGO_URI="mongodb://127.0.0.1:27017" \
  INNEROS_MONGO_DB="pcdoctor_swarm_canary" \
  INNEROS_WORKTREE_BASE="${ROOT}/.canary/worktrees" \
  INNEROS_NATS_ENABLED="false" \
  INNEROS_OTEL_ENABLED="false" \
  "${PYTHON}" -m inneros_core_runtime.temporal_worker \
  --queues inneros-p0-canary
