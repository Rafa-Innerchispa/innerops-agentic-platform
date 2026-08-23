# Arranque rápido — servidor 192.168.1.4

Copiar/pegar en terminal **dentro del servidor** (Cursor Remote SSH).

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate 2>/dev/null || { python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt; }
cp -n .env.example .env

# Terminal 1 — health
./run.sh

# Terminal 2 — MCP
./run_mcp.sh

# Terminal 3 — ngrok (ChatGPT)
./scripts/setup_ngrok.sh
```

Verificación:

```bash
curl -s http://127.0.0.1:8101/api/v1/health
curl -sI http://127.0.0.1:8102/mcp
bash scripts/smoke_test.sh
```

ChatGPT: Settings → Connectors → Developer Mode → URL `https://....ngrok.../mcp` + `X-API-Key`.
Ver [`MCP_CHATGPT.md`](MCP_CHATGPT.md).
