#!/usr/bin/env bash
# Libera VRAM de Ollama antes de generar imagen local (ComfyUI SDXL ~6-8GB + qwen14B ~8GB no caben en 12GB).
set -euo pipefail
echo "Modelos cargados en GPU (Ollama):"
curl -sf http://127.0.0.1:11434/api/ps | python3 -m json.tool 2>/dev/null || echo "(Ollama no responde)"
echo ""
echo "Descargando modelos Ollama de VRAM..."
ollama ps -q 2>/dev/null | while read -r m; do
  [[ -n "$m" ]] && ollama stop "$m" && echo "  stopped $m"
done
echo "ComfyUI (:8188) puede usar la GPU. nvidia-smi:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv 2>/dev/null || true
