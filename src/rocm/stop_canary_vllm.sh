#!/usr/bin/env bash
set -euo pipefail
docker stop inneros-vllm-canary-rocm10 2>/dev/null || true
docker rm -f inneros-vllm-canary-rocm10 2>/dev/null || true
pkill -f canary_health_server.py 2>/dev/null || true
echo STOPPED canary
