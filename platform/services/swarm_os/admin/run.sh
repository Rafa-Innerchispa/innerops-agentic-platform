#!/usr/bin/env bash
# Generado por ralphia_project_create — NO editar puerto a mano; usar metadata.json
set -euo pipefail
cd "$(dirname "$0")"
export PORT=5173
export PROJECT_PORT=5173
exec bash -lc 'node node_modules/.bin/vite preview --host 0.0.0.0 --port 5173'
