#!/usr/bin/env bash
# Fail if tracked files match high-confidence secret patterns.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0
checked=0

while IFS= read -r path; do
  [[ -f "$path" ]] || continue
  ((checked+=1))

  case "$path" in
    *.example|*/README.md|docs/SECURITY_REMEDIATION_PLAN.md|scripts/check-tracked-secrets.sh)
      continue
      ;;
  esac

  if grep -qE '(mongodb(\+srv)?://[^/@[:space:]]+:[^/@[:space:]]+@|AIza[0-9A-Za-z_-]{20,}|glpat-[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z]{20,})' "$path" 2>/dev/null; then
    echo "SECRET_PATTERN: $path"
    fail=1
  fi

  if [[ "$path" == platform/data/whatsapp_webhook_secret ]]; then
    echo "TRACKED_SECRET_FILE: $path"
    fail=1
  fi

  if [[ "$path" =~ ^var/peer_wifi_credentials/.+\.json$ ]]; then
    echo "TRACKED_WIFI_CREDENTIAL: $path"
    fail=1
  fi

  if [[ "$path" =~ ^backups/.+\.env$ && "$path" != *.example ]]; then
    echo "TRACKED_ENV_BACKUP: $path"
    fail=1
  fi
done < <(git ls-files)

if (( fail )); then
  echo "check-tracked-secrets: FAIL ($checked tracked files scanned)"
  exit 1
fi

echo "check-tracked-secrets: PASS ($checked tracked files scanned)"
