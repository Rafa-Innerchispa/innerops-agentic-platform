# Open WebUI — guía simple (sin comandos manuales)

## Qué modelo elegir (no es lo mismo ComfyUI)

| Modelo en el desplegable | Para qué sirve | ¿Chatea? | ¿Dibuja? |
|--------------------------|----------------|----------|----------|
| **RalfIA Copilot (qwen 14B)** | Proyectos, MCP, terminal, memoria, web | Sí | Solo con el **icono 🖼️** (no solo texto) |
| **RalfIA Imagen HD (local)** | Pedir imagen **fotorrealista** por texto | Una frase | Sí (RealVisXL) |
| **RalfIA Imagen Rápida** | Bocetos rápidos (~10 s), estilo más cartoon | Una frase | Sí (SDXL turbo) |
| **RalfIA Fast (qwen 7B)** | Respuestas rápidas con tools | Sí | Icono 🖼️ |
| **RalfIA Vision (llava 7B)** | Analizar fotos que subes | Sí | No |

**ComfyUI no aparece como modelo de chat.** Es el motor de dibujo en `:8188`; qwen entiende tu texto y le ordena dibujar.

### ¿Por qué salían como dibujos / cartoon?

El modelo **SDXL Turbo** está pensado para **velocidad** (8 pasos), no fotorrealismo. Por eso unicornios y escenas futuristas salían tipo ilustración.

| Preset | Motor | Calidad | Tiempo aprox. |
|--------|-------|---------|---------------|
| **RalfIA Imagen HD** | RealVisXL V5 | Personas reales, futurista, detalle | 30–90 s |
| **RalfIA Imagen Rápida** | SDXL turbo | Boceto / cartoon | 5–15 s |

Tras instalar RealVisXL (automático en el servidor), elige **Imagen HD** y pide explícitamente: *«fotorrealista, personas reales, iluminación cinematográfica»*.

---

## Qué hacer tú en la interfaz

1. Abre http://192.168.1.4:3000
2. **Ctrl+F5** si acabas de un error de imagen (recarga la config)
3. Para **hablar de proyectos / MCP** → **RalfIA Copilot (qwen 14B)** (default)
4. Para **generar imagen fotorrealista** → **RalfIA Imagen HD (local)** + **chat nuevo**
5. Escribe y envía

### Botones que ves (Integraciones)

| Botón | Qué es | Qué haces |
|-------|--------|-----------|
| **RalfIA MCP (LAN)** | Conexión al servidor (Mongo, proyectos, memoria, WhatsApp borrador) | Déjalo **ON** — el modelo consulta datos reales |
| **RalfIA Terminal (LAN)** | Consola remota en el servidor (`/home/rlopez/projects`, scripts) | ON si pides «ejecuta en terminal»; OFF si solo preguntas |
| **Web Search** | DuckDuckGo | ON si quieres buscar en internet |
| **Image generation** | Dibuja con ComfyUI local (SDXL turbo) | ON → icono imagen o «genera una imagen de…» |

**No tienes que ejecutar ningún script.** El servidor tiene un daemon (`ralfia-gpu-handoff`) que, cuando empieza una imagen, **suelta qwen de la GPU** solo.

---

## Si chateas y pides imagen en el mismo chat

- **No pierdes el chat** — el historial queda guardado.
- **No “cuelga” para siempre** — mientras genera imagen (30 s–2 min), esperas la imagen; luego puedes seguir escribiendo.
- Al siguiente mensaje, Ollama **vuelve a cargar qwen** (~10–30 s la primera respuesta). Es normal en 12 GB.

No hace falta reiniciar la máquina ni cerrar Open WebUI.

---

## Varios usuarios mañana (4 personas)

| Situación | Qué pasa |
|-----------|----------|
| **4 chateando a la vez** | Ollama **encola** peticiones; todos atendidos, algo más lento si coinciden |
| **4 generando imagen a la vez** | ComfyUI **encola**; una imagen usa casi toda la GPU → van **en fila**, no en paralelo real |
| **2 chat + 2 imagen** | El daemon libera qwen para imagen; chats en espera un momento |

En 12 GB **no** hay 4 imágenes simultáneas reales. Sí hay **cola ordenada** — nadie tiene que hacer nada manual.

Agentes externos (Cursor, ChatGPT MCP) que llamen Ollama **comparten la misma cola** — no duplican qwen en memoria por duplicado; Ollama serializa o encola.

---

## Script prep_gpu (solo emergencia)

`prep_gpu_for_local_image.sh` es **respaldo** si algo falla. **No lo uses** en el día a día; el daemon ya lo hace.

---

## Re-aplicar todo automático

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/tune_openwebui_copilot.py
```

Activa preset, MCP, imagen ComfyUI y el daemon GPU.
