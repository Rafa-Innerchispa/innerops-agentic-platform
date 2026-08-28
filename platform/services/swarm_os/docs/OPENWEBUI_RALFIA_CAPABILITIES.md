# Open WebUI + RalfIA — qué puede hacer

## Capas conectadas

| Capa | Conector | Escribe datos |
|------|----------|---------------|
| **RalfIA MCP :8102** | MCP Streamable HTTP + Bearer | Mongo (`save_memory`, `save_message`, `save_idea`, `log_coordination_event`), docs coordinación |
| **Ollama :11434** | Nativo | Solo inferencia local |
| **Swarm-OS :8100** | OpenAPI tools (fase 2) | Cotizaciones, clientes, gates Mongo operativos |
| **AnythingLLM :3001** | RAG separado | Índice vectorial documentos PDF |

## Qué hace Open WebUI por sí solo

- Chat + voz (Whisper) + historial en **webui.db** (SQLite local)
- Knowledge: subir PDFs/txt al vector interno de Open WebUI
- **No escribe en Mongo** sin MCP/tools

## Qué puede hacer vía MCP RalfIA (tools principales)

### Leer / consultar en vivo
- `search` — buscar en MongoDB
- `fetch` — documento por id
- `get_project_map` — mapa proyectos/servicios
- `get_coordination_summary` — estado ai_coordination
- `read_coordination_file` / `search_coordination_docs`
- `list_service_registry` / `system_health`
- `get_context_summary` / `bootstrap_context`

### Guardar / persistir (no solo chat)
- `save_memory` — memoria estructurada Mongo
- `save_message` — mensajes agente
- `save_idea` — ideas
- `save_chatgpt_note` / `save_knowledge_seed`
- `log_coordination_event` — bitácora operativa
- `register_change` — cambios de proyecto

### Operación
- `route_ai_task` / `classify_task_runtime`
- `generate_daily_brief`

## Cómo activar en el chat (Open WebUI **0.10.2**)

**Importante:** solo el usuario **admin** (`rafagye@gmail.com`) ve estas opciones.

### 1. Verificar conexión MCP (admin)
1. Entra en http://192.168.1.4:3000 (o HTTPS ngrok `/openwebui/`)
2. Avatar arriba a la derecha → **Panel de administración** (Admin Panel)
3. **Configuración** → pestaña **Herramientas** / **Tools** (antes “External Tools”)
4. En **Tool Servers** / **Servidores de herramientas** debe aparecer **RalfIA MCP (LAN)**
5. Pulsa **Verify** / **Comprobar** — debe conectar a `http://192.168.1.4:8102/mcp`

### 2. Usar MCP en un chat
1. Nuevo chat → botón **+** (junto al input)
2. **Integraciones** → **Tools** / **Herramientas**
3. Activa **RalfIA MCP (LAN)**
4. Pide explícitamente: *"Usa search para…"* o *"Guarda con save_memory…"*

Si no ves el menú admin: cierra sesión y entra con `rafagye@gmail.com`, luego **Ctrl+F5**.

### Actualizar / recrear contenedor

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/upgrade_openwebui_ralfia.sh
```

## URLs

| Uso | URL |
|-----|-----|
| LAN | http://192.168.1.4:3000 |
| HTTPS voz | https://sworn-profusely-alongside.ngrok-free.dev/openwebui/ |
| MCP LAN | http://192.168.1.4:8102/mcp |
| MCP ngrok | https://sworn-profusely-alongside.ngrok-free.dev/raphiia-mcp/mcp |

## Alternativas a Open WebUI

| Producto | Mejor para |
|----------|------------|
| **Open WebUI** | Chat general + MCP + voz (tu stack actual) |
| **AnythingLLM** | RAG documentos, no operación Mongo |
| **LibreChat** | Multi-modelo + agents + MCP (más complejo) |
| **Open WebUI + Swarm tools** | Cotizaciones PC Doctor (fase 2) |

Recomendación: **mantener Open WebUI** como interfaz única + MCP RalfIA + después OpenAPI Swarm para cotizaciones.

## Reconfigurar

```bash
python3 /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/configure_openwebui_ralfia_mcp.py
```
