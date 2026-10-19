#!/usr/bin/env bash
# Explicit, SHA-pinned synchronization of tested git sources into InnerOS runtime.
# Default operation is non-mutating. This never restarts or reloads services.
set -euo pipefail

WS="$(printenv INNEROS_PLATFORM_GIT || true)"
RT="$(printenv INNEROS_PLATFORM_RUNTIME || true)"
BACKUPS="$(printenv INNEROS_PLATFORM_BACKUP_DIR || true)"
if [ -z "$WS" ]; then WS="/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/platform"; fi
if [ -z "$RT" ]; then RT="/home/rlopez/inneros/inneros_core/platform"; fi
if [ -z "$BACKUPS" ]; then BACKUPS="/home/rlopez/inneros/inneros_core/var/runtime_sync_backups"; fi
MODE="dry-run"
EXPECTED=""

usage() {
  echo "Usage: $0 [--dry-run] [--apply --expected-sha 40-hex-commit]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) MODE="dry-run"; shift ;;
    --apply) MODE="apply"; shift ;;
    --expected-sha)
      if [ "$#" -lt 2 ]; then usage; exit 2; fi
      EXPECTED="$2"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

for bin in git rsync tar df du date; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "BLOCKED: required executable missing: $bin" >&2; exit 3
  fi
done
if [ ! -d "$WS/inneros_core_runtime" ] || [ ! -d "$WS/scripts" ] || [ ! -d "$WS/systemd" ]; then
  echo "BLOCKED: source does not have three required release directories" >&2; exit 4
fi
if [ ! -d "$RT" ]; then echo "BLOCKED: runtime directory missing: $RT" >&2; exit 4; fi
ROOT="$(cd "$WS/.." && pwd -P)"
WS="$(cd "$WS" && pwd -P)"
RT="$(cd "$RT" && pwd -P)"
if [ "$WS" = "$RT" ]; then echo "BLOCKED: source and runtime are identical" >&2; exit 4; fi
HEAD="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"
REMOTE="$(git -C "$ROOT" config --get remote.origin.url || true)"
case "$REMOTE" in
  https://github.com/Rafa-Innerchispa/innerops-agentic-platform|https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git|git@github.com:Rafa-Innerchispa/innerops-agentic-platform.git) ;;
  *) echo "BLOCKED: source origin is not the InnerOS canonical repository" >&2; exit 5 ;;
esac
if ! printf '%s' "$HEAD" | grep -Eq '^[a-f0-9]{40}$'; then
  echo "BLOCKED: no unambiguous git source commit" >&2; exit 5
fi
if [ "$MODE" = "apply" ]; then
  if ! printf '%s' "$EXPECTED" | grep -Eq '^[a-f0-9]{40}$'; then
    echo "BLOCKED: --apply requires exact 40-character expected SHA" >&2; exit 5
  fi
  if [ "$HEAD" != "$EXPECTED" ]; then
    echo "BLOCKED: checked-out HEAD does not match approved expected SHA" >&2; exit 5
  fi
  if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no -- platform/inneros_core_runtime platform/scripts platform/systemd)" ]; then
    echo "BLOCKED: release source contains uncommitted tracked changes" >&2; exit 5
  fi
fi

echo "SOURCE_SHA=$HEAD"
echo "MODE=$MODE"
echo "RUNTIME_PATH=$RT"
echo "NOTE: no services are restarted by this script"
for directory in inneros_core_runtime scripts systemd; do
  rsync -ani --exclude='.env' --exclude='venv/' --exclude='var/' \
    --exclude='__pycache__/' --exclude='*.pyc' \
    "$WS/$directory/" "$RT/$directory/"
done
if [ "$MODE" = "dry-run" ]; then
  echo "DRY_RUN_OK: no runtime files changed"
  exit 0
fi

# Fail safely before the first write when free storage cannot accommodate a
# source+runtime backup. No storage pruning or global package install here.
SOURCE_KB="$(du -sk "$WS/inneros_core_runtime" "$WS/scripts" "$WS/systemd" | awk '{sum += $1} END {print sum+0}')"
RUNTIME_KB="$(du -sk "$RT/inneros_core_runtime" "$RT/scripts" "$RT/systemd" 2>/dev/null | awk '{sum += $1} END {print sum+0}')"
FREE_KB="$(df -Pk "$RT" | awk 'END {print $4+0}')"
MIN_KB=$(( 1024 * 1024 ))
NEEDED_KB=$(( (SOURCE_KB + RUNTIME_KB) * 2 + MIN_KB ))
if [ "$FREE_KB" -lt "$NEEDED_KB" ]; then
  echo "BLOCKED: insufficient free disk for guarded runtime sync and backup" >&2; exit 6
fi

umask 077
mkdir -p "$BACKUPS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$BACKUPS/runtime-before-$STAMP-$HEAD.tar.gz"
tar -C "$RT" -czf "$ARCHIVE" \
  --exclude='.env' --exclude='venv' --exclude='var' \
  --exclude='__pycache__' --exclude='*.pyc' \
  inneros_core_runtime scripts systemd
test -s "$ARCHIVE" || { echo "BLOCKED: runtime backup empty" >&2; exit 7; }
echo "BACKUP=$ARCHIVE"

for directory in inneros_core_runtime scripts systemd; do
  rsync -a --exclude='.env' --exclude='venv/' --exclude='var/' \
    --exclude='__pycache__/' --exclude='*.pyc' \
    "$WS/$directory/" "$RT/$directory/" || {
      echo "BLOCKED: rsync incomplete. Review/restore from backup before restarting services: $ARCHIVE" >&2
      exit 8
    }
done
for file in \
  inneros_core_runtime/dev_swarm_scheduler.py \
  inneros_core_runtime/local_execution_plane.py \
  scripts/inneros_coordination_cycle.py; do
  if [ -f "$WS/$file" ] && ! cmp -s "$WS/$file" "$RT/$file"; then
    echo "BLOCKED: runtime verification mismatch at $file, restore backup before restart" >&2
    exit 9
  fi
done
echo "SYNC_OK SHA=$HEAD BACKUP=$ARCHIVE"
echo "NEXT: validate runtime SHA + canaries; only then use separately approved service actions"
