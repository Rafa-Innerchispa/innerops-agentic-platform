#!/usr/bin/env bash
# Descarga RealVisXL V5 fp16 (~7 GB) — checkpoint fotorealista SDXL para ComfyUI.
set -euo pipefail

DEST="${COMFYUI_CHECKPOINTS:-/home/rlopez/apps/ComfyUI/models/checkpoints}"
FILE="RealVisXL_V5.0_fp16.safetensors"
URL="https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/${FILE}"

mkdir -p "$DEST"
TARGET="$DEST/$FILE"

if [[ -f "$TARGET" ]]; then
  echo "OK ya existe: $TARGET ($(du -h "$TARGET" | cut -f1))"
  exit 0
fi

echo "Descargando $FILE → $TARGET (~7 GB, puede tardar varios minutos)..."
curl -L --progress-bar -o "$TARGET.part" "$URL"
mv "$TARGET.part" "$TARGET"
echo "OK descargado: $TARGET"

python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/fix_openwebui_image_config.py
