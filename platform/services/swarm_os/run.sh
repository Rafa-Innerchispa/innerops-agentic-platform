#!/usr/bin/env bash
# Generado por ralphia_project_create — NO editar puerto a mano; usar metadata.json
set -euo pipefail
cd "$(dirname "$0")"
export PORT=8210
export PROJECT_PORT=8210
exec bash -lc 'venv/bin/python hackathon_band/api_server.py'
