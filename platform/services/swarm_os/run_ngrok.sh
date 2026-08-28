#!/usr/bin/env bash
# Compatibilidad: redirige al túnel dual (InnerOS + Hackathon)
exec "$(dirname "$0")/run_ngrok_all.sh"
