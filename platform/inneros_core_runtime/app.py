"""FastAPI RaphiIA-OpenAI — health :8099 (MCP vive en :8102)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from raphiia_openai.browser_session_routes import router as browser_session_router
from raphiia_openai.discord_interaction_routes import router as discord_interaction_router
from raphiia_openai.editorial_routes import router as editorial_router
from raphiia_openai.mongo_store import log_sync, ping_mongo
from raphiia_openai.routes import router
from raphiia_openai.settings import MCP_PORT, MCP_PUBLIC_URL, RAPHI_IA_OPENAI_PORT, RAPHI_IA_PUBLIC_URL

app = FastAPI(
    title="RaphiIA-OpenAI",
    description="Health/status — integración ChatGPT vía MCP :8102 (ver docs/MCP_CHATGPT.md)",
    version="0.3.0-a2a",
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
app.include_router(browser_session_router)
app.include_router(discord_interaction_router)

# A2A is additive. During rollout a missing/incompatible optional SDK must not
# take down the existing MCP/health plane before the A2A runtime passes tests.
_a2a_app: Any | None = None
_a2a_load_error: str | None = None
try:
    from raphiia_openai.a2a_server import build_a2a_app

    _a2a_app = build_a2a_app()
except Exception as exc:
    _a2a_load_error = f"{type(exc).__name__}: {exc}"

if _a2a_app is not None:
    app.mount("/a2a", _a2a_app)


@app.on_event("startup")
def _startup():
    mongo = ping_mongo()
    log_sync("startup", mongo_ok=mongo.get("ok"), mode="mcp+a2a")


@app.get("/status")
def status():
    return {
        "service": "raphiia-openai",
        "mode": "mcp+a2a",
        "integration": "ChatGPT Connectors → MCP :8102; agentes → A2A 1.0 :8099/a2a",
        "http_port": RAPHI_IA_OPENAI_PORT,
        "mcp_port": MCP_PORT,
        "public_url": RAPHI_IA_PUBLIC_URL,
        "mcp_public_url": f"{MCP_PUBLIC_URL.rstrip('/')}/mcp",
        "mongodb": ping_mongo(),
        "a2a": {
            "enabled": _a2a_app is not None,
            "base_path": "/a2a",
            "protocol_version": "1.0",
            "load_error": _a2a_load_error,
        },
        "docs": {
            "handoff": "docs/HANDOFF.md",
            "mcp_setup": "docs/MCP_CHATGPT.md",
        },
        "endpoints": {
            "health": "GET /api/v1/health",
            "editorial_hub": f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/editorial",
            "discord_interactions": f"{RAPHI_IA_PUBLIC_URL.rstrip('/')}/discord/interactions",
            "mcp": f"http://127.0.0.1:{MCP_PORT}/mcp",
            "a2a": f"http://127.0.0.1:{RAPHI_IA_OPENAI_PORT}/a2a/status",
        },
    }
