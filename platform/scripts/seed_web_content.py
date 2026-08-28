#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai.operational.web_content_manager import create_web_content

def main():
    print("Seeding sample web content for InnerChispa...")
    
    # 1. Smart Quoter
    res1 = create_web_content(
        content_id="proj_smart_quoter",
        content_type="project",
        title="InnerSpark Smart Quoter",
        slug="innerspark-smart-quoter",
        description="Plataforma de cotización inteligente local asistida por IA. Transcribe audios a través de Whisper, extrae requerimientos y clasifica elementos de cotización utilizando modelos locales offline (Ollama) y enrutadores híbridos.",
        technologies=["Python", "FastAPI", "MongoDB", "Ollama", "Whisper"],
        images=[
            {"url": "/images/projects/quoter_cover.png", "caption": "Dashboard principal del Smart Quoter", "is_cover": True}
        ],
        demo_url="http://192.168.1.4:2026",
        github_url="https://github.com/Rafa-Innerchispa/innerspark-smart-quoter",
        visibility="public",
        theme="purple-neon"
    )
    print("Smart Quoter Seed:", res1)

    # 2. RalphiIA MCP
    res2 = create_web_content(
        content_id="proj_ralphiia_mcp",
        content_type="project",
        title="RalphiIA MCP",
        slug="ralphiia-mcp",
        description="Puente canónico Model Context Protocol (MCP) y servidor de autenticación OAuth para la orquestación y sincronización de datos de negocio (Contífico, CRM, WhatsApp) con agentes inteligentes autónomos.",
        technologies=["Python", "FastMCP", "MongoDB", "OAuth2", "Cloudflare Tunnels"],
        images=[
            {"url": "/images/projects/mcp_architecture.png", "caption": "Diagrama de arquitectura del puente MCP", "is_cover": True}
        ],
        demo_url="https://mcp.innerchispa.us",
        github_url="https://github.com/Rafa-Innerchispa/raphiia-openai",
        visibility="public",
        theme="grayscale"
    )
    print("RalphiIA MCP Seed:", res2)

if __name__ == "__main__":
    main()
