#!/usr/bin/env bash
# Manual ROCm 10 bind when runfile install fails on sudo (user-owned target).
# Requires prior extract: rocm-installer-10.0.0-4.run --noexec --target rocm-10.0.0
set -euo pipefail

CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
CONTENT="${ROCM10_CONTENT:-$CANARY_DIR/rocm-10.0.0/component-rocm/content}"
TARGET="${ROCM10_INSTALL:-$CANARY_DIR/rocm-10-install/rocm/core-10.0}"
GFX="${ROCM10_GFX:-gfx1201}"
LOG="${ROCM10_MANUAL_LOG:-$CANARY_DIR/rocm10_manual_install.log}"

if [[ ! -d "$CONTENT/base" ]]; then
  echo "FAIL: extract missing at $CONTENT (run runfile --noexec first)" >&2
  exit 1
fi
if [[ ! -d "$CONTENT/$GFX" ]]; then
  echo "FAIL: gfx package dir missing: $CONTENT/$GFX" >&2
  exit 1
fi

mkdir -p "$TARGET/.info"
{
  echo "=== manual install $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  echo "content=$CONTENT target=$TARGET gfx=$GFX"
} | tee "$LOG"

for pkg in "$CONTENT/base"/amdrocm-*; do
  echo "rsync base $(basename "$pkg")" | tee -a "$LOG"
  rsync -a "$pkg/rocm/core-10.0/" "$TARGET/"
done

for pkg in "$CONTENT/$GFX"/amdrocm-*; do
  echo "rsync $GFX $(basename "$pkg")" | tee -a "$LOG"
  rsync -a "$pkg/rocm/core-10.0/" "$TARGET/"
done

echo "manifest manual $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$TARGET/.info/manifest.txt"
du -sh "$TARGET" | tee -a "$LOG"
echo "PASS: manual ROCm 10 bind at $TARGET"
