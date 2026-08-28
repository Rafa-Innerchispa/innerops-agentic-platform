# Conexión del proyecto — Ralphi IA (192.168.1.4)

**Este proyecto NO se ejecuta en Windows.** Vive y corre **solo** en el servidor Ralphi IA.

| Dato | Valor |
|------|-------|
| **Host** | `ralphi-ia-ver-10` / `192.168.1.4` |
| **Usuario SSH** | `rlopez` |
| **Ruta del repo** | `/home/rlopez/projects/raphiia-openai` |
| **MongoDB** | `mongodb://127.0.0.1:27017/pcdoctor_swarm` (local en el servidor) |
| **Health HTTP** | `http://192.168.1.4:8101/status` |
| **MCP local** | `http://127.0.0.1:8102/mcp` |
| **MCP público (ChatGPT)** | `https://TU-NGROK.ngrok-free.dev/mcp` |

---

## Regla de oro (Cursor / agentes)

> **Abrir SIEMPRE el workspace en el servidor vía Remote SSH.**
> No trabajar desde Windows apuntando a rutas `/home/rlopez/...` — eso falla y obliga a levantar SSH en cada comando.

### Pasos Cursor (una sola vez)

1. Instalar extensión **Remote - SSH** en Cursor/VS Code.
2. Esquina inferior izquierda → **Remote SSH** → `rlopez@192.168.1.4`.
3. **File → Open Folder** → `/home/rlopez/projects/raphiia-openai`.
4. Verificar barra inferior: **`SSH: 192.168.1.4`** (no "Local").
5. Terminal integrada → debe mostrar `rlopez@ralphi-ia-ver-10` y `pwd` = `/home/rlopez/projects/raphiia-openai`.

Detalle ampliado: [`docs/CURSOR_SSH.md`](CURSOR_SSH.md).

---

## Arranque en el servidor (local = dentro de 192.168.1.4)

```bash
cd /home/rlopez/projects/raphiia-openai

# Entorno (primera vez)
cp -n .env.example .env
nano .env                    # MCP_API_KEY = secreto largo aleatorio
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
chmod +x run.sh run_mcp.sh scripts/*.sh

# Servicios
./run.sh                     # FastAPI :8101 (health/status)
./run_mcp.sh                 # MCP FastMCP :8102/mcp

# Verificar
curl -s http://127.0.0.1:8101/status | python3 -m json.tool
curl -sI http://127.0.0.1:8102/mcp | head -3
bash scripts/smoke_test.sh
```

### ngrok (ChatGPT Connectors — HTTPS público)

En **otra terminal** del mismo servidor:

```bash
cd /home/rlopez/projects/raphiia-openai
./scripts/setup_ngrok.sh
# Copiar URL HTTPS → termina en /mcp
```

Configuración ChatGPT: [`docs/MCP_CHATGPT.md`](MCP_CHATGPT.md).

---

## Puertos (no mezclar)

| Puerto | Servicio | Proyecto |
|--------|----------|----------|
| 8099 | Hackathon Funding Hub | no tocar |
| **8101** | Health/status | **raphiia-openai** |
| **8102** | MCP `/mcp` | **raphiia-openai** |
| 8100 | Swarm-OS API | innerspark-swarm-os |
| 8098 | Chutes | chutes-deposit-agent |
| 8097 | UiPath | uipath-copilot |
| 5173 | InnerOS admin | no tocar |

---

## Variables `.env` (servidor)

```env
MCP_API_KEY=...              # obligatorio para ChatGPT Connectors
MONGO_URI=mongodb://127.0.0.1:27017/
MONGO_DB=pcdoctor_swarm
MCP_PORT=8102
RAPHI_IA_OPENAI_PORT=8101
# NO poner OPENAI_API_KEY / sk- — evita coste API
```

---

## Errores típicos al conectar mal

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `File not found` en `/home/rlopez/...` | Cursor en **Windows local** | Remote SSH → abrir carpeta en servidor |
| SSH en cada comando del agente | Workspace no está en 192.168.1.4 | Cambiar workspace (ver arriba) |
| `can't open file ...\r` | Scripts con CRLF Windows | `sed -i 's/\r$//' *.sh scripts/*.sh` |
| MCP connection refused | `./run_mcp.sh` no arrancado | Ejecutar en terminal del **servidor** |
| ChatGPT 401 | `MCP_API_KEY` distinto | Igualar header `X-API-Key` y `.env` |

---

## Orden de lectura docs

1. **Este archivo** (`CONEXION.md`)
2. [`HANDOFF.md`](HANDOFF.md) — decisiones y arquitectura
3. [`MCP_CHATGPT.md`](MCP_CHATGPT.md) — conectar ChatGPT
4. [`INTEGRATION.md`](INTEGRATION.md) — Mongo colecciones
