"""Acceso a MongoDB — fuente de verdad operativa PC Doctor.

Esquema canónico v2: docs/ESQUEMA_MONGODB_DBxx.md
Legacy v1 (inspections, quote_headers): sigue soportado; migrar con scripts/migrate_v1_to_v2.py
"""

from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient

from config import MONGO_DB, MONGO_URI
from tools.schema import ensure_all_indexes as _ensure_all_indexes
from tools.schema import new_id

_client: MongoClient | None = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI)
    return _client[MONGO_DB]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes():
    _ensure_all_indexes(get_db())


def lookup_client_by_ruc(ruc: str) -> dict | None:
    return get_db().clients.find_one({"ruc": ruc}, {"_id": 0})


def create_client(data: dict) -> dict:
    from tools.schema import ensure_client_hub

    db = get_db()
    from tools.client_sanitize import normalize_tax_id_field, valid_tax_id

    ruc = normalize_tax_id_field(data.get("ruc"))
    if not valid_tax_id(ruc):
        raise ValueError("RUC/cédula inválido o vacío")
    data = {**data, "ruc": ruc}
    existing = db.clients.find_one({"ruc": ruc}, {"_id": 0})
    client_id = (existing or {}).get("client_id") or new_id("cli")
    doc = {
        "client_id": client_id,
        "ruc": data["ruc"],
        "cedula": data.get("cedula"),
        "name": data.get("name", ""),
        "trade_name": data.get("trade_name", ""),
        "address": data.get("address", ""),
        "city": data.get("city", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "legal_rep": data.get("legal_rep", ""),
        "activity": data.get("activity", ""),
        "estado": data.get("estado", "Cliente"),
        "hub_ready": bool((existing or {}).get("hub_ready")),
        "hub_id": (existing or {}).get("hub_id"),
        "created_at": (existing or {}).get("created_at") or _now(),
        "updated_at": _now(),
    }
    db.clients.update_one({"ruc": doc["ruc"]}, {"$set": doc}, upsert=True)
    if not doc["hub_id"]:
        hub = ensure_client_hub(db, client_id, doc["name"])
        doc["hub_id"] = hub["hub_id"]
        doc["hub_ready"] = True
    return db.clients.find_one({"ruc": doc["ruc"]}, {"_id": 0})


def create_inspection(inspection_id: str, raw_input: str, ruc: str | None = None) -> dict:
    db = get_db()
    doc = {
        "inspection_id": inspection_id,
        "ruc": ruc,
        "raw_input": raw_input,
        "status": "open",
        "findings": [],
        "media": [],
        "pending_tasks": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    from pymongo.errors import DuplicateKeyError

    try:
        db.inspections.insert_one(doc)
    except DuplicateKeyError:
        existing = db.inspections.find_one({"inspection_id": inspection_id}, {"_id": 0})
        if existing:
            return existing
        raise
    doc.pop("_id", None)
    return doc


def get_inspection(inspection_id: str) -> dict | None:
    return get_db().inspections.find_one({"inspection_id": inspection_id}, {"_id": 0})


def update_inspection(inspection_id: str, patch: dict) -> dict | None:
    patch["updated_at"] = _now()
    get_db().inspections.update_one({"inspection_id": inspection_id}, {"$set": patch})
    return get_inspection(inspection_id)


def save_findings(inspection_id: str, findings: list[dict], pending_tasks: list[str]) -> dict | None:
    return update_inspection(
        inspection_id,
        {"findings": findings, "pending_tasks": pending_tasks, "status": "documented"},
    )


def save_report(inspection_id: str, report: dict) -> dict:
    db = get_db()
    doc = {
        "inspection_id": inspection_id,
        **report,
        "created_at": _now(),
    }
    db.reports.update_one({"inspection_id": inspection_id}, {"$set": doc}, upsert=True)
    doc.pop("_id", None)
    return doc


def save_quote(inspection_id: str, quote: dict) -> dict:
    db = get_db()
    header = {
        "inspection_id": inspection_id,
        "client_ruc": quote.get("client_ruc"),
        "scope": quote.get("scope", ""),
        "subtotal": quote.get("subtotal", 0),
        "iva": quote.get("iva", 0),
        "total": quote.get("total", 0),
        "currency": "USD",
        "status": "draft",
        "created_at": _now(),
    }
    db.quote_headers.update_one({"inspection_id": inspection_id}, {"$set": header}, upsert=True)
    lines = quote.get("lines", [])
    if lines:
        db.quote_lines.delete_many({"inspection_id": inspection_id})
        for i, line in enumerate(lines, 1):
            db.quote_lines.insert_one(
                {
                    "inspection_id": inspection_id,
                    "line_no": i,
                    **line,
                }
            )
    return {**header, "lines": lines}


def search_inventory(query: str, limit: int = 10) -> list[dict]:
    db = get_db()
    regex = {"$regex": query, "$options": "i"}
    cur = db.inventory.find(
        {"$or": [{"name": regex}, {"sku": regex}, {"category": regex}]},
        {"_id": 0},
    ).limit(limit)
    return list(cur)


def seed_inventory_if_empty():
    db = get_db()
    if db.inventory.count_documents({}) > 0:
        return
    items = [
        {"sku": "CAM-IP-2MP", "name": "Cámara IP 2MP", "unit_price": 85.0, "category": "cctv"},
        {"sku": "CABLE-UTP", "name": "Cable UTP por metro", "unit_price": 0.8, "category": "cableado"},
        {"sku": "SW-8P", "name": "Switch 8 puertos", "unit_price": 45.0, "category": "red"},
        {"sku": "RACK-ORD", "name": "Ordenamiento de rack", "unit_price": 120.0, "category": "servicio"},
        {"sku": "MANO-OBRA", "name": "Mano de obra técnica (hora)", "unit_price": 25.0, "category": "servicio"},
    ]
    db.inventory.insert_many(items)


def log_action(agent: str, action: str, payload: dict[str, Any] | None = None):
    entry = {
        "agent": agent,
        "action": action,
        "payload": payload or {},
        "at": _now(),
    }
    db = get_db()
    db.audit_log.insert_one(entry)
    db.ai_provenance.insert_one(
        {
            "actor": f"agente:{agent}",
            "modelo": None,
            "fuente": "swarm-os",
            "accion": action,
            "target_type": (payload or {}).get("target_type"),
            "target_id": (payload or {}).get("target_id") or (payload or {}).get("inspection_id"),
            "payload": payload or {},
            "at": _now(),
        }
    )
