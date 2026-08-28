# RalfIA Copilot — Open WebUI 0.10.2

## Modelo a usar (siempre)

**RalfIA Copilot (qwen 14B)** — ya es default + pinned.  
No uses `qwen2.5:14b` suelto de la lista Ollama (no tiene MCP/Knowledge/memoria preconfigurados).

## Integraciones ON por defecto (0.10)

Configurado en el preset (`meta` del modelo):

| Integración | Auto |
|-------------|------|
| MCP RalfIA LAN | `toolIds: server:mcp:ralfia-mcp-local` |
| Open Terminal | `terminalId: ralfia-terminal` |
| Web search | `defaultFeatureIds: web_search` (DuckDuckGo) |
| Knowledge runbook | adjunta |
| Memory | capability ON |

En chat nuevo deberías ver MCP y Terminal ya activos en **+ → Integrations** (sin activar manualmente).

## Cómo preguntar (estilo ChatGPT)

Bueno:
- «¿Qué proyectos hay en el mapa del servidor?»
- «Usa MCP y dime el estado de coordinación»
- «Lee ESTADO_ACTUAL vía read_coordination_file»

Evitar:
- Elegir otro modelo Ollama crudo
- Pedir «dame comandos» sin contexto (qwen inventa shell)

## Re-tuning

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/tune_openwebui_copilot.py
```

## Limitación honesta

qwen 14B local **no** iguala GPT-4 en tool use. MCP conecta (logs OK) pero a veces alucina si no sigue el loop de tools. `stream_response: false` en el preset reduce basura `_icall_` en streaming.

Para máxima fluidez MCP: ChatGPT + conector RalfIA. Open WebUI = LAN + voz + terminal + resiliencia.

## Si ves basura tipo webpack / chunk.js

Eso **no** viene del Knowledge runbook (no hay JS ahí). Es **alucinación del modelo** simulando «Paso 1: ejecutar bootstrap_context» en texto.

Comprobar:
1. Modelo = **RalfIA Copilot (qwen 14B)** (no qwen suelto).
2. Chat **nuevo** tras re-tuning; Ctrl+F5 en el navegador.
3. **+ → Integrations** → MCP RalfIA activo.
4. Pregunta explícita: «Usa get_project_map y lista proyectos reales».

Prueba API (debe mostrar `tool_calls` → `get_project_map`, no webpack):

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/test_openwebui_mcp_chat.py
```

## Features 0.10.x útiles para RalfIA (ya aplicadas o disponibles)

| Feature | Utilidad |
|---------|----------|
| `toolIds` / `terminalId` en preset | MCP + terminal ON en chats nuevos |
| Native tool calling (default) | Obligatorio para MCP con Ollama |
| `CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS=64` | Más vueltas tool→respuesta |
| Memory system context toggle | Admin puede tener tools sin meter memorias al contexto |
| Context compaction | Chats muy largos (off por ahora) |
| Structured tool rendering | Mejor UI de tool calls |
| Default model persiste tras refresh | No pierdes RalfIA Copilot al recargar |
| Web search domain filter | Seguridad si activas allow/block |
| Folder uploads KB | Subcarpetas en Knowledge (sync runbook) |
| Pyodide sandbox | Code interpreter legacy — nosotros lo tenemos OFF |
| Event system + webhooks | Auditoría futura (sign-in, config) |

**Nota:** «Initialized 0 tool server(s)» al arrancar es **normal** — MCP no es OpenAPI; se conecta por chat vía `connect_mcp_server`.
