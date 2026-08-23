#!/usr/bin/env bash
# Asegura MongoDB en Docker antes de levantar la API.
set -euo pipefail

if curl -sf "http://127.0.0.1:27017" >/dev/null 2>&1 || nc -z 127.0.0.1 27017 2>/dev/null; then
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx 'mongodb'; then
  docker start mongodb >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    nc -z 127.0.0.1 27017 2>/dev/null && exit 0
    sleep 1
  done
fi

echo "WARN: MongoDB no responde en :27017" >&2
exit 0
