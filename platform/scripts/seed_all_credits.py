#!/usr/bin/env python3
"""Seed all researched startup credit programs into MongoDB (ops_3cc5e52351f7)."""

import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymongo

def main():
    print("Seeding all startup credit programs...")
    client = pymongo.MongoClient("mongodb://127.0.0.1:27017/")
    db = client["pcdoctor_swarm"]
    col = db["credit_applications"]
    
    # We clear the collection to avoid duplicates but keep/update Startup Grinder if existing
    col.delete_many({})
    
    programs = [
        {
            "app_id": "app_startup_grinder",
            "program_name": "Startup Grinder Application",
            "provider": "Startup Grinder",
            "type": "credits",
            "status": "applied",
            "value_requested": "10000",
            "value_approved": "",
            "date_applied": "2026-07-14",
            "max_reply_date": "2026-07-28",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "https://docs.google.com/presentation/d/1XyBoopm_InnerChispa_Deck/edit",
            "pitch_url": "https://www.youtube.com/watch?v=InnerChispaPitch",
            "notes": "Aplicación enviada utilizando el expediente corporativo de InnerChispa LLC. Esperando aprobación de los beneficios del ecosistema de partners.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_microsoft_founders",
            "program_name": "Microsoft for Startups Founders Hub",
            "provider": "Microsoft Azure",
            "type": "credits",
            "status": "draft",
            "value_requested": "150000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Startup privada, desarrollando producto de software propio. No requiere financiamiento VC previo. Da acceso inmediato a $1,000-$5,000 en créditos Azure y herramientas (GitHub Enterprise, M365). Escala hasta $150k bajo progreso verificado.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_aws_activate_founders",
            "program_name": "AWS Activate Founders",
            "provider": "Amazon Web Services",
            "type": "credits",
            "status": "draft",
            "value_requested": "5000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Startups bootstrapped / auto-financiadas, menos de 10 años de antigüedad, sitio web activo, correo corporativo. Otorga de $1,000 a $5,000 en créditos directos sin requerir afiliación a aceleradora.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_google_start",
            "program_name": "Google for Startups Cloud Program (Start Tier)",
            "provider": "Google Cloud",
            "type": "credits",
            "status": "draft",
            "value_requested": "2000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Startups pre-funded, fundadas en los últimos 5 años. Otorga hasta $2,000 en créditos GCP para construir el MVP. El dominio no debe estar suscrito a Workspace de pago dentro de los 31 días previos.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_openai_startups",
            "program_name": "OpenAI for Startups Program",
            "provider": "OpenAI API",
            "type": "credits",
            "status": "draft",
            "value_requested": "5000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Startups de IA con menos de 5 años. Se requiere estar respaldado por un partner VC de OpenAI o plataforma verificada (ej. Ramp). Otorga $2,500-$5,000 en créditos API para GPT-4o y razonamiento.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_anthropic_startups",
            "program_name": "Anthropic Startup Program",
            "provider": "Anthropic API",
            "type": "credits",
            "status": "draft",
            "value_requested": "25000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Startups con financiamiento institucional (VC/SAFE). Requiere invitación directa o link del fondo de inversión. Otorga $25,000-$100,000 en créditos de API Claude y subida a los límites más altos de rate-limits.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_github_startups",
            "program_name": "GitHub for Startups",
            "provider": "GitHub Enterprise",
            "type": "credits",
            "status": "draft",
            "value_requested": "10000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Compañías en etapa Series B o anterior, nuevas en GitHub Enterprise, afiliadas a un partner de GitHub. Otorga hasta 20 licencias gratis por 12 meses y créditos de Copilot/Actions.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_cloudflare_startups",
            "program_name": "Cloudflare for Startups",
            "provider": "Cloudflare Platform",
            "type": "credits",
            "status": "draft",
            "value_requested": "5000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Privada, tech product, menos de 5 años. Se puede aplicar como 'bootstrapped' usando códigos promocionales. Otorga desde $5,000 en créditos para Workers, R2, WAF, Workers AI y CDN.",
            "linked_email_ids": []
        },
        {
            "app_id": "app_nvidia_inception",
            "program_name": "NVIDIA Inception",
            "provider": "NVIDIA",
            "type": "credits",
            "status": "draft",
            "value_requested": "5000",
            "value_approved": "",
            "date_applied": "",
            "max_reply_date": "",
            "contact_email": "rlopez@innerchispa.us",
            "linked_domain": "innerchispa.us",
            "investor_deck_url": "",
            "pitch_url": "",
            "notes": "Elegibilidad: Startups de tecnología construyendo productos basados en IA/GPU. Otorga soporte técnico, créditos en NVIDIA GPU Cloud (NGC) y descuentos en hardware local.",
            "linked_email_ids": []
        }
    ]
    
    now_str = datetime.now(timezone.utc).isoformat()
    for prog in programs:
        prog["created_at"] = now_str
        prog["updated_at"] = now_str
        
    res = col.insert_many(programs)
    print(f"Successfully seeded {len(res.inserted_ids)} programs.")

if __name__ == "__main__":
    main()
