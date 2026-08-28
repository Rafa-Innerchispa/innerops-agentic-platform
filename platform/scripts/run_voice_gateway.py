#!/usr/bin/env python3
"""Servidor voz RalfIA — :8200 PWA Android/iPhone/tablet."""
import uvicorn

from raphiia_openai.settings import RALFIA_LAN_IP

if __name__ == "__main__":
    os = __import__("os")
    port = int(os.environ.get("VOICE_GATEWAY_PORT", "8200"))
    host = os.environ.get("VOICE_GATEWAY_HOST", "127.0.0.1")
    uvicorn.run(
        "raphiia_openai.voice_gateway:app",
        host=host,
        port=port,
        log_level="info",
    )
