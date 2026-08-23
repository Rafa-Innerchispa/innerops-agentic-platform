# MCP + ChatGPT Connectors — guía RaphiIA-OpenAI

> **Conexión servidor y Cursor:** [`CONEXION.md`](CONEXION.md) · [`CURSOR_SSH.md`](CURSOR_SSH.md) · [`ARRANQUE_RAPIDO.md`](ARRANQUE_RAPIDO.md)


## Por qué MCP (y no Custom GPT)

| | Custom GPT + Actions | **MCP Connector** |
|--|----------------------|-------------------|
| Dónde chateas | GPT aparte, limitado | **ChatGPT normal** |
| Configuración | OpenAPI, instrucciones, schema | **Add connector + URL** (una vez) |
| Sensación | “Cuadrado” | **Tipo Notion** |
| Coste backend | REST gratis | **REST/MCP gratis** (solo Mongo) |
| LLM | ChatGPT (plan) | ChatGPT (plan) — **no `sk-` en tu servidor** |

---

## Requisitos

- ChatGPT **Plus / Pro / Team / Enterprise** (Developer Mode para conectores custom)
- Servidor RaphiIA accesible por **HTTPS público** (ngrok o gateway `:5188`)
- MongoDB local `pcdoctor_swarm` en `192.168.1.4`
- **No** hace falta `OPENAI_API_KEY` en `.env` de este proyecto

---

## Puertos

| Servicio | Puerto | URL local |
|----------|--------|-----------|
| Status / health FastAPI | 8101 | `http://192.168.1.4:8101/status` |
| **MCP Streamable HTTP** | **8102** | `http://127.0.0.1:8102/mcp` |

ChatGPT conecta a la URL **pública** del MCP, por ejemplo:

```
https://TU-NGROK.ngrok-free.dev/raphiia-mcp/mcp
```

(Ajustar ruta en `scripts/setup_ngrok.sh` cuando exista.)

---

## Configuración en ChatGPT (paso a paso)

1. Abrir **ChatGPT** → avatar → **Settings**
2. **Connectors** → activar **Developer Mode** (beta)
3. **Add custom connector**
   - **Name:** RaphiIA Mongo
   - **Description:** Guardar y consultar ideas/conversaciones RalfyIA en MongoDB
   - **URL:** `https://…/mcp` (HTTPS, terminación `/mcp`)
   - **Auth:** API Key → header `X-API-Key` = valor de `MCP_API_KEY` en `.env`
4. Guardar → en chat normal, activar el connector (icono / menú connectors)
5. Probar:
   - *“Guarda esta idea: post LinkedIn sobre IA soberana InnerChispa”*
   - *“Busca ideas recientes sobre InnerChispa”*
   - *“Resume cuántos clientes e ideas hay en la base”*

---

## Tools MCP a implementar

| Tool | Acción | Mongo |
|------|--------|-------|
| `save_message` | Guardar turno conversación | `raphiia_openai_messages` |
| `save_idea` | Guardar idea titulada | `ideas` (DB11) |
| `search` | Buscar ideas/mensajes (requerido ChatGPT) | text index / regex |
| `fetch` | Obtener documento por id (requerido ChatGPT) | por `_id` o `idea_id` |
| `get_context_summary` | Conteos clientes, ideas, pipeline | lectura |
| `list_pipeline` | Borradores editoriales | `editorial_pipeline` |
| `save_pipeline_draft` | Guardar borrador (texto ya generado por ChatGPT) | DB48 |

**Importante:** muchos conectores ChatGPT validan presencia de tools **`search`** y **`fetch`**. Incluirlos siempre.

---

## Costes

| Qué | ¿Paga API OpenAI? |
|-----|-------------------|
| Conversación en ChatGPT | Incluido en tu plan ChatGPT |
| MCP → tu servidor → Mongo | **No** |
| Llamar `sk-` desde backend propio | **Sí** — **no hacer** |

---

## Seguridad

- `MCP_API_KEY` largo y aleatorio en `.env`
- MCP solo por HTTPS (ngrok)
- Tools de escritura acotadas (no `drop database`)
- Logs en `raphiia_openai_sync_log`

---

## Referencias

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FastMCP](https://gofastmcp.com/)
- Notion (referencia UX): connector oficial `mcp.notion.com`

---

## Si ChatGPT no conecta ? preguntas y checklist

La documentaci?n de OpenAI sobre Connectors puede estar incompleta o cambiar. **Prevalece la conexi?n MCP real** (`streamable-http` en `/mcp`), no suposiciones del asistente.

### Antes de conectar

1. En Ralphi IA (`192.168.1.4`):
   ```bash
   cd /home/rlopez/projects/raphiia-openai
   cp .env.example .env   # si no existe
   # Editar MCP_API_KEY con valor largo aleatorio
   ./run_mcp.sh           # :8102/mcp
   ./scripts/setup_ngrok.sh   # otra terminal ? copiar URL HTTPS
   ```
2. Verificar local: `curl -I http://127.0.0.1:8102/mcp` ? debe responder (no connection refused).

### Configuraci?n en ChatGPT (Developer Mode)

| Campo | Valor correcto |
|-------|----------------|
| URL | `https://TU-NGROK.ngrok-free.dev/mcp` (termina en `/mcp`) |
| Transport | Streamable HTTP (no SSE legacy) |
| Auth | API Key ? header **`X-API-Key`** = valor de `MCP_API_KEY` en `.env` |
| Tools requeridos | **`search`** y **`fetch`** (implementados) |

### Preguntas ?tiles para ChatGPT / soporte OpenAI

Si el conector falla al validar o no aparecen tools, preguntar:

1. *?Qu? versi?n del protocolo MCP espera el conector custom en Developer Mode (2024-11-05 vs 2025-03-26 streamable-http)?*
2. *?La URL debe terminar exactamente en `/mcp` o acepta redirect?*
3. *?El auth API Key se env?a como `X-API-Key`, `Authorization: Bearer`, o ambos?*
4. *?Qu? tools m?nimos exige la validaci?n del conector (`search`/`fetch` nombres exactos)?*
5. *?Hay que declarar `resources` o solo `tools` para pasar la validaci?n?*
6. *?Ngrok free tier (`ngrok-skip-browser-warning`) bloquea el handshake MCP?*

### Errores frecuentes

| S?ntoma | Causa probable | Fix |
|---------|----------------|-----|
| Connection refused | MCP no arrancado en servidor | `./run_mcp.sh` en 192.168.1.4 |
| 401 / Unauthorized | `MCP_API_KEY` distinto en ChatGPT vs `.env` | Igualar header `X-API-Key` |
| Validaci?n falla tools | Faltan `search`/`fetch` | Ya incluidos en `mcp_server.py` |
| ngrok interstitial | P?gina HTML en vez de MCP | Usar dominio reservado ngrok o gateway `:5188` |
| CRLF en scripts Windows | `\r` en paths | `sed -i 's/\r$//' *.sh scripts/*.sh` |

### Modo sin coste API (confirmar)

- **NO** poner `OPENAI_API_KEY` / `sk-` en `.env` del servidor.
- ChatGPT hace el razonamiento; el servidor solo persiste/consulta Mongo v?a MCP.
