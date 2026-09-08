#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKERFILE="${PLATFORM_ROOT}/docker/xtts/Dockerfile"
IMAGE="${XTTS_DOCKER_IMAGE:-ralfia-xtts:latest}"

if [[ ! -f "${DOCKERFILE}" ]]; then
  echo "Missing XTTS Dockerfile: ${DOCKERFILE}" >&2
  exit 1
fi

docker build -t "${IMAGE}" -f "${DOCKERFILE}" "${PLATFORM_ROOT}/docker/xtts"
docker image inspect "${IMAGE}" >/dev/null

echo "XTTS Docker image ready: ${IMAGE}"
