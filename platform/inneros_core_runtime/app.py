"""FastAPI RaphiIA-OpenAI — health :8099 (MCP vive en :8102)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from raphiia_openai.mongo_store import log_sync, ping_mongo
from raphiia_openai.editorial_routes import router as editorial_router
from raphiia_openai.routes import router
from raphiia_openai.settings import MCP_PORT, MCP_PUBLIC_URL, RAPHI_IA_OPENAI_PORT, RAPHI_IA_PUBLIC_URL

app = FastAPI(
    title="RaphiIA-OpenAI",
    description="Health/status — integración ChatGPT vía MCP :8102 (ver docs/MCP_CHATGPT.md)",
    version="0.2.0-mcp",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(editorial_router)


@app.on_event("startup")
def _startup():
    mongo = ping_mongo()
    log_sync("startup", mongo_ok=mongo.get("ok"), mode="mcp")


@app.get("/status")
def status():
    return {
        "service": "raphiia-openai",
        "mode": "mcp",
        "integration": "ChatGPT Connectors → MCP Streamable HTTP (no OpenAI API en servidor)",
        "http_port": RAPHI_IA_OPENAI_PORT,
        "mcp_port": MCP_PORT,
        "public_url": RAPHI_IA_PUBLIC_URL,
        "mcp_public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
        "mongodb": ping_mongo(),
        "docs": {
            "handoff": "docs/HANDOFF.md",
            "mcp_setup": "docs/MCP_CHATGPT.md",
        },
        "endpoints": {
            "health": "GET /api/v1/health",
            "editorial_hub": f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/editorial",
            "mcp": f"http://127.0.0.1:{MCP_PORT}/mcp (implementar run_mcp.sh)",
        },
    }
