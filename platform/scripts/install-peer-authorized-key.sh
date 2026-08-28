#!/bin/sh
set -eu

peer_ip=${1:-}
marker=${2:-}
pub_file=${3:-}

case "$peer_ip" in 192.168.1.4|192.168.1.5) ;; *) echo invalid_peer_ip >&2; exit 2;; esac
case "$marker" in ralfia-peer-ops-from-4|ralfia-peer-ops-from-5) ;; *) echo invalid_marker >&2; exit 2;; esac
[ -f "$pub_file" ] || { echo missing_public_key >&2; exit 2; }

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"

key_type=$(awk 'NR==1 {print $1}' "$pub_file")
key_body=$(awk 'NR==1 {print $2}' "$pub_file")
case "$key_type" in ssh-ed25519) ;; *) echo invalid_key_type >&2; exit 2;; esac
[ -n "$key_body" ] || { echo invalid_public_key >&2; exit 2; }

tmp=$(mktemp "$HOME/.ssh/authorized_keys.ralfia.XXXXXX")
trap 'rm -f "$tmp"' EXIT HUP INT TERM
grep -v "$marker" "$HOME/.ssh/authorized_keys" >"$tmp" || true
printf 'from="%s",restrict,command="/home/rlopez/bin/ralfia-peer-ops" %s %s %s\n' \
  "$peer_ip" "$key_type" "$key_body" "$marker" >>"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$HOME/.ssh/authorized_keys"
trap - EXIT HUP INT TERM
echo peer_authorized_key_installed
