"""Configuración hackathon Band — variables desde .env del repo raíz."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
load_dotenv(REPO_ROOT / ".env")

BAND_REST_URL = os.getenv("BAND_REST_URL", "https://app.band.ai").rstrip("/")
BAND_API_KEY = os.getenv("BAND_API_KEY", "")

BAND_AGENT_ID_ROUTER = os.getenv("BAND_AGENT_ID_ROUTER", "")
BAND_AGENT_ID_MEMORY = os.getenv("BAND_AGENT_ID_MEMORY", "")
BAND_AGENT_ID_ANALYST = os.getenv("BAND_AGENT_ID_ANALYST", "")
BAND_AGENT_ID_DOCUMENTATION = os.getenv("BAND_AGENT_ID_DOCUMENTATION", "")

# Nombres @mention en Band (deben coincidir con el agente en app.band.ai)
BAND_AGENT_NAME_ROUTER = os.getenv("BAND_AGENT_NAME_ROUTER", "Router")
BAND_AGENT_NAME_MEMORY = os.getenv("BAND_AGENT_NAME_MEMORY", "Memory")
BAND_AGENT_NAME_ANALYST = os.getenv("BAND_AGENT_NAME_ANALYST", "analyst")
BAND_AGENT_NAME_DOCUMENTATION = os.getenv("BAND_AGENT_NAME_DOCUMENTATION", "docmaker")
BAND_API_KEY_ROUTER = os.getenv("BAND_API_KEY_ROUTER", BAND_API_KEY)
BAND_API_KEY_MEMORY = os.getenv("BAND_API_KEY_MEMORY", BAND_API_KEY)
BAND_API_KEY_ANALYST = os.getenv("BAND_API_KEY_ANALYST", BAND_API_KEY)
BAND_API_KEY_DOCUMENTATION = os.getenv("BAND_API_KEY_DOCUMENTATION", BAND_API_KEY)

BAND_AGENT_API_KEYS: dict[str, str] = {
    "router": BAND_API_KEY_ROUTER,
    "memory": BAND_API_KEY_MEMORY,
    "analyst": BAND_API_KEY_ANALYST,
    "documentation": BAND_API_KEY_DOCUMENTATION,
}

FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY", "")
FEATHERLESS_BASE_URL = os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
FEATHERLESS_MODEL = os.getenv(
    "FEATHERLESS_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct"
)

AIML_API_KEY = os.getenv("AIML_API_KEY", "")
AIML_BASE_URL = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
AIML_MODEL = os.getenv("AIML_MODEL", "deepseek/deepseek-r1")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Evolution WhatsApp — mismo .env que InnerOS (swarm-api :8100)
EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://192.168.1.4:8082")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
HACKATHON_WHATSAPP_TO = os.getenv("HACKATHON_WHATSAPP_TO", "").strip()
HACKATHON_EMAIL_TO = os.getenv("HACKATHON_EMAIL_TO", "").strip()

HACKATHON_BAND_PORT = int(os.getenv("HACKATHON_BAND_PORT", "5190"))
HACKATHON_API_PORT = int(os.getenv("HACKATHON_API_PORT", "8200"))
HACKATHON_API_HOST = os.getenv("HACKATHON_API_HOST", "0.0.0.0")

RALPHI_DATA_DOCS = Path(os.getenv("RALPHI_DATA_DOCS", "/home/rlopez/data/docs"))
OUTPUTS_DIR = ROOT / "outputs"
BAND_AUDIT_DIR = ROOT / ".band_local"
REPORT_PATH = OUTPUTS_DIR / "hackathon_report.md"

AGENTS = {
    "router": {
        "id": "AG-001",
        "name": BAND_AGENT_NAME_ROUTER,
        "band_id": BAND_AGENT_ID_ROUTER,
        "api_key": BAND_API_KEY_ROUTER,
    },
    "memory": {
        "id": "AG-004",
        "name": BAND_AGENT_NAME_MEMORY,
        "band_id": BAND_AGENT_ID_MEMORY,
        "api_key": BAND_API_KEY_MEMORY,
    },
    "analyst": {
        "id": "AG-003",
        "name": BAND_AGENT_NAME_ANALYST,
        "band_id": BAND_AGENT_ID_ANALYST,
        "api_key": BAND_API_KEY_ANALYST,
    },
    "documentation": {
        "id": "AG-005",
        "name": BAND_AGENT_NAME_DOCUMENTATION,
        "band_id": BAND_AGENT_ID_DOCUMENTATION,
        "api_key": BAND_API_KEY_DOCUMENTATION,
    },
}

DEFAULT_QUESTION = (
    "¿Qué sabemos sobre fallas previas de cámaras de seguridad y qué deberíamos recomendar?"
)

OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
BAND_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
