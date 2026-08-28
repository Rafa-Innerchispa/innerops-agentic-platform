# Pipeline de vídeo RalfIA

Generación automatizada de vídeos narrados para **InnerChispa**, **InnerSpark** y **PCDoctor**.

## Flujo

```
Brief/MCP → guion (Ollama) → TTS (Piper/espeak) → imágenes (ComfyUI/PIL)
         → montaje ffmpeg (Ken Burns + subs) → MP4 → WhatsApp / web / LinkedIn
```

## Herramientas MCP (ChatGPT / Cursor)

| Tool | Uso |
|------|-----|
| `video_pipeline_health` | Estado TTS, ComfyUI, ffmpeg |
| `generate_video_content` | Genera MP4 completo |
| `publish_video_content` | Publica en WhatsApp Status, web |

### Ejemplo MCP

```json
{
  "title": "InnerSpark Smart Quoter",
  "brief": "Explica el cotizador inteligente en 30 segundos",
  "entity_id": "ent_innerspark",
  "aspect": "9:16",
  "auto_publish": false,
  "destinations": ["web", "whatsapp_status"]
}
```

## Instalación AMD (R9700)

```bash
export SUDO_PASS='...'
bash ~/projects/ralfiia-amd-standby/scripts/setup_video_pipeline_amd.sh
```

Instala: Piper TTS, espeak-ng, ffmpeg, ComfyUI, modelos Ollama 32B/VL.

## Worker editorial automático

```bash
# En .env o systemd
EDITORIAL_AUTO_VIDEO=1
EDITORIAL_AUTO_VIDEO_PUBLISH=0   # 1 para publicar sin revisión
```

Marca borradores con `generate_video: true` en Mongo `editorial_pipeline`.

## n8n

Importar: `ralfiia-amd-standby/n8n/ralfia-video-pipeline.json`  
Webhook POST `/webhook/ralfia-video` con `{title, brief, entity_id, aspect}`.

## Duración y formatos

| aspect | Resolución | Uso |
|--------|------------|-----|
| `9:16` | 1080×1920 | Stories, Reels, WhatsApp Status |
| `16:9` | 1920×1080 | LinkedIn, YouTube |
| `1:1` | 1080×1080 | Feed cuadrado |

Duración típica: **15 s – 3 min** (slideshow + narración).

## Salida

Videos en: `/home/rlopez/data/media/videos/{entity_id}/{timestamp}/`

Cada carpeta incluye: `*.mp4`, `narration.wav`, `subs.srt`, `manifest.json`, escenas JPG.

## Prueba local

```bash
cd ~/projects/raphiia-openai
./venv/bin/python -c "
from raphiia_openai.video_pipeline.pipeline import generate_video
print(generate_video(title='Test Chispa', script='Hola desde RalfIA.', max_scenes=2))
"
```

## Próximos pasos

- ComfyUI en R9700 (imágenes reales SDXL en lugar de placeholders PIL)
- Piper binario (voz más natural que espeak)
- LinkedIn Video API
- Instagram/TikTok APIs
- Sync GCS para backup cloud
