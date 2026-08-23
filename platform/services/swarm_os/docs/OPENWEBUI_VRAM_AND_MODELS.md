# Open WebUI — VRAM 12GB, modelos e imagen local

**GPU:** RTX 3060 12GB · **Chat:** Ollama · **Imagen:** ComfyUI SDXL turbo (:8188)

---

## ¿Pueden funcionar chat e imagen a la vez?

**No de forma fiable en 12GB** si ambos están cargados en VRAM:

| Carga | VRAM aprox. |
|-------|-------------|
| qwen2.5:14b-instruct-q4_K_M | ~8–9 GB |
| SDXL turbo (ComfyUI) | ~6–8 GB |
| **Total si coexisten** | **14–17 GB → OOM** |

### Qué pasa en la práctica

1. Chateas con **RalfIA Copilot (qwen 14B)** → Ollama deja el modelo en GPU (`keep_alive` ~5 min).
2. Pides **generar imagen** (botón Open WebUI o MCP `generate_local_image`):
   - ComfyUI intenta cargar el checkpoint → **CUDA out of memory**, o
   - El sistema se vuelve **muy lento** (swap), o
   - A veces Ollama libera solo tras un rato (no confiable).

**No es que Open WebUI “no pueda”** — es límite físico de VRAM. Chat e imagen **sí pueden usarse en la misma sesión**, pero **en secuencia**, liberando GPU entre uno y otro.

### Flujo recomendado

```bash
# Antes de generar imagen local:
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/prep_gpu_for_local_image.sh
```

Luego genera imagen → cuando termine, vuelves a chatear (Ollama recarga qwen en ~10–30 s).

---

## Dos vías de imagen local (activadas)

| Vía | Cómo | Backend |
|-----|------|---------|
| **Open WebUI** | Integraciones → Image generation ON · icono imagen en chat | ComfyUI :8188 |
| **MCP** | «Genera imagen con generate_local_image…» | Mismo ComfyUI vía MCP :8102 |

Misma GPU, mismas reglas VRAM.

---

## Modelos recomendados (esta máquina NVIDIA)

| Preset | Modelo Ollama | Uso | VRAM |
|--------|---------------|-----|------|
| **RalfIA Copilot (qwen 14B)** ⭐ default | qwen2.5:14b-instruct-q4_K_M | MCP + ops + español | ~8 GB |
| **RalfIA Fast (qwen 7B)** | qwen2.5:7b | Tools más estables, menos listo | ~4 GB |
| **RalfIA Vision (llava 7B)** | llava:7b | Analizar fotos/PDF escaneados | ~4 GB |

**Recomendación:** mantén **Copilot 14B** como principal. Usa **Fast 7B** si qwen 14B alucina tools. Usa **Vision** solo para ver imágenes (cierra chat 14B antes).

**Imagen:** no uses Ollama flux/SD en 12GB con 14B cargado — usa **ComfyUI**:

| Modo | Checkpoint | Uso |
|------|------------|-----|
| **HD fotorrealista** | RealVisXL V5 fp16 (~7 GB) | Personas, futurista, editorial |
| **Rápido** | SDXL turbo | Bocetos, pruebas (~8 pasos) |

Instalar RealVis: `bash …/scripts/install_comfyui_realvis_checkpoint.sh` (descarga ~7 GB una vez).

---

## MCP: cuántas tools

Open WebUI filtra **~23 tools** (ops + imagen + salud). ChatGPT ngrok sigue con **82** completas.

Con 23 tools qwen 14B va justo; si empeora, baja a preset Fast 7B o reduce tools en `tune_openwebui_copilot.py`.

---

## Futuro: máquina AMD

Mismo stack conceptual:

- **Ollama** con ROCm (modelos GGUF igual)
- **ComfyUI** build ROCm o CPU offload parcial
- **Open WebUI** sin cambios (Docker apuntando a Ollama/ComfyUI en LAN)

VRAM/iGPU compartida en AMD suele ser **más ajustada** — priorizar **un modelo chat 7–8B + imagen por turnos**, no 14B+SDXL simultáneo. Documentar en hackathon AMD cuando montes esa máquina.

---

## Re-aplicar config

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/tune_openwebui_copilot.py
```
