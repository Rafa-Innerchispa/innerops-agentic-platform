"""Mapa de capacidades ISKCON local — qué reutiliza de InnerOS (sin duplicar DB)."""

from __future__ import annotations

from typing import Any

ENTITY_ID = "ent_iskcon"
PROJECT = "iskcon"

# Dominios operativos de una comunidad ISKCON local
ISKCON_DOMAINS: dict[str, dict[str, Any]] = {
    "food_for_life": {
        "label": "Food for Life — distribución de comida",
        "actions": [
            "Registrar raciones diarias (platos, ubicación, voluntarios)",
            "Historial de distribuciones y rutas",
            "Inventario insumos / donaciones en especie",
            "Reportes para donantes y grants FFL",
        ],
        "reuse": {
            "memory": "daily_memory → ralfia_memory_items (tags: ffl, rations, project=iskcon)",
            "contacts": "contacts/ops_contacts → voluntarios y donantes (entity_id=ent_iskcon)",
            "funding": "funding_registry → grants FFL, Rotary, CSR",
            "ops": "ralfia_ops_tasks → tareas logística",
            "documents": "document_engine theme ent_iskcon → reportes",
        },
        "status": "LIVE",
    },
    "donations_fundraising": {
        "label": "Donaciones y fondos",
        "actions": [
            "Seguimiento donantes y patrocinadores",
            "Grants y convocatorias ONG",
            "Cuentas de crédito/consumo (cloud, servicios)",
            "Recibos y cartas de agradecimiento",
        ],
        "reuse": {
            "funding": "funding_programs, funding_applications, funding_credit_accounts",
            "contacts": "panihati_sponsors (festival) + contacts ent_iskcon",
            "accounting": "create_receivable_draft, record_payment (si billing_enabled)",
            "email": "search_email_archive → oportunidades grant",
        },
        "status": "PARTIAL",
    },
    "festivals_events": {
        "label": "Festivales y eventos (Panihati, Ratha Yatra, etc.)",
        "actions": [
            "Patrocinadores y pipeline sponsors",
            "Gastos y aprobación tesorero",
            "Tareas del comité organizador",
            "Plantillas cartas / WhatsApp borrador",
        ],
        "reuse": {
            "panihati": "panihati_sponsors, panihati_expenses, panihati_tasks, panihati_group_events",
            "whatsapp": "Evolution webhook → iskcon-panihati-2026 :2027",
            "mcp": "send_whatsapp_draft, extract_fields_from_media, generate_quote_pdf (adaptable)",
        },
        "status": "PARTIAL",
    },
    "workshops_education": {
        "label": "Talleres, yoga aplicado y educación",
        "actions": [
            "Calendario talleres y facilitadores",
            "Materiales y asistencia",
            "Memoria de contenidos impartidos",
            "Borradores WhatsApp para yoga aplicado a cultura vaishnava",
            "Avisos de cambios de clase con aprobación previa",
        ],
        "reuse": {
            "memory": "ralfia_memory_items (tags: workshop, education, yoga, vaishnava)",
            "ops": "ralfia_ops_tasks",
            "web": "iskconguayaquil.org como presencia pública y futuro destino de publicación",
            "notion": "páginas ISKCON OS / calendario / Panihati como fuentes curadas",
            "whatsapp": "borradores internos; broadcasts requieren aprobación explícita",
        },
        "status": "LIVE",
    },
    "temple_operations": {
        "label": "Operaciones del templo",
        "actions": [
            "Horarios arati / programas",
            "Tareas mantenimiento y limpieza",
            "Contratos visitantes / residentes / voluntarios largo plazo",
            "Inventario utensilios y deity care checklist",
        ],
        "reuse": {
            "memory": "daily_life_current_state + ralfia_memory_items",
            "ops": "ralfia_ops_tasks + list_ops_tasks",
            "contacts": "ops_contacts con tags resident, visitor, contractor",
            "documents": "document_engine ent_iskcon",
        },
        "status": "NOT_READY",
    },
    "community_contacts": {
        "label": "Contactos comunitarios",
        "actions": [
            "Import CSV Google Contacts → ent_iskcon",
            "Voluntarios, donantes, devotos, proveedores",
            "Grupos WhatsApp comunitarios",
        ],
        "reuse": {
            "import": "import_google_contacts_csv(path, entity_id=ent_iskcon)",
            "list": "list_contacts(entity_id=ent_iskcon), list_ops_contacts",
            "link": "link_contact_entities",
            "whatsapp": "save_whatsapp_group, list_whatsapp_groups",
        },
        "status": "LIVE",
    },
}


def capabilities_summary() -> dict[str, Any]:
    return {
        "entity_id": ENTITY_ID,
        "project": PROJECT,
        "domains": ISKCON_DOMAINS,
        "entry_agent": "AG-52_ISKCON_OPS",
        "profile_mcp": "iskcon_ops",
        "vertical_repo": "inneros_core/companies/iskcon/ (canónico; no usar carpetas legacy en /projects para operación viva)",
        "entity_yaml": "inneros_core/companies/iskcon/config/entity.yaml",
        "send_policy": "WhatsApp/publicación siempre en borrador hasta aprobación humana",
    }
