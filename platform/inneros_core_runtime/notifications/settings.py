"""Config notificaciones — Evolution + destino Rafael."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "RalphiIA-pcdoctor")
# Segundo número — nodo AMD (.5), chip distinto
EVOLUTION_AMD_BASE_URL = os.getenv("EVOLUTION_AMD_BASE_URL", "http://192.168.1.5:8082").rstrip("/")
EVOLUTION_AMD_INSTANCE = os.getenv("EVOLUTION_AMD_INSTANCE", "Innerchispa")
EVOLUTION_DEFAULT_NODE = os.getenv("EVOLUTION_DEFAULT_NODE", "primary")  # primary | amd
NOTIFY_WHATSAPP_TO = os.getenv("NOTIFY_WHATSAPP_TO", os.getenv("HACKATHON_WHATSAPP_TO", "593988959606"))

# Política anti-bloqueo WhatsApp (Baileys/Evolution)
WHATSAPP_STATUS_ENABLED = os.getenv("WHATSAPP_STATUS_ENABLED", "0") == "1"
WHATSAPP_AMD_SEND_ENABLED = os.getenv("WHATSAPP_AMD_SEND_ENABLED", "0") == "1"
WHATSAPP_AMD_STATUS_ENABLED = os.getenv("WHATSAPP_AMD_STATUS_ENABLED", "0") == "1"

def _resolve_swarm_base() -> str:
    explicit = os.getenv("SWARM_API_BASE", "").strip().rstrip("/")
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for url in ("http://127.0.0.1:8100", "http://192.168.1.4:8100"):
        if url not in candidates:
            candidates.append(url)
    import httpx

    for url in candidates:
        try:
            r = httpx.get(f"{url}/docs", timeout=2.5)
            if r.status_code < 500:
                return url
        except Exception:
            continue
    return "http://192.168.1.4:8100"


SWARM_API_BASE = _resolve_swarm_base()

NOTIFY_COORDINATION = os.getenv("NOTIFY_COORDINATION", "1") == "1"
NOTIFY_EMAIL_POLL = os.getenv("NOTIFY_EMAIL_POLL", "1") == "1"
NOTIFY_MODULE_DOWN = os.getenv("NOTIFY_MODULE_DOWN", "1") == "1"
NOTIFY_COOLDOWN_SEC = int(os.getenv("NOTIFY_COOLDOWN_SEC", "300"))


def _load_evolution_key_from_sibling_env() -> None:
    """Si .env local no tiene clave, reutiliza funding-hub (mismo servidor)."""
    global EVOLUTION_API_KEY  # noqa: PLW0603
    if EVOLUTION_API_KEY:
        return
    sibling = ROOT / ".." / "hackathon-funding-hub" / ".env"
    if not sibling.is_file():
        return
    for line in sibling.read_text(encoding="utf-8").splitlines():
        if line.startswith("EVOLUTION_API_KEY="):
            EVOLUTION_API_KEY = line.split("=", 1)[1].strip().strip('"')
            break


_load_evolution_key_from_sibling_env()
