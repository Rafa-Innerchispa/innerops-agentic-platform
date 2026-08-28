#!/usr/bin/env python3
"""Script to enrich and seed all 10 hackathons (Lablab and Devpost) into MongoDB (ops_ac30025d20c8)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymongo
from raphiia_openai.operational.web_content_manager import export_web_content_for_astro

def run_enrichment():
    client = pymongo.MongoClient("mongodb://127.0.0.1:27017/")
    db = client["pcdoctor_swarm"]
    col = db["innerchispa_web_content"]

    # Clean existing hackathons to prevent duplicate legacy versions
    col.delete_many({"type": "hackathon"})
    print("Cleared existing hackathons in MongoDB.")

    hackathons = [
        # --- LABLAB.AI HACKATHONS (4) ---
        {
            "content_id": "hack_amd_act_ii",
            "type": "hackathon",
            "title": "AMD Developer Hackathon ACT II",
            "slug": "amd-developer-hackathon-act-ii",
            "description": "Ecosistema multiagente soberano edge-cloud que enruta tareas operativas de negocio entre hardware local AMD Ryzen y GPUs AMD Instinct MI300X en la nube, incluyendo auditoría de código local con Gemma.",
            "technologies": ["Gemma 2", "AMD ROCm", "Fireworks AI", "vLLM", "Docker"],
            "images": [
                {"url": "/visuals/quoteops_cover.png", "caption": "Ralphi-IA Hybrid Ops Copilot AMD", "is_cover": True}
            ],
            "demo_url": "https://sworn-profusely-alongside.ngrok-free.dev/amd-ops/",
            "github_url": "https://github.com/Rafa-Innerchispa/amd-ralfiia-hybrid-ops-copilot",
            "submission_url": "https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-ii/innerspark-sovereign-swarm/ralphi-ia-hybrid-ops-copilot-amd",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-07-09T13:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-07-09T15:00:00Z",
            "milestones": [
                {"title": "Track 1: Inferencia Local & Fireworks", "date": "2026-07-09", "status": "completed"},
                {"title": "Track 3: Edge-Cloud Routing", "date": "2026-07-11", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_band_of_agents",
            "type": "hackathon",
            "title": "Band of Agents Hackathon",
            "slug": "band-of-agents-hackathon",
            "description": "Desarrollo de un enjambre multiagente soberano local para diagnóstico de redes IT, CCTV y soporte empresarial, utilizando Band y Featherless con memoria organizacional MongoDB.",
            "technologies": ["Band", "Featherless", "FastAPI", "MongoDB"],
            "images": [
                {"url": "/visuals/zerotokens_cover.png", "caption": "InnerOS IT Field Swarm", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/innerspark-swarm-os-cursor-local",
            "submission_url": "https://lablab.ai/ai-hackathons/band-of-agents-hackathon/innerchispa-autonomous-labs/inneros-sovereign-multi-agent-it-field-swarm",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-07-12T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-07-12T12:00:00Z",
            "milestones": [
                {"title": "Submission Track 1", "date": "2026-07-12", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_ollama_offline",
            "type": "hackathon",
            "title": "Ollama Offline Intelligence Challenge",
            "slug": "ollama-offline-intelligence-challenge",
            "description": "Desarrollo de herramientas de clasificación e ingesta local sin conexión para control y presupuestos operativos asistidos por IA local (Smart Quoter).",
            "technologies": ["Ollama", "Gemma 2", "Python", "Whisper"],
            "images": [
                {"url": "/visuals/gemma2_cover.png", "caption": "Smart Quoter local classification", "is_cover": True}
            ],
            "demo_url": "https://sworn-profusely-alongside.ngrok-free.dev/staging-web/proyectos",
            "github_url": "https://github.com/Rafa-Innerchispa/innerspark-smart-quoter",
            "submission_url": "https://ollama-challenge.lablab.ai/",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-06-30T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-06-30T12:00:00Z",
            "milestones": [
                {"title": "Registration & Setup", "date": "2026-06-14", "status": "completed"},
                {"title": "Offline Pitch Submission", "date": "2026-06-30", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_brightdata_agents",
            "type": "hackathon",
            "title": "BrightData AI Agents Web Data Hackathon",
            "slug": "brightdata-ai-agents-web-data-hackathon",
            "description": "Desarrollo de VigilOS, un ecosistema de seguridad perimetral autónomo asistido por IA en el edge, diseñado para proteger la ingesta de datos públicos y auditar anomalías en tiempo real.",
            "technologies": ["BrightData", "FastAPI", "Docker", "Sovereign AI"],
            "images": [
                {"url": "/visuals/quoteops_cover.png", "caption": "VigilOS Autonomous Edge Security", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/amd-ralfiia-hybrid-ops-copilot",
            "submission_url": "https://lablab.ai/ai-hackathons/brightdata-ai-agents-web-data-hackathon/ralphi-ia/vigilos-autonomous-ai-edge-security-ecosystem",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-07-05T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-07-05T12:00:00Z",
            "milestones": [
                {"title": "Edge Security Architecture", "date": "2026-07-04", "status": "completed"},
                {"title": "BrightData Integration", "date": "2026-07-05", "status": "completed"}
            ]
        },

        # --- DEVPOST HACKATHONS (6) ---
        {
            "content_id": "hack_openai_build_week",
            "type": "hackathon",
            "title": "OpenAI Build Week",
            "slug": "openai-build-week",
            "description": "Desarrollo de la suite RalphiIA QuoteOps utilizando modelos avanzados para clasificar y generar cotizaciones y presupuestos B2B de forma dinámica sin contenido hardcodeado.",
            "technologies": ["OpenAI API", "FastAPI", "MongoDB", "Astro"],
            "images": [
                {"url": "/visuals/quoteops_cover.png", "caption": "RalphiIA QuoteOps", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/raphiia-openai",
            "submission_url": "https://openai.devpost.com/",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-07-13T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-07-13T12:00:00Z",
            "milestones": [
                {"title": "QuoteOps E2E Core", "date": "2026-07-14", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_chutes_malaysia",
            "type": "hackathon",
            "title": "Chutes Hack Malaysia 2026",
            "slug": "chutes-hack-malaysia-2026",
            "description": "Desarrollo de InnerOS Cloud Copilot, un copilot de DevOps autónomo que audita logs de servidor, maneja anomalías de contenedores y despacha notificaciones enriquecidas a WhatsApp.",
            "technologies": ["Chutes", "Docker", "Python", "WhatsApp API"],
            "images": [
                {"url": "/visuals/zerotokens_cover.png", "caption": "InnerOS Cloud Copilot", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/chutes-deposit-agent",
            "submission_url": "https://devpost.com/software/inneros-cloud-copilot-sovereign-agentic-operations",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-06-28T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-06-28T12:00:00Z",
            "milestones": [
                {"title": "DevOps Copilot Engine", "date": "2026-06-29", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_uipath_agenthack",
            "type": "hackathon",
            "title": "UiPath AgentHack",
            "slug": "uipath-agenthack",
            "description": "Desarrollo de PC Doctor Maestro Copilot, un sistema que orquesta excepciones reales de campo de MSP usando MongoDB, Ollama local y WhatsApp human-in-the-loop.",
            "technologies": ["UiPath", "Ollama", "FastAPI", "MongoDB"],
            "images": [
                {"url": "/visuals/gemma2_cover.png", "caption": "PC Doctor Maestro Copilot", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/uipath-copilot",
            "submission_url": "https://devpost.com/software/pc-doctor-maestro-copilot-sovereign-field-case-ai",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-06-22T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-06-22T12:00:00Z",
            "milestones": [
                {"title": "MSP Field Orchestration", "date": "2026-06-23", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_gitlab_transcend",
            "type": "hackathon",
            "title": "GitLab Transcend Hackathon",
            "slug": "gitlab-transcend-hackathon",
            "description": "Desarrollo de InnerSpark DevSecOps Swarm, una malla de agentes autónomos que intercepta eventos de GitLab para auditar vulnerabilidades usando Qwen-14B local.",
            "technologies": ["GitLab API", "Qwen-14B", "FastAPI", "WhatsApp"],
            "images": [
                {"url": "/visuals/zerotokens_cover.png", "caption": "InnerSpark DevSecOps Swarm", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/gitlab-transcend",
            "submission_url": "https://devpost.com/software/innerspark-devsecops-swarm",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-07-06T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-07-06T12:00:00Z",
            "milestones": [
                {"title": "GitLab Webhook Ingestion", "date": "2026-07-06", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_rapid_agent",
            "type": "hackathon",
            "title": "Google Cloud Rapid Agent Hackathon",
            "slug": "google-cloud-rapid-agent-hackathon",
            "description": "Desarrollo de InnerOS-Sovereign, un flujo IT operativo con enrutamiento inteligente, cotizaciones automáticas Notion/MongoDB y alertas enriquecidas por WhatsApp.",
            "technologies": ["Google Cloud", "CrewAI", "Gemini", "MongoDB MCP"],
            "images": [
                {"url": "/visuals/gemma2_cover.png", "caption": "InnerOS IT Field Operations", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/innerspark-swarm-os-cursor-local",
            "submission_url": "https://devpost.com/software/inneros-sovereign-multi-agent-enterprise-orchestrator",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-06-15T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-06-15T12:00:00Z",
            "milestones": [
                {"title": "Multi-Agent IT Dispatch", "date": "2026-06-16", "status": "completed"}
            ]
        },
        {
            "content_id": "hack_gemini_xprize",
            "type": "hackathon",
            "title": "Build with Gemini XPRIZE",
            "slug": "build-with-gemini-xprize",
            "description": "Desarrollo de sistemas multi-agente e integraciones cognitivas utilizando Gemini Pro y mallas de datos distribuidas con persistencia local MongoDB.",
            "technologies": ["Gemini Pro", "MongoDB", "Node.js", "Python"],
            "images": [
                {"url": "/visuals/quoteops_cover.png", "caption": "Gemini XPRIZE Integration", "is_cover": True}
            ],
            "demo_url": "",
            "github_url": "https://github.com/Rafa-Innerchispa/innerspark-swarm-os-cursor-local",
            "submission_url": "https://xprize.devpost.com/",
            "visibility": "public",
            "theme": "default",
            "status": "published",
            "created_at": "2026-06-08T10:00:00Z",
            "updated_at": "2026-07-15T06:30:00Z",
            "approved_by": "rlopez",
            "published_at": "2026-06-08T12:00:00Z",
            "milestones": [
                {"title": "Initial Registration", "date": "2026-06-08", "status": "completed"}
            ]
        }
    ]

    col.insert_many(hackathons)
    print(f"Successfully enriched MongoDB with {len(hackathons)} hackathons.")

    # Export to Astro JSON data files
    export_web_content_for_astro("/home/rlopez/projects/hackathon-autopilot/staging/innerchispa-web/src/data")
    print("Content exported successfully for Astro.")

if __name__ == "__main__":
    run_enrichment()
