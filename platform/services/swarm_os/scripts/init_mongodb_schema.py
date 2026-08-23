#!/usr/bin/env python3
"""
Crea TODA la estructura MongoDB OS Central (DB01–DB52).

Qué hace:
  1. Crea cada colección si no existe
  2. Crea índices
  3. Registra metadatos en _schema_registry (mapeo DBxx + relaciones)
  4. Siembra secuenciales DB40 (PCD, año actual, en 0)
  5. Siembra reglas DB41 de ejemplo

NO mueve datos viejos. Para eso existe migrate_v1_to_v2.py (opcional).

Uso:
  cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
  source venv/bin/activate
  python scripts/init_mongodb_schema.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.mongo import get_db  # noqa: E402
from tools.schema import (  # noqa: E402
    COLLECTIONS,
    ENTITY_PREFIX,
    SERIAL_TYPES,
    ensure_all_indexes,
    new_id,
)

# Metadatos por DBxx — relaciones se completan cuando Rafael pase la lógica
SCHEMA_REGISTRY: list[dict] = [
    {"dbxx": "DB01", "collection": "entities", "name": "Entidades", "relations": ["DB05 contacts", "DB30 accounts"]},
    {"dbxx": "DB02", "collection": "divisions", "name": "Divisiones", "relations": ["DB01 entities", "DB06 offers"]},
    {"dbxx": "DB03", "collection": "buyer_personas", "name": "Buyer Personas", "relations": ["DB02 divisions", "DB17 avatars"]},
    {"dbxx": "DB04", "collection": "clients", "name": "Instituciones y Clientes", "relations": ["DB05 contacts", "HUB client_hubs", "DB08 projects"]},
    {"dbxx": "DB05", "collection": "contacts", "name": "Contactos", "relations": ["DB04 clients", "DB01 entities"]},
    {"dbxx": "DB06", "collection": "offers", "name": "Ofertas y Soluciones", "relations": ["DB02 divisions", "DB07 stacks", "DB03 buyer_personas"]},
    {"dbxx": "DB07", "collection": "stacks", "name": "Stacks Validados", "relations": []},
    {"dbxx": "DB08", "collection": "projects", "name": "Proyectos", "relations": ["DB04 clients", "DB05 contacts", "DB27 quotes", "DB32 invoices", "DB29 works"]},
    {"dbxx": "DB09", "collection": "assets", "name": "Inventario y Activos", "relations": ["DB01 entities", "DB04 clients", "DB08 projects"]},
    {"dbxx": "DB10", "collection": "research_lines", "name": "Research Lines", "relations": ["DB01 entities", "DB08 projects"]},
    {"dbxx": "DB11", "collection": "ideas", "name": "Ideas y Viabilidad", "relations": ["DB08 projects", "DB02 divisions"]},
    {"dbxx": "DB12", "collection": "grants", "name": "Grants & Funding", "relations": ["DB35 grant_financials"]},
    {"dbxx": "DB13", "collection": "catalog_products", "name": "Catálogo Maestro Productos", "relations": ["DB38 quote_lines", "DB25 suppliers"]},
    {"dbxx": "DB14", "collection": "automations", "name": "OS Automation Registry", "relations": ["DB14 automations"]},
    {"dbxx": "DB15", "collection": "editorial_posts", "name": "OS Editorial", "relations": ["DB16 social_destinations", "DB23 campaigns"]},
    {"dbxx": "DB16", "collection": "social_destinations", "name": "Destinos Sociales", "relations": []},
    {"dbxx": "DB17", "collection": "avatars", "name": "Avatares InnerSpark", "relations": ["DB03 buyer_personas", "DB13 catalog_products"]},
    {"dbxx": "DB18", "collection": "digital_assets_channels", "name": "Activos Digitales y Canales", "relations": ["DB01 entities", "DB16 social_destinations"]},
    {"dbxx": "DB19", "collection": "ecosystem_metrics", "name": "Métricas Salud Ecosistema", "relations": ["DB01 entities", "DB02 divisions"]},
    {"dbxx": "DB20", "collection": "incidents", "name": "Incidentes y Decisiones", "relations": ["DB14 automations", "DB18 digital_assets_channels"]},
    {"dbxx": "DB21", "collection": "media_library", "name": "Biblioteca Assets Media", "relations": ["DB15 editorial_posts", "DB23 campaigns"]},
    {"dbxx": "DB22", "collection": "utm_links", "name": "UTM y Links", "relations": ["DB13 catalog_products", "DB15 editorial_posts"]},
    {"dbxx": "DB23", "collection": "campaigns", "name": "Campañas", "relations": ["DB13 catalog_products", "DB15 editorial_posts"]},
    {"dbxx": "DB24", "collection": "experiments", "name": "Experimentos A/B", "relations": ["DB23 campaigns"]},
    {"dbxx": "DB25", "collection": "suppliers", "name": "Proveedores", "relations": ["DB26 inventory_items", "DB38 quote_lines"]},
    {"dbxx": "DB26", "collection": "inventory_items", "name": "Inventario Hardware PC Doctor", "relations": ["DB25 suppliers", "DB38 quote_lines", "DB28 purchase_prices"]},
    {"dbxx": "DB27", "collection": "quotes", "name": "Cotizaciones", "relations": ["DB04 clients", "DB38 quote_lines", "DB42 sop_visits", "DB45 technical_reports"]},
    {"dbxx": "DB28", "collection": "purchase_prices", "name": "Compras / Historial Precios", "relations": ["DB26 inventory_items", "DB25 suppliers"]},
    {"dbxx": "DB29", "collection": "works", "name": "Trabajos Día a Día", "relations": ["DB04 clients", "DB27 quotes", "DB42 sop_visits"]},
    {"dbxx": "DB30", "collection": "accounts", "name": "Cuentas Financieras", "relations": ["DB01 entities", "DB31 transactions"]},
    {"dbxx": "DB31", "collection": "transactions", "name": "Transacciones Financieras", "relations": ["DB30 accounts", "DB32 invoices"]},
    {"dbxx": "DB32", "collection": "invoices", "name": "Facturas", "relations": ["DB04 clients", "DB27 quotes", "DB08 projects"]},
    {"dbxx": "DB33", "collection": "expenses", "name": "Gastos Operativos", "relations": ["DB25 suppliers", "DB30 accounts"]},
    {"dbxx": "DB34", "collection": "payment_processors", "name": "Procesadores de Pago", "relations": ["DB01 entities"]},
    {"dbxx": "DB35", "collection": "grant_financials", "name": "Grants Tracking Financiero", "relations": ["DB12 grants", "DB08 projects", "DB30 accounts"]},
    {"dbxx": "DB36", "collection": "cashflow_budgets", "name": "Cash Flow y Budget", "relations": ["DB01 entities"]},
    {"dbxx": "DB37", "collection": "productivity_metrics", "name": "Productivity Metrics", "relations": ["DB08 projects"]},
    {"dbxx": "DB38", "collection": "quote_lines", "name": "Líneas de Cotización", "relations": ["DB27 quotes", "DB26 inventory_items", "DB13 catalog_products"]},
    {"dbxx": "DB39", "collection": "manuals", "name": "Manuales InnerSpark", "relations": ["DB13 catalog_products", "DB17 avatars"]},
    {"dbxx": "DB40", "collection": "serials", "name": "Secuenciales", "relations": ["DB27 quotes", "DB29 works", "DB42 sop_visits", "DB45 technical_reports"]},
    {"dbxx": "DB41", "collection": "verification_rules", "name": "Reglas Verificación Cotización", "relations": ["VAL validation_results"]},
    {"dbxx": "DB42", "collection": "sop_visits", "name": "Soporte / Visitas SOP", "relations": ["DB04 clients", "DB29 works", "DB45 technical_reports"]},
    {"dbxx": "DB43", "collection": "equipment_tickets", "name": "Recepciones Equipos", "relations": ["DB04 clients", "DB29 works", "DB32 invoices"]},
    {"dbxx": "DB44", "collection": "domains_hosting", "name": "Dominios y Hosting", "relations": ["DB04 clients", "DB51 domain_emails", "DB31 transactions"]},
    {"dbxx": "DB45", "collection": "technical_reports", "name": "Reportes Técnicos", "relations": ["DB42 sop_visits", "DB27 quotes", "DOC documents"]},
    {"dbxx": "DB46", "collection": "contracts", "name": "Contratos", "relations": ["DB04 clients", "DB27 quotes", "DB08 projects"]},
    {"dbxx": "DB47", "collection": "field_captures", "name": "Capturas Campo Editorial", "relations": ["DB29 works", "DB45 technical_reports"]},
    {"dbxx": "DB48", "collection": "editorial_pipeline", "name": "Pipeline Editorial Multicanal", "relations": ["DB47 field_captures", "DB49 editorial_campaigns"]},
    {"dbxx": "DB49", "collection": "editorial_campaigns", "name": "Campañas Editoriales", "relations": ["DB23 campaigns", "DB48 editorial_pipeline"]},
    {"dbxx": "DB50", "collection": "visual_prompts", "name": "Biblioteca Prompts Visuales", "relations": ["DB48 editorial_pipeline"]},
    {"dbxx": "DB51", "collection": "domain_emails", "name": "Correos por Dominio", "relations": ["DB44 domains_hosting"]},
    {"dbxx": "DB52", "collection": "ai_provenance", "name": "AI Provenance Log", "relations": ["todas las colecciones operativas"]},
    {"dbxx": "HUB", "collection": "client_hubs", "name": "Hub Cliente", "relations": ["DB04 clients"]},
    {"dbxx": "DOC", "collection": "documents", "name": "Documentos PDF-first", "relations": ["DB27 quotes", "DB45 technical_reports", "DB42 sop_visits"]},
    {"dbxx": "VAL", "collection": "validation_results", "name": "Resultados Validación", "relations": ["DB41 verification_rules"]},
    {"dbxx": "MED", "collection": "media_assets", "name": "Media por Visita", "relations": ["DB42 sop_visits"]},
    # Legacy v1 — se mantiene hasta deprecar
    {"dbxx": "LEGACY", "collection": "inspections", "name": "(legacy) Inspecciones mezcladas", "relations": ["migrar a DB42+DB45"]},
    {"dbxx": "LEGACY", "collection": "reports", "name": "(legacy) Reportes por inspection_id", "relations": ["migrar a DB45"]},
    {"dbxx": "LEGACY", "collection": "quote_headers", "name": "(legacy) Cabeceras cotización", "relations": ["migrar a DB27 quotes"]},
    {"dbxx": "LEGACY", "collection": "inventory", "name": "(legacy) Inventario demo", "relations": ["migrar a DB26 inventory_items"]},
    {"dbxx": "LEGACY", "collection": "audit_log", "name": "(legacy) Log agentes", "relations": ["migrar a DB52 ai_provenance"]},
]


def _now():
    return datetime.now(timezone.utc)


def ensure_collections(db) -> list[str]:
    """Crea colecciones vacías si no existen."""
    existing = set(db.list_collection_names())
    all_names = set(COLLECTIONS.values()) | {r["collection"] for r in SCHEMA_REGISTRY}
    all_names.add("_schema_registry")
    created = []
    for name in sorted(all_names):
        if name not in existing:
            db.create_collection(name)
            created.append(name)
    return created


def seed_serials(db) -> int:
    yy = _now().year % 100
    n = 0
    for entity in ENTITY_PREFIX:
        for doc_type in SERIAL_TYPES:
            res = db.serials.update_one(
                {"entity": entity, "doc_type": doc_type, "year": yy},
                {
                    "$setOnInsert": {
                        "entity": entity,
                        "doc_type": doc_type,
                        "year": yy,
                        "last_seq": 0,
                        "prefix": entity,
                        "created_at": _now(),
                    }
                },
                upsert=True,
            )
            if res.upserted_id:
                n += 1
    return n


def seed_verification_rules(db) -> int:
    if db.verification_rules.count_documents({}) > 0:
        return 0
    rules = [
        {
            "rule_id": new_id("rule"),
            "activa": True,
            "severidad": "Bloqueante (no enviar)",
            "aplica_a": ["DB38 (líneas)"],
            "condicion": "Cotización sin líneas",
            "verificar": "count(quote_lines where quote_id=X) >= 1",
            "accion_si_falta": "Agregar líneas antes de enviar",
        },
        {
            "rule_id": new_id("rule"),
            "activa": True,
            "severidad": "Bloqueante (no enviar)",
            "aplica_a": ["PDF-first"],
            "condicion": "Cliente sin hub",
            "verificar": "client.hub_ready == true",
            "accion_si_falta": "Crear hub cliente",
        },
        {
            "rule_id": new_id("rule"),
            "activa": True,
            "severidad": "Alta",
            "aplica_a": ["DB38 (líneas)"],
            "condicion": "Descuadre totales cabecera vs líneas",
            "verificar": "quote.total == sum(quote_lines) + IVA",
            "accion_si_falta": "Recalcular desde DB38",
        },
    ]
    db.verification_rules.insert_many(rules)
    return len(rules)


def seed_schema_registry(db) -> int:
    reg = db["_schema_registry"]
    reg.delete_many({})
    now = _now()
    docs = []
    for entry in SCHEMA_REGISTRY:
        docs.append(
            {
                **entry,
                "status": "ready",
                "document_count": db[entry["collection"]].count_documents({}),
                "initialized_at": now,
            }
        )
    reg.insert_many(docs)
    return len(docs)


FLOW_REGISTRY: list[dict] = [
    {
        "flow_id": "onboarding_cliente",
        "name": "Onboarding Cliente",
        "steps": ["DB04 clients", "DB05 contacts", "client_hubs"],
        "gates": ["anti_duplicacion_cliente", "hub_first"],
    },
    {
        "flow_id": "campo_pc_doctor",
        "name": "Campo PC Doctor",
        "steps": ["DB42 sop_visits", "MED media_assets", "DB45 technical_reports", "DB27 quotes", "DB38 quote_lines", "DOC documents"],
        "gates": ["hub_first", "db38_matematica", "pdf_first", "anti_placeholders"],
    },
    {
        "flow_id": "listo_para_enviar",
        "name": "Gate Listo para enviar",
        "steps": ["validar documents", "validar DB38", "validar hub"],
        "gates": ["hub_first", "db38_matematica", "pdf_first", "anti_placeholders"],
    },
    {
        "flow_id": "cobro_real",
        "name": "Cobro / Finanzas",
        "steps": ["DB29 works", "DB32 invoices", "DB31 transactions", "DB30 accounts"],
        "gates": ["dinero_real_db31"],
    },
    {
        "flow_id": "editorial_caso_real",
        "name": "Editorial desde ejecución",
        "steps": ["DB29/DB45", "DB47 field_captures", "DB48 editorial_pipeline", "DB49 editorial_campaigns"],
        "gates": ["no_publicar_desde_cotizacion"],
    },
]


def seed_flow_registry(db) -> int:
    flows = db["_flow_registry"]
    flows.delete_many({})
    now = _now()
    docs = [{**f, "initialized_at": now} for f in FLOW_REGISTRY]
    flows.insert_many(docs)
    return len(docs)


def main() -> None:
    db = get_db()
    print(f"Base de datos: {db.name}")

    created = ensure_collections(db)
    print(f"Colecciones creadas: {len(created)}")
    if created:
        for c in created:
            print(f"  + {c}")

    ensure_all_indexes(db)
    print("Índices: OK")

    serials = seed_serials(db)
    print(f"Secuenciales DB40 sembrados (nuevos): {serials}")

    rules = seed_verification_rules(db)
    print(f"Reglas DB41 sembradas: {rules}")

    reg = seed_schema_registry(db)
    print(f"Registro _schema_registry: {reg} entradas")

    flows = seed_flow_registry(db)
    print(f"Registro _flow_registry: {flows} flujos")

    total = len(db.list_collection_names())
    print(f"\nTotal colecciones en MongoDB: {total}")
    print("Listo. Puedes pasar la lógica de relaciones; se actualizará _schema_registry.")


if __name__ == "__main__":
    main()
