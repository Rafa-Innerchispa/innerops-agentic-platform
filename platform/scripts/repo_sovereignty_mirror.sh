#!/usr/bin/env bash
set -u

DEST_ROOT="/mnt/datos_agentes/backups/git_mirrors"
STATE_ROOT="/home/rlopez/inneros/inneros_core/var/repo_sovereignty"
LOG_FILE="$STATE_ROOT/mirror.log"
STATUS_FILE="$STATE_ROOT/status.tsv"
TMP_FILE="$STATUS_FILE.tmp"

mkdir -p "$DEST_ROOT" "$STATE_ROOT"
: > "$TMP_FILE"
printf 'timestamp\trepo\tsource\tmirror\thead\tfetch\tfsck\n' >> "$TMP_FILE"

scan_root() {
  local root="$1"
  [ -d "$root" ] || return 0
  find "$root" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null |
  while IFS= read -r -d '' src; do
    [ -d "$src/.git" ] || continue

    local origin
    origin="$(git -C "$src" remote get-url origin 2>/dev/null || true)"
    case "$origin" in
      *github.com/Rafa-Innerchispa/*) ;;
      *) continue ;;
    esac

    local repo safe dest ts head fetch_state fsck_state
    repo="${origin#*github.com/}"
    repo="${repo%.git}"
    repo="${repo%/}"
    safe="${repo//\//__}"
    dest="$DEST_ROOT/${safe}.git"
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fetch_state="local-only"

    if timeout 120 git -C "$src" fetch origin --prune --tags >/dev/null 2>&1; then
      fetch_state="upstream-refreshed"
    fi

    if [ ! -d "$dest" ]; then
      if ! git clone --mirror "$src" "$dest" >>"$LOG_FILE" 2>&1; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$ts" "$repo" "$src" "$dest" "" "$fetch_state" "clone-failed" >> "$TMP_FILE"
        continue
      fi
    fi

    git --git-dir="$dest" fetch --prune "$src"       '+refs/heads/*:refs/local-heads/*'       '+refs/remotes/origin/*:refs/heads/*'       '+refs/remotes/origin/*:refs/remotes/origin/*'       '+refs/tags/*:refs/tags/*' >>"$LOG_FILE" 2>&1 || true

    head="$(git -C "$src" rev-parse HEAD 2>/dev/null || true)"
    if git --git-dir="$dest" fsck --full --no-dangling >/dev/null 2>&1; then
      fsck_state="ok"
    else
      fsck_state="fail"
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$ts" "$repo" "$src" "$dest" "$head" "$fetch_state" "$fsck_state" >> "$TMP_FILE"
  done
}

scan_root "/home/rlopez/inneros/inneros_core/workspaces"
scan_root "/home/rlopez/inneros/inneros_core/var/local_execution/repos"

mv "$TMP_FILE" "$STATUS_FILE"
printf '%s completed repository mirror cycle\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"


# Offline/local recovery smoke test.
RESTORE_SAMPLE="$DEST_ROOT/Rafa-Innerchispa__inneros-executable-world-2026.git"
RESTORE_TMP="/tmp/inneros-repo-sovereignty-restore-smoke"
RESTORE_PROOF="$STATE_ROOT/restore-proof.txt"
rm -rf "$RESTORE_TMP"
if [ -d "$RESTORE_SAMPLE" ] && git clone "$RESTORE_SAMPLE" "$RESTORE_TMP" >/dev/null 2>&1; then
  RESTORED_HEAD="$(git -C "$RESTORE_TMP" rev-parse HEAD 2>/dev/null || true)"
  printf 'timestamp=%s\nsource=%s\nrestored_head=%s\nresult=PASS\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RESTORE_SAMPLE" "$RESTORED_HEAD" > "$RESTORE_PROOF"
else
  printf 'timestamp=%s\nsource=%s\nresult=FAIL\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RESTORE_SAMPLE" > "$RESTORE_PROOF"
fi
rm -rf "$RESTORE_TMP"
