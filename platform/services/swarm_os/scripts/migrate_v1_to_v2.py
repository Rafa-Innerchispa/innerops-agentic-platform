#!/usr/bin/env python3
"""
Migra datos legacy v1 → esquema v2 (idempotente).

Uso:
  cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
  source venv/bin/activate
  python scripts/migrate_v1_to_v2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.mongo import get_db  # noqa: E402
from tools.schema import ensure_all_indexes, ensure_client_hub, new_id, next_serial  # noqa: E402


def migrate_clients(db) -> int:
    n = 0
    for c in db.clients.find({}):
        patch = {}
        if not c.get("client_id"):
            patch["client_id"] = new_id("cli")
        cid = patch.get("client_id") or c["client_id"]
        if not c.get("hub_id"):
            ensure_client_hub(db, cid, c.get("name", ""))
            n += 1
        if patch:
            db.clients.update_one({"_id": c["_id"]}, {"$set": patch})
            n += 1
    return n


def migrate_inspections(db) -> int:
    n = 0
    for insp in db.inspections.find({}):
        iid = insp["inspection_id"]
        if db.sop_visits.find_one({"legacy_inspection_id": iid}):
            continue

        client_id = None
        ruc = insp.get("ruc")
        if ruc:
            cl = db.clients.find_one({"ruc": ruc})
            if cl:
                client_id = cl.get("client_id")
                if client_id and not cl.get("hub_id"):
                    ensure_client_hub(db, client_id, cl.get("name", ""))

        visit_id = new_id("vis")
        serial = next_serial(db, "PCD", "SOP")
        visit = {
            "visit_id": visit_id,
            "legacy_inspection_id": iid,
            "code": serial["code"],
            "entity": "PCD",
            "client_id": client_id,
            "fecha": insp.get("created_at"),
            "estado": "Cerrado" if insp.get("status") == "documented" else "En ejecución",
            "raw_input": insp.get("raw_input", ""),
            "findings": insp.get("findings", []),
            "pending_tasks": insp.get("pending_tasks", []),
            "created_at": insp.get("created_at"),
            "updated_at": insp.get("updated_at"),
        }
        db.sop_visits.insert_one(visit)

        report_legacy = db.reports.find_one({"inspection_id": iid}, {"_id": 0})
        report_id = new_id("rpt")
        r_serial = next_serial(db, "PCD", "RPT")
        report = {
            "report_id": report_id,
            "code": r_serial["code"],
            "visit_id": visit_id,
            "legacy_inspection_id": iid,
            "client_id": client_id,
            "estado": "Finalizado" if report_legacy else "Borrador",
            "findings": insp.get("findings", []),
            "pending_tasks": insp.get("pending_tasks", []),
            "created_at": insp.get("created_at"),
        }
        if report_legacy:
            for k, v in report_legacy.items():
                if k not in ("inspection_id", "_id"):
                    report[k] = v
        db.technical_reports.insert_one(report)

        for m in insp.get("media", []) or []:
            db.media_assets.insert_one(
                {
                    "asset_id": new_id("med"),
                    "visit_id": visit_id,
                    "legacy_inspection_id": iid,
                    **m,
                }
            )

        qh = db.quote_headers.find_one({"inspection_id": iid}, {"_id": 0})
        if qh and not db.quotes.find_one({"legacy_inspection_id": iid}):
            quote_id = new_id("qot")
            q_serial = next_serial(db, "PCD", "COT")
            quote = {
                "quote_id": quote_id,
                "code": q_serial["code"],
                "legacy_inspection_id": iid,
                "visit_id": visit_id,
                "report_id": report_id,
                "client_id": client_id,
                "estado": qh.get("status", "Borrador"),
                "moneda": qh.get("currency", "USD"),
                "subtotal": qh.get("subtotal", 0),
                "monto_iva": qh.get("iva", 0),
                "total": qh.get("total", 0),
                "scope": qh.get("scope", ""),
                "created_at": qh.get("created_at"),
            }
            db.quotes.insert_one(quote)
            for line in db.quote_lines.find({"inspection_id": iid}, {"_id": 0}):
                db.quote_lines.update_one(
                    {"legacy_inspection_id": iid, "line_no": line.get("line_no")},
                    {
                        "$set": {
                            "quote_id": quote_id,
                            "legacy_inspection_id": iid,
                            "tipo": line.get("tipo", "Otro"),
                            "descripcion": line.get("description") or line.get("descripcion", ""),
                            "cantidad": line.get("qty") or line.get("cantidad", 1),
                            "precio_unitario": line.get("unit_price") or line.get("precio_unitario", 0),
                            "subtotal_linea": line.get("subtotal") or line.get("subtotal_linea", 0),
                        }
                    },
                    upsert=True,
                )

        n += 1
    return n


def migrate_inventory(db) -> int:
    n = 0
    for item in db.inventory.find({}):
        sku = item.get("sku")
        if not sku or db.inventory_items.find_one({"sku": sku}):
            continue
        db.inventory_items.insert_one(
            {
                "item_code": item.get("item_code") or f"PCD-ITM-LEG-{sku}",
                "sku": sku,
                "nombre": item.get("name") or item.get("nombre", ""),
                "categoria": [item.get("category", "Otros")],
                "precio_sugerido": item.get("unit_price") or item.get("precio_sugerido", 0),
                "disponible_cotizar": True,
                "legacy": True,
            }
        )
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
            "verificar": "Al menos 1 línea en quote_lines",
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
            "condicion": "Descuadre totales",
            "verificar": "quote.total == sum(quote_lines.subtotal_linea) + IVA",
            "accion_si_falta": "Recalcular desde DB38",
        },
    ]
    db.verification_rules.insert_many(rules)
    return len(rules)


def main() -> None:
    db = get_db()
    ensure_all_indexes(db)
    print("Índices v2 OK")

    c = migrate_clients(db)
    print(f"Clientes/hubs tocados: {c}")

    i = migrate_inspections(db)
    print(f"Inspecciones migradas: {i}")

    inv = migrate_inventory(db)
    print(f"Ítems inventario migrados: {inv}")

    rules = seed_verification_rules(db)
    print(f"Reglas DB41 sembradas: {rules}")

    print("Migración v1→v2 completada (idempotente).")


if __name__ == "__main__":
    main()
