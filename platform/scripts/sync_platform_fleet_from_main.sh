#!/usr/bin/env bash
# Pull canonical main → SHA-pinned runtime on Intel, rsync mirror to AMD, optional service refresh.
set -euo pipefail

PLATFORM="${INNEROS_PLATFORM_ROOT:-/home/rlopez/inneros/inneros_core/platform}"
CLONE="${INNEROS_PLATFORM_DEPLOY_CLONE:-/home/rlopez/inneros/inneros_core/var/deploy-clones/innerops-agentic-platform-main}"
AMD="${INNEROS_AMD_SSH:-rlopez@192.168.1.5}"
RUN_MIRROR="${INNEROS_FLEET_MIRROR_HA:-0}"
ROLE="${INNEROS_NODE_ROLE:-intel}"

if [[ ! -d "$CLONE/.git" ]]; then
  echo "BLOCKED: deploy clone missing: $CLONE" >&2
  exit 4
fi

cd "$CLONE"
git fetch origin main
git checkout main
git pull --ff-only origin main
HEAD="$(git rev-parse HEAD)"
echo "FLEET_SOURCE_SHA=$HEAD"

export INNEROS_PLATFORM_GIT="$CLONE/platform"
export INNEROS_PLATFORM_RUNTIME="$PLATFORM"
bash "$CLONE/platform/scripts/sync_platform_runtime_from_git.sh" --apply --expected-sha "$HEAD"

RSYNC_EX=(
  --exclude venv/
  --exclude __pycache__/
  --exclude .env
  --exclude .git/
  --exclude data/
)
echo "FLEET_RSYNC → ${AMD}:${PLATFORM}"
rsync -az "${RSYNC_EX[@]}" "$PLATFORM/" "${AMD}:${PLATFORM}/"

ssh -o BatchMode=yes "$AMD" "printf '%s\n' '$HEAD' > '${PLATFORM}/.runtime_git_sha'"

if [[ "$RUN_MIRROR" == "1" ]]; then
  export INNEROS_NODE_ROLE="$ROLE"
  bash "$PLATFORM/scripts/deploy_platform_mirror_ha.sh"
else
  export INNEROS_NODE_ROLE=intel
  "$PLATFORM/scripts/apply_canonical_temporal_worker.sh" >/dev/null
  systemctl --user restart ralfia-mcp-profile@chatgpt_compact.service 2>/dev/null \
    || systemctl --user restart ralfia-mcp.service 2>/dev/null || true
  ssh -o BatchMode=yes "$AMD" "export INNEROS_NODE_ROLE=amd; cd '$PLATFORM' && ./scripts/apply_canonical_temporal_worker.sh && systemctl --user restart ralfia-mcp-profile@chatgpt_compact.service 2>/dev/null || systemctl --user restart ralfia-mcp.service 2>/dev/null || true"
fi

echo "FLEET_SYNC_OK SHA=$HEAD"
