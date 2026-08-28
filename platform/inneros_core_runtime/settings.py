"""Configuración RaphiIA-OpenAI — MCP + Mongo compartida."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# IP LAN del nodo (primary .4, AMD .5, etc.)
RALFIA_LAN_IP = os.getenv("RALFIA_LAN_IP", os.getenv("NODE_IP", "192.168.1.4"))
RALFIA_INTEL_HOST = os.getenv("RALFIA_INTEL_HOST", "192.168.1.4")
RALFIA_AMD_HOST = os.getenv("RALFIA_AMD_HOST", "192.168.1.5")

# HTTP status / health
RAPHI_IA_OPENAI_PORT = int(os.getenv("RAPHI_IA_OPENAI_PORT", "8101"))
RAPHI_IA_OPENAI_HOST = os.getenv("RAPHI_IA_OPENAI_HOST", "0.0.0.0")
RAPHI_IA_PUBLIC_URL = os.getenv("RAPHI_IA_PUBLIC_URL", f"http://{RALFIA_LAN_IP}:{RAPHI_IA_OPENAI_PORT}")

# MCP Streamable HTTP (ChatGPT Connectors)
MCP_PORT = int(os.getenv("MCP_PORT", "8102"))
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PUBLIC_URL = os.getenv("MCP_PUBLIC_URL", f"http://{RALFIA_LAN_IP}:{MCP_PORT}")
MCP_LAN_URL = os.getenv("MCP_LAN_URL", f"http://{RALFIA_INTEL_HOST}:{MCP_PORT}").rstrip("/")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")
MCP_DISPLAY_NAME = os.getenv("MCP_DISPLAY_NAME", "Ralphi-IA-MCP")
MCP_SERVER_VERSION = os.getenv("MCP_SERVER_VERSION", "3.5.0")

# OAuth for ChatGPT / external MCP clients
OAUTH_PORT = int(os.getenv("OAUTH_PORT", "8103"))
OAUTH_HOST = os.getenv("OAUTH_HOST", "0.0.0.0")
OAUTH_ISSUER = os.getenv("OAUTH_ISSUER", f"http://{RALFIA_INTEL_HOST}:8103").rstrip("/")
OAUTH_ISSUER_LAN = os.getenv("OAUTH_ISSUER_LAN", f"http://{RALFIA_INTEL_HOST}:8103").rstrip("/")
_default_mcp_resource = f"{MCP_PUBLIC_URL.rstrip('/')}/mcp"
OAUTH_MCP_RESOURCE = os.getenv("OAUTH_MCP_RESOURCE", _default_mcp_resource).rstrip("/")
OAUTH_MCP_RESOURCE_LAN = os.getenv(
    "OAUTH_MCP_RESOURCE_LAN",
    f"{MCP_LAN_URL.rstrip('/')}/mcp",
).rstrip("/")
OAUTH_TOKEN_TTL_SECONDS = int(os.getenv("OAUTH_TOKEN_TTL_SECONDS", "604800"))
OAUTH_REFRESH_TTL_SECONDS = int(os.getenv("OAUTH_REFRESH_TTL_SECONDS", "2592000"))
OAUTH_CODE_TTL_SECONDS = int(os.getenv("OAUTH_CODE_TTL_SECONDS", "600"))
OAUTH_ALLOWED_REDIRECT_HOSTS = tuple(
    host.strip().lower()
    for host in os.getenv(
        "OAUTH_ALLOWED_REDIRECT_HOSTS",
        "chatgpt.com,localhost,127.0.0.1",
    ).split(",")
    if host.strip()
)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_URI_PRIMARY = os.getenv("MONGO_URI_PRIMARY", "mongodb://192.168.1.4:27017/")
MONGO_URI_LOCAL = os.getenv("MONGO_URI_LOCAL", MONGO_URI)
MONGO_DB = os.getenv("MONGO_DB", "pcdoctor_swarm")

# Qdrant RAG (inneros_kb — Notion, Drive, marcas)
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "inneros_kb")
QDRANT_URL_PRIMARY = os.getenv("QDRANT_URL_PRIMARY", "http://192.168.1.4:6333").rstrip("/")

# Inferencia unificada dual-nodo
OLLAMA_ROUTER_URL = os.getenv("OLLAMA_ROUTER_URL", "http://127.0.0.1:11435").rstrip("/")
RALFIA_OWNER_ID = os.getenv("RALFIA_OWNER_ID", "RAFAEL")
NODE_ROLE = os.getenv("NODE_ROLE", "auto")  # primary | amd | auto
HA_STATE_FILE = Path(os.getenv("HA_STATE_FILE", "/home/rlopez/data/ralfia/ha_state.json"))

COORD_ROOT = Path(os.getenv("AI_COORDINATION_ROOT", "/home/rlopez/data/ai_coordination"))
PORTAL_SERVICES_JSON = os.getenv(
    "PORTAL_SERVICES_JSON",
    "/home/rlopez/projects/innerspark-swarm-os-cursor-local/portal/services.json",
)
OPS_PANEL_PUBLIC_URL = os.getenv("OPS_PANEL_PUBLIC_URL", f"http://{RALFIA_LAN_IP}:2002")

SWARM_API_BASE = os.getenv("SWARM_API_BASE", "http://127.0.0.1:8100").rstrip("/")

COL_CONVERSATIONS = "raphiia_openai_conversations"
COL_MESSAGES = "raphiia_openai_messages"
COL_SYNC_LOG = "raphiia_openai_sync_log"
COL_COORDINATION_LOG = "ralfia_coordination_log"
COL_MAILBOX_SNAPSHOTS = "ralfia_mailbox_snapshots"
COL_MAILBOX_LATEST = "ralfia_mailbox_latest"
COL_COORDINATION_STATE = "ralfia_coordination_state"
COL_AGENT_MESSAGES = "ralfia_agent_messages"
COL_OAUTH_CLIENTS = "ralfia_oauth_clients"
COL_OAUTH_CODES = "ralfia_oauth_codes"
COL_OAUTH_TOKENS = "ralfia_oauth_tokens"
COL_OAUTH_REFRESH_TOKENS = "ralfia_oauth_refresh_tokens"

COL_EDITORIAL_PIPELINE = "editorial_pipeline"
COL_EDITORIAL_POSTS = "editorial_posts"
COL_SOCIAL_DESTINATIONS = "social_destinations"
COL_EDITORIAL_CAMPAIGNS = "editorial_campaigns"
COL_IDEAS = "ideas"
COL_CHAT_MESSAGES = "chat_messages"
COL_MEMORY_ITEMS = "ralfia_memory_items"
COL_MEMORY_VERSIONS = "ralfia_memory_versions"
COL_DAILY_CONVERSATIONS = "daily_life_conversations"
COL_DAILY_CURRENT_STATE = "daily_life_current_state"
COL_DAILY_ENTITIES = "daily_life_entities"
COL_DAILY_PENDING = "daily_life_pending_items"
COL_DAILY_TIMELINE = "daily_life_timeline"
COL_DAILY_AUDIT = "daily_life_memory_audit"
COL_KNOWLEDGE_SEEDS = "ralfia_knowledge_seeds"
COL_DEV_BACKLOG = "ralfia_dev_backlog"
COL_AI_ROUTING_LOG = "ralfia_ai_routing_log"
COL_MCP_ERROR_LOG = "mcp_error_log"

# Notion API bridge (RalfIA → Notion push)
NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN", os.getenv("NOTION_SECRET", ""))
NOTION_DOCS_PARENT_PAGE_ID = os.getenv("NOTION_DOCS_PARENT_PAGE_ID", "")
NOTION_DOCS_DATABASE_ID = os.getenv("NOTION_DOCS_DATABASE_ID", "")
NOTION_AUDIT_DATABASE_ID = os.getenv("NOTION_AUDIT_DATABASE_ID", "")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")
NOTION_MAX_DOC_CHARS = int(os.getenv("NOTION_MAX_DOC_CHARS", "50000"))
NOTION_WEBHOOK_VERIFICATION_TOKEN = os.getenv("NOTION_WEBHOOK_VERIFICATION_TOKEN", "")
NOTION_WEBHOOK_WATCH_DB_IDS = os.getenv("NOTION_WEBHOOK_WATCH_DB_IDS", "")
NOTION_DB08_PROYECTOS_ID = os.getenv("NOTION_DB08_PROYECTOS_ID", "d3710c1b-e655-43e9-ae7d-09f96e9f491b")
NOTION_COORDINATION_DATABASE_ID = os.getenv("NOTION_COORDINATION_DATABASE_ID", "")

# Contifico API (read-only import → MOD-ACCOUNTING)
CONTIFICO_API_KEY = os.getenv("CONTIFICO_API_KEY", "")
CONTIFICO_COMPANY_TOKEN = os.getenv("CONTIFICO_COMPANY_TOKEN", "")
CONTIFICO_API_BASE = os.getenv("CONTIFICO_API_BASE", "https://api.contifico.com/sistema/api/v1")
CONTIFICO_REQUEST_DELAY_MS = float(os.getenv("CONTIFICO_REQUEST_DELAY_MS", "350"))
CONTIFICO_BATCH_PAUSE_EVERY = int(os.getenv("CONTIFICO_BATCH_PAUSE_EVERY", "25"))
CONTIFICO_BATCH_PAUSE_MS = float(os.getenv("CONTIFICO_BATCH_PAUSE_MS", "2000"))

# Orquestación + registry + assets
COL_SERVICE_REGISTRY = "ralfia_service_registry"
COL_RALFIA_PROJECTS = "ralfia_projects"
COL_ORCHESTRATION_BRIEFS = "orchestration_briefs"
COL_ORCHESTRATION_TASKS = "orchestration_tasks"
COL_AGENT_ACTIVITY = "agent_activity_log"
COL_ASSET_REGISTRY = "asset_registry"
COL_FUNDING_PROGRAMS = "funding_programs"
COL_FUNDING_APPLICATIONS = "funding_applications"
COL_FUNDING_CREDIT_ACCOUNTS = "funding_credit_accounts"
COL_FUNDING_CREDIT_CONSUMPTIONS = "funding_credit_consumptions"
COL_FUNDING_PROJECT_LINKS = "funding_project_links"

RALFIA_TIMEZONE = os.getenv("RALFIA_TIMEZONE", "America/Guayaquil")

# Editorial social (DB48 / DB15 / DB16 / DB21)
COL_MEDIA_LIBRARY = "media_library"
EDITORIAL_MEDIA_ROOT = os.getenv(
    "EDITORIAL_MEDIA_ROOT",
    "/home/rlopez/data/media/linkedin",
)
EDITORIAL_VIDEO_ROOT = os.getenv(
    "EDITORIAL_VIDEO_ROOT",
    "/home/rlopez/data/media/videos",
)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
WHISPER_URL = os.getenv("WHISPER_URL", "http://127.0.0.1:9001").rstrip("/")

# Image generation
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", os.getenv("GEMINI_API_KEY", ""))
IMAGE_GEN_MODEL = os.getenv("IMAGE_GEN_MODEL", "imagen-3.0-generate-002")
IMAGE_GEN_PROVIDER = os.getenv("IMAGE_GEN_PROVIDER", "google")  # google | local_comfy | automatic1111 | placeholder
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_CHECKPOINT = os.getenv("COMFYUI_CHECKPOINT", "")
AUTOMATIC1111_URL = os.getenv("AUTOMATIC1111_URL", "http://127.0.0.1:7860").rstrip("/")
LOCAL_IMAGE_PROVIDER = os.getenv("LOCAL_IMAGE_PROVIDER", "comfyui")  # comfyui | automatic1111

# LinkedIn
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_AUTHOR_URN = os.getenv("LINKEDIN_AUTHOR_URN", "")  # urn:li:person:XXX

# Cloudflare — subdominios pcdoctor.ai (AG-44)
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID", "")
CLOUDFLARE_ZONE_NAME = os.getenv("CLOUDFLARE_ZONE_NAME", "pcdoctor.ai")
CLOUDFLARE_TUNNEL_ID = os.getenv(
    "CLOUDFLARE_TUNNEL_ID",
    "6fb8ceab-a17e-41b3-872d-e26ef2d1383f",
)
CLOUDFLARE_TUNNEL_HOST = os.getenv("CLOUDFLARE_TUNNEL_HOST", RALFIA_INTEL_HOST)
CLOUDFLARE_TUNNEL_CONFIG = os.getenv(
    "CLOUDFLARE_TUNNEL_CONFIG",
    "/home/rlopez/.cloudflared/opportunityops.yml",
)
CLOUDFLARE_TUNNEL_SERVICE = os.getenv(
    "CLOUDFLARE_TUNNEL_SERVICE",
    "opportunityops-cloudflared.service",
)
