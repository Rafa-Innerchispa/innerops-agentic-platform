#!/usr/bin/env python3
"""Servidor voz RalfIA — :8200 PWA Android/iPhone/tablet."""
import uvicorn

from raphiia_openai.settings import RALFIA_LAN_IP

if __name__ == "__main__":
    port = int(__import__("os").environ.get("VOICE_GATEWAY_PORT", "8200"))
    uvicorn.run(
        "raphiia_openai.voice_gateway:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
