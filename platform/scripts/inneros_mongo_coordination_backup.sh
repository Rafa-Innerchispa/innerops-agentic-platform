#!/usr/bin/env bash
# Frequent Mongo coordination backup (pcdoctor_swarm): local HDD + Google Drive.
# Goal: lose hours at worst, not the full daily DR window.
set -euo pipefail

MONGO_DB="${INNEROS_MONGO_DB:-pcdoctor_swarm}"
MONGO_URI="${MONGO_URI:-mongodb://127.0.0.1:27017/}"
BACKUP_MODE="${INNEROS_MONGO_BACKUP_MODE:-core}"
CORE_COLLECTIONS="${INNEROS_MONGO_CORE_COLLECTIONS:-ralfia_ops_tasks,ralfia_coordination_state,ralfia_agent_messages,ralfia_external_repair_runs,ralfia_coordination_log,ralfia_owner_push_inbox}"
DATA_ROOT="${INNEROS_BACKUP_ROOT:-/mnt/inneros_backups/backups/mongo_coordination}"
REMOTE="${RCLONE_REMOTE:-Ralphi-IA-Gdrive}"
REMOTE_DIR="${RCLONE_MONGO_DIR:-RalphiIA_Backups/mongo_coordination}"
KEEP_LOCAL="${KEEP_LOCAL_MONGO:-48}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${DATA_ROOT}/mongo_${MONGO_DB}_${TS}.archive.gz"
LOG="${DATA_ROOT}/backup.log"

mkdir -p "$DATA_ROOT"
echo "[${TS}] start db=${MONGO_DB}" >>"$LOG"

_dump_ok=0
_dump_args=()
if [ "$BACKUP_MODE" = "core" ]; then
  IFS=',' read -r -a _cols <<<"$CORE_COLLECTIONS"
  for c in "${_cols[@]}"; do
    c="${c// /}"
    [ -n "$c" ] && _dump_args+=(--collection "$c")
  done
fi
if command -v mongodump >/dev/null 2>&1; then
  if mongodump --uri="$MONGO_URI" --db="$MONGO_DB" "${_dump_args[@]}" --archive="$ARCHIVE" --gzip; then
    _dump_ok=1
  fi
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'mongodb'; then
  if docker exec mongodb mongodump --db="$MONGO_DB" "${_dump_args[@]}" --archive --gzip >"$ARCHIVE"; then
    _dump_ok=1
  fi
fi
if [ "$_dump_ok" -ne 1 ]; then
  echo "[${TS}] FAIL: mongodump (host or docker mongodb)" | tee -a "$LOG"
  exit 2
fi

SIZE="$(stat -c%s "$ARCHIVE" 2>/dev/null || echo 0)"
echo "[${TS}] local ok bytes=${SIZE} path=${ARCHIVE}" >>"$LOG"

sha256sum "$ARCHIVE" >"${ARCHIVE}.sha256"

UPLOADED=0
if command -v rclone >/dev/null 2>&1 && rclone listremotes 2>/dev/null | grep -q "^${REMOTE}:"; then
  if rclone copyto "$ARCHIVE" "${REMOTE}:${REMOTE_DIR}/$(basename "$ARCHIVE")" \
    --contimeout 30s --timeout 7200s --retries 2 --low-level-retries 2; then
    rclone copyto "${ARCHIVE}.sha256" "${REMOTE}:${REMOTE_DIR}/$(basename "$ARCHIVE").sha256" \
      --contimeout 10s --timeout 60s --retries 1 || true
    echo "[${TS}] cloud ok ${REMOTE}:${REMOTE_DIR}/$(basename "$ARCHIVE")" >>"$LOG"
    UPLOADED=1
  else
    echo "[${TS}] WARN: cloud upload failed (local copy kept)" >>"$LOG"
  fi
fi

find "$DATA_ROOT" -maxdepth 1 -type f -name "mongo_${MONGO_DB}_*.archive.gz" -mtime +"$((KEEP_LOCAL / 2 + 1))" -delete 2>/dev/null || true
find "$DATA_ROOT" -maxdepth 1 -type f -name "mongo_${MONGO_DB}_*.archive.gz.sha256" -mtime +"$((KEEP_LOCAL / 2 + 1))" -delete 2>/dev/null || true

echo "[${TS}] done uploaded=${UPLOADED}" >>"$LOG"
printf '{"ok":true,"archive":"%s","bytes":%s,"uploaded":%s}\n' "$ARCHIVE" "$SIZE" "$UPLOADED"