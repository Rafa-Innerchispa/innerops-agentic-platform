# Integración — MongoDB + MCP + ChatGPT

> Arranque y conexión: [`CONEXION.md`](CONEXION.md)


## MongoDB (compartida)

```env
MONGO_URI=mongodb://127.0.0.1:27017/
MONGO_DB=pcdoctor_swarm
```

Esquema OS Central: `innerspark-swarm-os-cursor-local/docs/ESQUEMA_MONGODB_DBxx.md`

### Colecciones bridge (nuevas)

| Colección | Uso |
|-----------|-----|
| `raphiia_openai_conversations` | Cabecera conversación |
| `raphiia_openai_messages` | Turnos user/assistant |
| `raphiia_openai_sync_log` | Auditoría MCP |

### Colecciones existentes (lectura/escritura vía tools)

| DBxx | Colección | Tools MCP |
|------|-----------|-----------|
| DB11 | `ideas` | `save_idea`, `search`, `fetch` |
| DB48 | `editorial_pipeline` | `save_pipeline_draft`, `list_pipeline` |
| DB15 | `editorial_posts` | fase 2 |
| DB16 | `social_destinations` | fase 3 |
| DB04 | `clients` | `get_context_summary` |

## ChatGPT Connectors (MCP)

Ver **`docs/MCP_CHATGPT.md`** — única vía de integración con ChatGPT.

- Transport: **Streamable HTTP**
- URL pública HTTPS terminada en `/mcp`
- Auth: `X-API-Key: MCP_API_KEY`

## Swarm-OS :8100

Lectura opcional de contexto operativo. **No duplicar** `api/assistant.py` — RaphiIA-OpenAI es el puente MCP para ChatGPT externo.

## Lo que NO usamos

- ~~Custom GPT Actions~~
- ~~`OPENAI_API_KEY` en servidor para chat~~
- ~~Ollama como camino principal~~ (solo debug local opcional)
