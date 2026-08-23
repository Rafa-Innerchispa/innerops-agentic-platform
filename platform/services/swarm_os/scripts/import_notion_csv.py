#!/usr/bin/env python3
"""Importa CSV exportados de Notion → MongoDB (DB04, DB13, DB25, DB26)."""

from __future__ import annotations

import csv
import glob
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.mongo import get_db  # noqa: E402
from tools.schema import ensure_client_hub, new_id  # noqa: E402

import os

NOTION_EXPORT_BASE = Path(
    os.environ.get(
        "NOTION_EXPORT_DIR",
        "/home/rlopez/data/notion_export",
    )
)
# Fallback legacy si aún no migraste
if not NOTION_EXPORT_BASE.exists():
    _legacy = Path("/home/rlopez/backups/20260518_032357/ai-server-v2/n8n/notion_data")
    if _legacy.exists():
        NOTION_EXPORT_BASE = _legacy


def _now():
    return datetime.now(timezone.utc)


def _find_csv(db_code: str) -> Path:
    matches = glob.glob(str(NOTION_EXPORT_BASE / f"**/{db_code}*all.csv"), recursive=True)
    if not matches:
        matches = glob.glob(str(NOTION_EXPORT_BASE / f"**/{db_code}*.csv"), recursive=True)
    if not matches:
        raise FileNotFoundError(f"No CSV for {db_code}")
    # Prefer _all.csv
    for m in matches:
        if m.endswith("_all.csv"):
            return Path(m)
    return Path(matches[0])


def _money(val: str) -> float:
    if not val or not str(val).strip():
        return 0.0
    s = re.sub(r"[^\d.,-]", "", str(val))
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _bool(val: str) -> bool:
    return str(val).strip().lower() in ("yes", "sí", "si", "true", "1", "checked")


def import_db25_suppliers(db) -> int:
    path = _find_csv("DB25")
    n = 0
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("Nombre del proveedor") or "").strip()
            if not name:
                continue
            supplier_id = new_id("sup")
            doc = {
                "supplier_id": supplier_id,
                "nombre": name,
                "ruc": (row.get("RUC o ID fiscal") or row.get("RUC") or "").strip(),
                "email": (row.get("Email") or "").strip(),
                "phone": (row.get("Teléfono") or "").strip(),
                "ciudad": (row.get("Ciudad") or "").strip(),
                "pais": (row.get("País") or "").strip(),
                "estado": (row.get("Estado") or "Activo").strip(),
                "categoria": [c.strip() for c in (row.get("Categoría") or "").split(",") if c.strip()],
                "calificacion": (row.get("Calificación") or "").strip(),
                "notion_import": True,
                "imported_at": _now(),
            }
            db.suppliers.update_one(
                {"nombre": name},
                {"$set": doc, "$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
            n += 1
    return n


def import_db26_inventory(db) -> int:
    path = _find_csv("DB26")
    suppliers_by_name = {s["nombre"]: s["supplier_id"] for s in db.suppliers.find({}, {"nombre": 1, "supplier_id": 1})}
    n = 0
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("Nombre del producto") or "").strip()
            if not name:
                continue
            sku_raw = (row.get("SKU o Código") or row.get("Código proveedor") or "").strip()
            item_code = (row.get("Código ítem") or "").strip() or f"PCD-ITM-IMP-{n+1:04d}"
            sku = sku_raw or item_code
            if db.inventory_items.find_one({"sku": sku, "item_code": {"$ne": item_code}}):
                sku = f"{sku}-{item_code[-4:]}"
            prov_name = (row.get("Proveedor principal") or "").strip()
            # Notion relation often empty in CSV — name in separate col sometimes missing
            supplier_id = suppliers_by_name.get(prov_name) if prov_name else None
            doc = {
                "item_code": item_code,
                "sku": sku or item_code,
                "nombre": name,
                "categoria": [c.strip() for c in (row.get("Categoría") or "").split(",") if c.strip()],
                "marca": (row.get("Marca") or "").strip(),
                "modelo": (row.get("Modelo") or "").strip(),
                "costo_proveedor": _money(row.get("Costo proveedor", "")),
                "precio_sugerido": _money(row.get("Precio sugerido venta", "")),
                "stock_actual": float(row.get("Stock actual") or 0) if row.get("Stock actual") else 0,
                "disponible_cotizar": _bool(row.get("Disponible para cotizar", "Yes")),
                "estado_producto": (row.get("Estado producto") or "Activo").strip(),
                "supplier_id": supplier_id,
                "notion_import": True,
                "imported_at": _now(),
            }
            db.inventory_items.update_one(
                {"item_code": item_code},
                {"$set": doc, "$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
            n += 1
    return n


def import_db13_catalog(db) -> int:
    path = _find_csv("DB13")
    n = 0
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("Nombre del producto") or "").strip()
            if not name:
                continue
            code = (row.get("Código") or "").strip() or f"PCD-SRV-IMP-{n+1:04d}"
            doc = {
                "code": code,
                "nombre": name,
                "marca": (row.get("Marca") or "PC Doctor").strip(),
                "tipo": (row.get("Tipo") or "Servicio").strip(),
                "linea_negocio": (row.get("Línea de negocio") or "").strip(),
                "estado": (row.get("Estado") or "Activo").strip(),
                "descripcion_comercial": (row.get("Descripción comercial") or "").strip(),
                "precio_sugerido": _money(row.get("Precio sugerido", "")),
                "costo_base": _money(row.get("Costo base estimado", "")),
                "margen_objetivo_pct": _money(row.get("Margen objetivo %", "")),
                "notion_import": True,
                "imported_at": _now(),
            }
            db.catalog_products.update_one(
                {"code": code},
                {"$set": doc, "$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
            n += 1
    return n


def import_db04_clients(db) -> int:
    path = _find_csv("DB04")
    n = 0
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("Nombre") or "").strip()
            ruc = (row.get("RUC") or "").strip()
            if not name:
                continue
            existing = db.clients.find_one({"ruc": ruc}) if ruc else db.clients.find_one({"name": name})
            client_id = (existing or {}).get("client_id") or new_id("cli")
            doc = {
                "client_id": client_id,
                "name": name,
                "city": (row.get("Ciudad") or "").strip(),
                "address": (row.get("Dirección") or "").strip(),
                "email": (row.get("Email contacto") or "").strip(),
                "email_documentos": (row.get("Email documentos electrónicos") or "").strip(),
                "estado": (row.get("Estado") or "Cliente").strip(),
                "pais": (row.get("País") or "ecu").strip(),
                "notas": (row.get("Notas") or "").strip(),
                "notion_import": True,
                "imported_at": _now(),
                "updated_at": _now(),
            }
            if ruc:
                doc["ruc"] = ruc
            key = {"ruc": ruc} if ruc else {"name": name}
            db.clients.update_one(key, {"$set": doc, "$setOnInsert": {"created_at": _now(), "hub_ready": False}}, upsert=True)
            cl = db.clients.find_one(key, {"client_id": 1, "hub_id": 1, "name": 1})
            if cl and not cl.get("hub_id"):
                ensure_client_hub(db, cl["client_id"], name)
            n += 1
    return n


def main():
    db = get_db()
    print("Importando desde Notion CSV...")
    s = import_db25_suppliers(db)
    print(f"  DB25 suppliers: {s}")
    i = import_db26_inventory(db)
    print(f"  DB26 inventory_items: {i}")
    c = import_db13_catalog(db)
    print(f"  DB13 catalog_products: {c}")
    cl = import_db04_clients(db)
    print(f"  DB04 clients: {cl}")
    print("Importación completada.")


if __name__ == "__main__":
    main()
