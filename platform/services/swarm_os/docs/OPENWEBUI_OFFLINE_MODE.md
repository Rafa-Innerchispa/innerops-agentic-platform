# Open WebUI — modo offline (sin internet)

Objetivo: seguir trabajando en LAN cuando caigan ngrok, ChatGPT y APIs cloud.

## Qué funciona SIN internet

| Servicio | Puerto | Para qué |
|----------|--------|----------|
| **Open WebUI** | 3000 | Chat + voz (LAN) |
| **Ollama** | 11434 | Modelo local |
| **MCP RalfIA** | 8102 | Mongo, coordinación, memoria |
| **MongoDB** | 27017 | Datos operativos |
| **Open Terminal** | 8010 | Shell real: mkdir, scripts, archivos |
| **FileBrowser** | 8081 | Explorador manual de `/home/rlopez/data` |

## Las 4 capas de memoria (úsalas todas)

| Capa | Dónde | Cuándo |
|------|-------|--------|
| **1. Memory cards** | Open WebUI → Settings → Personalization | Hechos sobre ti, preferencias, rutinas |
| **2. Knowledge** | Admin → Knowledge → `RALFIA_OFFLINE_RUNBOOK.md` | Puertos, proyectos, runbook (RAG local) |
| **3. MCP RalfIA** | Tools en chat | Estado vivo: Mongo, `read_coordination_file`, `save_memory` |
| **4. Disco** | `/home/rlopez/data/ai_coordination/` | Verdad canónica (Cursor/Codex también leen aquí) |

### Qué poner en Memory cards (ejemplos)

Copia y adapta en Personalization → Memories:

- Rafael López, Guayaquil (GYT, GMT-5).
- Servidor principal: 192.168.1.4 — proyectos en `/home/rlopez/projects`, datos en `/home/rlopez/data`.
- Sin internet: usar MCP LAN :8102, Open WebUI :3000, Ollama, Mongo local.
- Puertos clave: 8101 health, 8102 MCP, 8100 swarm, 3000 Open WebUI, 8010 terminal.
- Preferencia: respuestas en español, pasos concretos, comandos copiables.

## Modelo recomendado

**RalfIA Offline (local)** — preset sobre `qwen2.5:14b-instruct` (mejor tool-calling local en tu RTX 3060 12GB).

No esperes nivel ChatGPT; sí espera: consultar MCP, leer runbook, ejecutar comandos en terminal con guía.

## Cómo usar (cada sesión offline)

1. Abre http://192.168.1.4:3000
2. Elige modelo **RalfIA Offline (local)**
3. **+ → Integrations** → activa:
   - **RalfIA MCP (LAN)**
   - **RalfIA Terminal (LAN)**
4. Pregunta en natural: *«¿Qué servicios están caídos?»*, *«Crea la carpeta X en projects»*, *«Lee ESTADO_ACTUAL vía MCP»*

## Qué hace cada herramienta

| Necesidad | Herramienta |
|-----------|-------------|
| Puertos, tareas, estado | MCP: `bootstrap_context`, `get_coordination_summary` |
| Leer doc coordinación | MCP: `read_coordination_file` |
| Buscar en Mongo | MCP: `search` |
| Guardar nota durable | MCP: `save_memory` |
| Crear carpetas, ls, scripts | **Open Terminal** (`run_command`) |
| Datos personales | **Memory** (search_memories / add_memory) |
| Docs estáticos offline | **Knowledge** (runbook subido) |

**Importante:** el Code Interpreter (Pyodide) corre en el **navegador**, no en el servidor. Para mkdir en el servidor usa **Open Terminal**.

## Instalar / actualizar stack offline

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/setup_offline_stack.sh
```

Incluye: runbook, Open Terminal, preset modelo, **subida automática a Knowledge** (ya no manual).

Estado verificado 2026-07-07: KB **RalfIA Offline** + runbook indexado + modelo `ralfia-offline` enlazado.

Regenerar solo el runbook:

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/build_offline_runbook.py
```

## Checklist antes de que caiga internet

- [ ] Ejecutar `setup_offline_stack.sh` con internet (descarga imagen Open Terminal).
- [ ] Subir `RALFIA_OFFLINE_RUNBOOK.md` a Knowledge y adjuntarlo al modelo offline.
- [ ] Completar Memory cards (mínimo 5–10 hechos útiles).
- [ ] Probar un chat: «bootstrap_context y dime qué servicios hay».
- [ ] Probar terminal: «lista /home/rlopez/projects con ls».
- [ ] Verificar MCP: `curl -s http://127.0.0.1:8102/mcp` (desde el servidor).

## Limitaciones honestas

- El modelo 14B **no** elige tools tan bien como GPT; el preset filtra MCP a ~12 funciones esenciales.
- Hay que activar MCP + Terminal **una vez por chat** (limitación Open WebUI).
- Knowledge hay que **indexar con internet** antes; después el RAG funciona offline.
- Voz/micrófono en LAN HTTP puede fallar; en offline usa texto.
