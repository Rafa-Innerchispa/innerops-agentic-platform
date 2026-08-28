# MongoDB MCP — Google Cloud Rapid Agent Hackathon (track MongoDB)

Este proyecto usa **MongoDB local** (`pcdoctor_swarm`) y el servidor oficial **mongodb-mcp-server** para cumplir el requisito de partner MCP del hackathon.

## Requisitos

- Node.js **22.13+** (verificar: `node -v`)
- MongoDB corriendo en `127.0.0.1:27017`
- Base de datos: `pcdoctor_swarm`

## Opción A — Cursor / VS Code (recomendado para demo)

1. Abre el proyecto backend o UI en Cursor.
2. El archivo `.cursor/mcp.json` ya está configurado en ambos repos.
3. Reinicia Cursor (Settings → MCP → recargar servidores).
4. En el chat del agente, prueba: *"Lista las colecciones de pcdoctor_swarm"*.

Config incluida:

```json
{
  "mcpServers": {
    "MongoDB": {
      "command": "npx",
      "args": ["-y", "mongodb-mcp-server@latest", "--readOnly"],
      "env": {
        "MDB_MCP_CONNECTION_STRING": "mongodb://127.0.0.1:27017/pcdoctor_swarm",
        "MDB_MCP_READ_ONLY": "true"
      }
    }
  }
}
```

## Opción B — Google AI Studio / Agent Builder

1. Ve a [AI Studio](https://ai.studio/apps/a2d230ce-a60c-431a-a56f-f24a6aa14989).
2. En **Tools → MCP**, añade un servidor con:
   - Command: `npx`
   - Args: `-y`, `mongodb-mcp-server@latest`, `--readOnly`
   - Env: `MDB_MCP_CONNECTION_STRING=mongodb://127.0.0.1:27017/pcdoctor_swarm`
3. Si el jurado accede desde internet, usa **MongoDB Atlas** (URI `mongodb+srv://...`) en lugar de localhost.

## Opción C — Setup interactivo (genera config)

```bash
npx mongodb-mcp-server@latest setup
# Responde Y a read-only
# Connection string: mongodb://127.0.0.1:27017/pcdoctor_swarm
```

## Verificación rápida

```bash
# Dry-run (no modifica datos)
export MDB_MCP_CONNECTION_STRING="mongodb://127.0.0.1:27017/pcdoctor_swarm"
npx -y mongodb-mcp-server@latest --readOnly --dryRun
```

## Evidencia para Devpost

- Screenshot del agente listando colecciones vía MCP
- Mencionar en README: *"MongoDB MCP Server conectado a pcdoctor_swarm (71+ colecciones)"*
- Endpoint compliance: `GET http://127.0.0.1:8100/api/v1/hackathon/compliance` → `partner_mcp_mongodb`

## Atlas (opcional, para URL pública)

Si ngrok expone la UI pero MongoDB queda en LAN, crea un cluster Atlas gratuito y actualiza la URI en `.cursor/mcp.json` y `.env`.
