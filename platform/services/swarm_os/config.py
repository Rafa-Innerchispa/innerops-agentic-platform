import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_DB = os.getenv("MONGO_DB", "pcdoctor_swarm")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "neural-chat:7b")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8100"))

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

# Evolution API — WhatsApp (:8082)
EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "http://127.0.0.1:8082")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")

# API RUC Intuito/Deuna (credenciales propias — ver manual ASG-INFO-011)
RUC_API_TOKEN_URL = os.getenv(
    "RUC_API_TOKEN_URL",
    "https://consulta-ruc-token.azurewebsites.net/v1/deuna/creacion-token",
)
RUC_API_LOOKUP_URL = os.getenv(
    "RUC_API_LOOKUP_URL",
    "https://consulta-ruc.azurewebsites.net/api/ruc",
)
RUC_API_USER = os.getenv("RUC_API_USER", "")
RUC_API_PASS = os.getenv("RUC_API_PASS", "")

# Whisper local (whisper-service Docker)
WHISPER_URL = os.getenv("WHISPER_URL", "http://127.0.0.1:9001")

OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llava:7b")

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", ROOT / "data" / "media"))
EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", ROOT / "data" / "exports"))
CHAT_UPLOADS_DIR = Path(os.getenv("CHAT_UPLOADS_DIR", ROOT / "data" / "chat_uploads"))

# Hackathon / Devpost (UI Google AI Studio)
HACKATHON_UI_ROOT = Path(
    os.getenv("HACKATHON_UI_ROOT", "/home/rlopez/projects/swarm-os-google_ai_studio")
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN", "")

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
CHAT_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
