"""
Esquema MongoDB v2 — mapeo DBxx OS Central.

Colecciones, índices y secuenciales (DB40).
Fuente de verdad documentada en docs/ESQUEMA_MONGODB_DBxx.md
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

# --- Mapeo DBxx → colección Mongo ---
COLLECTIONS = {
    "DB01": "entities",
    "DB02": "divisions",
    "DB03": "buyer_personas",
    "DB04": "clients",
    "DB05": "contacts",
    "DB06": "offers",
    "DB07": "stacks",
    "DB08": "projects",
    "DB09": "assets",
    "DB10": "research_lines",
    "DB11": "ideas",
    "DB12": "grants",
    "DB13": "catalog_products",
    "DB14": "automations",
    "DB15": "editorial_posts",
    "DB16": "social_destinations",
    "DB17": "avatars",
    "DB18": "digital_assets_channels",
    "DB19": "ecosystem_metrics",
    "DB20": "incidents",
    "DB21": "media_library",
    "DB22": "utm_links",
    "DB23": "campaigns",
    "DB24": "experiments",
    "DB25": "suppliers",
    "DB26": "inventory_items",
    "DB27": "quotes",
    "DB28": "purchase_prices",
    "DB29": "works",
    "DB30": "accounts",
    "DB31": "transactions",
    "DB32": "invoices",
    "DB33": "expenses",
    "DB34": "payment_processors",
    "DB35": "grant_financials",
    "DB36": "cashflow_budgets",
    "DB37": "productivity_metrics",
    "DB38": "quote_lines",
    "DB39": "manuals",
    "DB40": "serials",
    "DB41": "verification_rules",
    "DB42": "sop_visits",
    "DB43": "equipment_tickets",
    "DB44": "domains_hosting",
    "DB45": "technical_reports",
    "DB46": "contracts",
    "DB47": "field_captures",
    "DB48": "editorial_pipeline",
    "DB49": "editorial_campaigns",
    "DB50": "visual_prompts",
    "DB51": "domain_emails",
    "DB52": "ai_provenance",
    # Extensiones locales (Playbook)
    "HUB": "client_hubs",
    "DOC": "documents",
    "VAL": "validation_results",
    "MED": "media_assets",
}

# Tipos de secuencial DB40
SERIAL_TYPES = frozenset({"COT", "TRB", "INF", "RPT", "FAC", "INV", "SOP", "REC", "PRY"})

ENTITY_PREFIX = {
    "PCD": "PC Doctor",
    "IS": "InnerSpark",
    "ISK": "ISKCON",
    "RFL": "RalphIA",
}

# Anchura del número según tipo (SOP usa 6 dígitos en Notion)
SERIAL_WIDTH = {
    "SOP": 6,
    "default": 4,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_all_indexes(db) -> None:
    """Crea índices v1 (legacy) + v2 (canónico)."""
    # --- Legacy v1 ---
    db.clients.create_index("ruc", unique=True, sparse=True)
    db.inspections.create_index("inspection_id", unique=True)
    db.inventory.create_index("sku", unique=True, sparse=True)

    # --- v2 núcleo Fase A ---
    db.client_hubs.create_index("hub_id", unique=True)
    db.client_hubs.create_index("client_id")

    db.contacts.create_index("contact_id", unique=True)
    db.contacts.create_index("client_id")

    db.clients.create_index("client_id", unique=True, sparse=True)

    db.sop_visits.create_index("visit_id", unique=True)
    db.sop_visits.create_index("legacy_inspection_id", sparse=True)
    db.sop_visits.create_index([("client_id", 1), ("fecha", -1)])

    db.technical_reports.create_index("report_id", unique=True)
    db.technical_reports.create_index("visit_id")
    db.technical_reports.create_index("legacy_inspection_id", sparse=True)

    db.media_assets.create_index("asset_id", unique=True)
    db.media_assets.create_index("visit_id")

    db.quotes.create_index("quote_id", unique=True)
    db.quotes.create_index("code", unique=True, sparse=True)
    db.quotes.create_index("legacy_inspection_id", sparse=True)
    db.quotes.create_index([("client_id", 1), ("created_at", -1)])

    db.quote_lines.create_index([("quote_id", 1), ("line_no", 1)], unique=True)
    db.quote_lines.create_index("legacy_inspection_id", sparse=True)

    db.catalog_products.create_index("code", unique=True, sparse=True)
    db.inventory_items.create_index("item_code", unique=True, sparse=True)
    db.inventory_items.create_index("sku", unique=True, sparse=True)

    db.serials.create_index([("entity", 1), ("doc_type", 1), ("year", 1)], unique=True)

    db.verification_rules.create_index("rule_id", unique=True)
    db.validation_results.create_index([("target_type", 1), ("target_id", 1)])

    db.documents.create_index("document_id", unique=True)
    db.documents.create_index([("target_type", 1), ("target_id", 1)])

    db.ai_provenance.create_index("at")
    db.ai_provenance.create_index([("target_type", 1), ("target_id", 1)])

    db.works.create_index("work_id", unique=True)
    db.works.create_index("code", unique=True, sparse=True)

    # --- Resto DBxx (Fase B–E) ---
    _id_collections = [
        ("entities", "entity_id"),
        ("divisions", "division_id"),
        ("buyer_personas", "persona_id"),
        ("offers", "offer_id"),
        ("stacks", "stack_id"),
        ("projects", "project_id"),
        ("assets", "asset_id"),
        ("research_lines", "line_id"),
        ("ideas", "idea_id"),
        ("grants", "grant_id"),
        ("automations", "automation_id"),
        ("editorial_posts", "post_id"),
        ("social_destinations", "destination_id"),
        ("avatars", "avatar_id"),
        ("digital_assets_channels", "channel_asset_id"),
        ("ecosystem_metrics", "metric_id"),
        ("incidents", "incident_id"),
        ("media_library", "library_asset_id"),
        ("utm_links", "link_id"),
        ("campaigns", "campaign_id"),
        ("experiments", "experiment_id"),
        ("suppliers", "supplier_id"),
        ("purchase_prices", "purchase_id"),
        ("accounts", "account_id"),
        ("transactions", "transaction_id"),
        ("invoices", "invoice_id"),
        ("expenses", "expense_id"),
        ("payment_processors", "processor_id"),
        ("grant_financials", "grant_financial_id"),
        ("cashflow_budgets", "budget_id"),
        ("productivity_metrics", "productivity_id"),
        ("manuals", "manual_id"),
        ("equipment_tickets", "ticket_id"),
        ("domains_hosting", "domain_asset_id"),
        ("contracts", "contract_id"),
        ("field_captures", "capture_id"),
        ("editorial_pipeline", "pipeline_id"),
        ("editorial_campaigns", "editorial_campaign_id"),
        ("visual_prompts", "prompt_id"),
        ("domain_emails", "email_account_id"),
    ]
    for coll, id_field in _id_collections:
        db[coll].create_index(id_field, unique=True, sparse=True)

    # Índices de relación frecuentes
    db.projects.create_index("client_id")
    db.projects.create_index("code", sparse=True)
    db.works.create_index("client_id")
    db.works.create_index("visit_id")
    db.works.create_index("quote_id")
    db.suppliers.create_index("ruc", sparse=True)
    db.invoices.create_index("code", sparse=True)
    db.invoices.create_index("client_id")
    db.equipment_tickets.create_index("client_id", sparse=True)
    db.field_captures.create_index("work_id", sparse=True)
    db.purchase_prices.create_index([("inventory_item_id", 1), ("fecha", -1)], sparse=True)


def next_serial(db, entity: str, doc_type: str, year: int | None = None) -> dict[str, Any]:
    """
    DB40 — incremento atómico. Devuelve seq, code y componentes.

    entity: PCD | IS | ISK | RFL
    doc_type: COT | TRB | RPT | SOP | INV | ...
    """
    if doc_type not in SERIAL_TYPES:
        raise ValueError(f"doc_type inválido: {doc_type}")
    if entity not in ENTITY_PREFIX:
        raise ValueError(f"entity inválida: {entity}")

    yy = year if year is not None else _now().year % 100
    width = SERIAL_WIDTH.get(doc_type, SERIAL_WIDTH["default"])

    doc = db.serials.find_one_and_update(
        {"entity": entity, "doc_type": doc_type, "year": yy},
        {
            "$inc": {"last_seq": 1},
            "$setOnInsert": {
                "entity": entity,
                "doc_type": doc_type,
                "year": yy,
                "prefix": entity,
                "created_at": _now(),
            },
            "$set": {"updated_at": _now()},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = int(doc["last_seq"])
    code = f"{entity}-{doc_type}-{yy:02d}{seq:0{width}d}"
    return {
        "entity": entity,
        "doc_type": doc_type,
        "year": yy,
        "seq": seq,
        "code": code,
    }


def new_id(prefix: str) -> str:
    """ID opaco estable para documentos (no sustituye code DB40)."""
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ensure_client_hub(db, client_id: str, name: str = "") -> dict:
    """Hub-first: un hub por cliente."""
    existing = db.client_hubs.find_one({"client_id": client_id}, {"_id": 0})
    if existing:
        return existing
    hub = {
        "hub_id": new_id("hub"),
        "client_id": client_id,
        "name": name or f"Hub {client_id}",
        "ready": True,
        "sections": {
            "cotizaciones": [],
            "trabajos": [],
            "reportes": [],
            "pdfs_exportables": [],
            "infraestructura": [],
            "notas_internas": [],
        },
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.client_hubs.insert_one(hub)
    hub.pop("_id", None)
    db.clients.update_one(
        {"client_id": client_id},
        {"$set": {"hub_id": hub["hub_id"], "hub_ready": True}},
    )
    return hub
