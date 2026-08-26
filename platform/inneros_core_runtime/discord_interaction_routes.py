"""FastAPI routes for Discord Interactions."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from raphiia_openai import discord_interaction_gateway as gateway

router = APIRouter(prefix="/discord", tags=["discord-interactions"])


@router.get("/interactions/status")
def interactions_status():
    return gateway.endpoint_status()


@router.post("/interactions")
async def interactions(request: Request):
    raw = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    status, body = gateway.handle_interaction(raw, signature, timestamp)
    return JSONResponse(status_code=status, content=body)
