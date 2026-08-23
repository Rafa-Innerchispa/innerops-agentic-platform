"""Empresas del ecosistema multi-marca (PC Doctor + InnerChispa)."""

from __future__ import annotations

from datetime import datetime, timezone

from tools.schema import new_id

DEFAULT_COMPANIES = [
    {
        "company_id": "pcdoctor",
        "slug": "pcdoctor",
        "legal_name": "PC Doctor S.A.",
        "brand_name": "PC Doctor",
        "tagline": "Soporte técnico, CCTV, redes y urbanizaciones",
        "logo_file": "logo_pcdoctor.png",
        "icon_file": "icon_pcdoctor.png",
        "colors": {"primary": "#1e3a8a", "secondary": "#dc2626", "accent": "#2563eb"},
        "active": True,
        "default_for_quotes": True,
    },
    {
        "company_id": "innerchispa",
        "slug": "innerchispa",
        "legal_name": "InnerChispa LLC",
        "brand_name": "InnerChispa / InnerSpark",
        "tagline": "IA local, RAG, automatización y desarrollo de sistemas",
        "logo_file": "logo_innerchispa.png",
        "icon_file": "logo_innerchispa.png",
        "colors": {"primary": "#7c3aed", "secondary": "#f59e0b", "accent": "#a855f7"},
        "active": True,
        "default_for_quotes": False,
    },
]

INNERCHISPA_CATALOG_SEED = [
    {
        "code": "IC-IA-001",
        "nombre": "Consultoría IA local — diagnóstico y arquitectura",
        "tipo": "servicio",
        "empresa": "innerchispa",
        "categoria": "IA / Consultoría",
        "precio_base": 450.0,
        "moneda": "USD",
        "descripcion": "Sesión de diagnóstico: modelos locales, RAG, costos y roadmap.",
    },
    {
        "code": "IC-IA-002",
        "nombre": "Implementación RAG (AnythingLLM + documentos)",
        "tipo": "servicio",
        "empresa": "innerchispa",
        "categoria": "IA / RAG",
        "precio_base": 1200.0,
        "moneda": "USD",
        "descripcion": "Indexación, workspace, prompts y entrega operativa en servidor local.",
    },
    {
        "code": "IC-IA-003",
        "nombre": "Agente CrewAI / flujo operativo a medida",
        "tipo": "servicio",
        "empresa": "innerchispa",
        "categoria": "IA / Agentes",
        "precio_base": 2500.0,
        "moneda": "USD",
        "descripcion": "Diseño e implementación de agentes conectados a tu MongoDB y gates.",
    },
    {
        "code": "IC-IA-004",
        "nombre": "Whisper — integración voz a texto en flujos",
        "tipo": "servicio",
        "empresa": "innerchispa",
        "categoria": "IA / Voz",
        "precio_base": 350.0,
        "moneda": "USD",
        "descripcion": "Dictado en campo, transcripción español, conexión con inspecciones.",
    },
    {
        "code": "IC-IA-005",
        "nombre": "Mantenimiento mensual servidor IA (RALF IA)",
        "tipo": "servicio",
        "empresa": "innerchispa",
        "categoria": "IA / Soporte",
        "precio_base": 180.0,
        "moneda": "USD",
        "descripcion": "Monitoreo, backups, actualizaciones Docker, portal y modelos.",
    },
    {
        "code": "IC-IA-006",
        "nombre": "Mini-ERP / OS Central (módulo adicional)",
        "tipo": "servicio",
        "empresa": "innerchispa",
        "categoria": "IA / Software",
        "precio_base": 1800.0,
        "moneda": "USD",
        "descripcion": "Nuevo módulo admin, PDF, integración n8n o catálogo multiempresa.",
    },
]


def _now():
    return datetime.now(timezone.utc)


def ensure_companies(db) -> None:
    for doc in DEFAULT_COMPANIES:
        doc = dict(doc)
        doc.setdefault("created_at", _now())
        doc["updated_at"] = _now()
        db.companies.update_one({"company_id": doc["company_id"]}, {"$set": doc}, upsert=True)


def seed_innerchispa_catalog(db) -> int:
    n = 0
    for item in INNERCHISPA_CATALOG_SEED:
        filt = {"code": item["code"]}
        if db.catalog_products.find_one(filt):
            continue
        doc = {**item, "created_at": _now(), "updated_at": _now(), "activo": True}
        db.catalog_products.insert_one(doc)
        n += 1
    return n
