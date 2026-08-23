# RaphiIA-OpenAI

Puente **MCP (Model Context Protocol)** entre **ChatGPT Connectors** y **MongoDB RalfyIA** (`pcdoctor_swarm`).

**Servidor:** Ralphi IA `192.168.1.4` · **Ruta:** `/home/rlopez/projects/raphiia-openai`

Chateas en **ChatGPT normal** → tools guardan/consultan ideas, conversaciones y pipeline editorial. **Sin OpenAI API (`sk-`) en el servidor.**

---

## Empezar aquí

| Paso | Doc |
|------|-----|
| 1. Conectar Cursor al servidor | [`docs/CONEXION.md`](docs/CONEXION.md) |
| 2. Configurar Remote SSH | [`docs/CURSOR_SSH.md`](docs/CURSOR_SSH.md) |
| 3. Arrancar servicios | [`docs/ARRANQUE_RAPIDO.md`](docs/ARRANQUE_RAPIDO.md) |
| 4. Conectar ChatGPT | [`docs/MCP_CHATGPT.md`](docs/MCP_CHATGPT.md) |
| 5. Arquitectura | [`docs/HANDOFF.md`](docs/HANDOFF.md) |

---

## Puertos

| Puerto | Servicio |
|--------|----------|
| **8101** | FastAPI `/status`, `/api/v1/health` |
| **8102** | MCP Streamable HTTP `/mcp` |

Verdad canónica servidor: `/home/rlopez/data/ai_coordination/PORTS_CANONICAL.md`

---

## Quick start (en el servidor, no en Windows)

```bash
cd /home/rlopez/projects/raphiia-openai
cp -n .env.example .env && nano .env
source venv/bin/activate
./run.sh && ./run_mcp.sh
curl http://127.0.0.1:8101/status
```

---

## Ecosistema

| Proyecto | Puerto |
|----------|--------|
| **raphiia-openai** (este) | 8101, 8102 |
| innerspark-swarm-os | 8100 |
| chutes-deposit-agent | 8098 |
| uipath-copilot | 8097 |
