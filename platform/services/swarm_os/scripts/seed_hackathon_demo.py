#!/usr/bin/env python3
"""Idempotent hackathon demo seed — suppliers, quotes, visits, reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tools.companies import ensure_companies
from tools.gates import calc_quote_from_lines
from tools.schema import ensure_client_hub, new_id, next_serial


def _now():
    return datetime.now(timezone.utc)


def _db():
    from tools.mongo import get_db

    return get_db()


def _ensure_catalog(db) -> int:
    items = [
        {"code": "PRD-SW-PoE16", "nombre": "PoE switch 16-port Gigabit", "tipo": "producto", "precio_sugerido": 185, "empresa": "pcdoctor", "linea_negocio": "Redes", "estado": "Activo"},
        {"code": "PRD-CAM-IP4K", "nombre": "IP camera 4MP outdoor", "tipo": "producto", "precio_sugerido": 120, "empresa": "pcdoctor", "linea_negocio": "CCTV", "estado": "Activo"},
        {"code": "SRV-INST-CAM", "nombre": "Camera installation (per unit)", "tipo": "servicio", "precio_sugerido": 70, "empresa": "pcdoctor", "linea_negocio": "CCTV", "estado": "Activo"},
        {"code": "SRV-CABLEADO", "nombre": "Structured cabling per point", "tipo": "servicio", "precio_sugerido": 45, "empresa": "pcdoctor", "linea_negocio": "Cableado", "estado": "Activo"},
        {"code": "SRV-SOPORTE", "nombre": "On-site technical support (2h)", "tipo": "servicio", "precio_sugerido": 60, "empresa": "pcdoctor", "linea_negocio": "Soporte", "estado": "Activo"},
        {"code": "SRV-NVR-CONFIG", "nombre": "NVR/DVR configuration", "tipo": "servicio", "precio_sugerido": 55, "empresa": "innerchispa", "linea_negocio": "CCTV", "estado": "Activo"},
    ]
    n = 0
    for it in items:
        if db.catalog_products.find_one({"code": it["code"]}):
            db.catalog_products.update_one({"code": it["code"]}, {"$set": {**it, "updated_at": _now()}})
        else:
            db.catalog_products.insert_one({**it, "created_at": _now(), "updated_at": _now()})
        n += 1
    return n


def _dedupe_212_quotes(db) -> int:
    """Remove duplicate $212.75 quotes; enrich the survivor."""
    dups = list(db.quotes.find({"total": 212.75}, {"_id": 0, "quote_id": 1}).sort("created_at", 1))
    removed = 0
    if len(dups) <= 1:
        return removed
    keep_id = dups[0]["quote_id"]
    for q in dups[1:]:
        qid = q["quote_id"]
        db.quotes.delete_one({"quote_id": qid})
        db.quote_lines.delete_many({"quote_id": qid})
        removed += 1
    db.quotes.update_one(
        {"quote_id": keep_id},
        {"$set": {"company_id": "pcdoctor", "estado": "Borrador", "updated_at": _now()}},
    )
    return removed


def _ensure_client(db, spec: dict) -> dict:
    hit = db.clients.find_one({"ruc": spec["ruc"]}, {"_id": 0})
    if hit:
        db.clients.update_one(
            {"client_id": hit["client_id"]},
            {
                "$set": {
                    "name": spec.get("name", hit.get("name")),
                    "city": spec.get("city", hit.get("city", "Guayaquil")),
                    "phone": spec.get("phone", hit.get("phone", "")),
                    "email": spec.get("email", hit.get("email", "")),
                    "updated_at": _now(),
                }
            },
        )
        return db.clients.find_one({"client_id": hit["client_id"]}, {"_id": 0})

    client_id = new_id("cli")
    doc = {
        "client_id": client_id,
        "ruc": spec["ruc"],
        "name": spec["name"],
        "city": spec.get("city", "Guayaquil"),
        "pais": "Ecuador",
        "address": spec.get("address", ""),
        "email": spec.get("email", ""),
        "phone": spec.get("phone", ""),
        "estado": "Cliente",
        "entidades": [],
        "hub_ready": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.clients.insert_one(doc)
    doc.pop("_id", None)
    ensure_client_hub(db, client_id, doc["name"])
    return doc


def _ensure_supplier(db, spec: dict) -> str:
    hit = db.suppliers.find_one({"ruc": spec["ruc"]}, {"_id": 0, "supplier_id": 1})
    if hit:
        db.suppliers.update_one(
            {"supplier_id": hit["supplier_id"]},
            {"$set": {**spec, "updated_at": _now()}},
        )
        return hit["supplier_id"]
    sid = new_id("sup")
    db.suppliers.insert_one(
        {
            "supplier_id": sid,
            **spec,
            "estado": "Activo",
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    return sid


def _ensure_quote(db, spec: dict, client: dict) -> str:
    hit = db.quotes.find_one({"code": spec["code"]}, {"_id": 0, "quote_id": 1})
    quote_id = hit["quote_id"] if hit else new_id("qte")
    header = {
        "quote_id": quote_id,
        "code": spec["code"],
        "serial": spec["code"],
        "client_id": client["client_id"],
        "client_ruc": client["ruc"],
        "client_name": client["name"],
        "company_id": spec.get("company_id", "pcdoctor"),
        "titulo": spec.get("titulo", f"Quote {spec['code']}"),
        "estado": spec.get("estado", "Borrador"),
        "moneda": "USD",
        "iva_15": True,
        "scope": spec.get("scope", ""),
        "updated_at": _now(),
    }
    if hit:
        db.quotes.update_one({"quote_id": quote_id}, {"$set": header})
    else:
        header["created_at"] = _now()
        db.quotes.insert_one(header)

    db.quote_lines.delete_many({"quote_id": quote_id})
    for i, line in enumerate(spec.get("lines", []), 1):
        qty = float(line.get("qty", 1))
        price = float(line.get("unit_price", 0))
        db.quote_lines.insert_one(
            {
                "quote_id": quote_id,
                "line_no": i,
                "tipo": line.get("tipo", "Servicio"),
                "descripcion": line.get("name", line.get("descripcion", "")),
                "cantidad": qty,
                "precio_unitario": price,
                "subtotal_linea": round(qty * price, 2),
            }
        )
    calc = calc_quote_from_lines(quote_id)
    db.quotes.update_one(
        {"quote_id": quote_id},
        {"$set": {"subtotal": calc["subtotal"], "monto_iva": calc["iva"], "total": calc["total"]}},
    )
    return quote_id


def _ensure_visit(db, spec: dict, client: dict) -> str:
    hit = db.sop_visits.find_one({"demo_seed_key": spec["key"]}, {"_id": 0, "visit_id": 1})
    if hit:
        db.sop_visits.update_one(
            {"visit_id": hit["visit_id"]},
            {
                "$set": {
                    "client_id": client["client_id"],
                    "client_name": client["name"],
                    "client_ruc": client["ruc"],
                    "tipo": spec.get("tipo", "soporte"),
                    "notas": spec.get("notas", ""),
                    "estado": spec.get("estado", "abierta"),
                    "fecha": spec.get("fecha", _now().isoformat()),
                    "updated_at": _now(),
                }
            },
        )
        return hit["visit_id"]

    visit_id = new_id("vis")
    db.sop_visits.insert_one(
        {
            "visit_id": visit_id,
            "demo_seed_key": spec["key"],
            "client_id": client["client_id"],
            "client_name": client["name"],
            "client_ruc": client["ruc"],
            "tipo": spec.get("tipo", "soporte"),
            "notas": spec.get("notas", ""),
            "estado": spec.get("estado", "abierta"),
            "fecha": spec.get("fecha", _now().isoformat()),
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    return visit_id


def _ensure_report(db, spec: dict, client: dict, visit_id: str) -> str:
    hit = db.technical_reports.find_one({"demo_seed_key": spec["key"]}, {"_id": 0, "report_id": 1})
    if hit:
        db.technical_reports.update_one(
            {"report_id": hit["report_id"]},
            {
                "$set": {
                    "titulo": spec["titulo"],
                    "client_id": client["client_id"],
                    "client_name": client["name"],
                    "client_ruc": client["ruc"],
                    "visit_id": visit_id,
                    "content_md": spec.get("content_md", ""),
                    "estado": spec.get("estado", "borrador"),
                    "updated_at": _now(),
                }
            },
        )
        return hit["report_id"]

    serial = next_serial(db, "PCD", "RPT")
    report_id = new_id("rpt")
    db.technical_reports.insert_one(
        {
            "report_id": report_id,
            "serial": serial["code"],
            "code": serial["code"],
            "demo_seed_key": spec["key"],
            "titulo": spec["titulo"],
            "client_id": client["client_id"],
            "client_name": client["name"],
            "client_ruc": client["ruc"],
            "visit_id": visit_id,
            "content_md": spec.get("content_md", ""),
            "estado": spec.get("estado", "borrador"),
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    return report_id


def run_seed() -> dict:
    db = _db()
    ensure_companies(db)

    removed_dups = _dedupe_212_quotes(db)

    clients_spec = [
        {"ruc": "0999059000001", "name": "Torres de la Merced", "city": "Guayaquil", "phone": "+593999059000"},
        {"ruc": "1790012345001", "name": "Edificio Albatros", "city": "Guayaquil", "phone": "+593987654321"},
        {"ruc": "1790098765001", "name": "Urbanización La Pradera", "city": "Quito", "phone": "+593912345678"},
        {"ruc": "0912345678001", "name": "Cliente Demo InnerChispa", "city": "Cuenca", "phone": "+593998877665"},
    ]
    clients = [_ensure_client(db, c) for c in clients_spec]

    suppliers_spec = [
        {"nombre": "TechDistribuidor SA", "ruc": "1790123456001", "ciudad": "Guayaquil", "email": "ventas@techdist.ec"},
        {"nombre": "RedesPro Ecuador", "ruc": "1790654321001", "ciudad": "Quito", "email": "info@redespro.ec"},
        {"nombre": "CCTV Importadores", "ruc": "1790789012001", "ciudad": "Guayaquil", "email": "cctv@import.ec"},
        {"nombre": "InnerChispa Supply", "ruc": "1790998877001", "ciudad": "Guayaquil", "email": "supply@innerchispa.ec"},
    ]
    supplier_ids = [_ensure_supplier(db, s) for s in suppliers_spec]

    quotes_spec = [
        {
            "code": "PCD-COT-260101",
            "company_id": "pcdoctor",
            "titulo": "Switch PoE 16 puertos — Torres de la Merced",
            "lines": [{"name": "Switch PoE 16p", "qty": 1, "unit_price": 185.0}],
            "client_idx": 0,
        },
        {
            "code": "PCD-COT-260102",
            "company_id": "pcdoctor",
            "titulo": "Mantenimiento CCTV — Albatros",
            "lines": [{"name": "Mantenimiento preventivo CCTV", "qty": 1, "unit_price": 120.0}],
            "client_idx": 1,
        },
        {
            "code": "PCD-COT-260103",
            "company_id": "innerchispa",
            "titulo": "Automatización acceso — La Pradera",
            "lines": [{"name": "Control acceso IP + instalación", "qty": 1, "unit_price": 890.0}],
            "client_idx": 2,
        },
        {
            "code": "PCD-COT-260104",
            "company_id": "innerchispa",
            "titulo": "Consultoría IoT residencial",
            "lines": [{"name": "Consultoría IoT", "qty": 2, "unit_price": 75.0}],
            "client_idx": 3,
        },
        {
            "code": "PCD-COT-260105",
            "company_id": "pcdoctor",
            "titulo": "Cableado estructurado Cat6",
            "lines": [{"name": "Punto de red Cat6", "qty": 12, "unit_price": 35.0}],
            "client_idx": 0,
        },
    ]
    quote_ids = [_ensure_quote(db, q, clients[q["client_idx"]]) for q in quotes_spec]

    base_date = _now() - timedelta(days=14)
    visits_spec = [
        {
            "key": "demo_visit_1",
            "tipo": "inspeccion",
            "notas": "Cámaras sin energía en estacionamiento — se requiere switch PoE.",
            "fecha": (base_date + timedelta(days=1)).isoformat(),
            "client_idx": 0,
        },
        {
            "key": "demo_visit_2",
            "tipo": "mantenimiento",
            "notas": "Limpieza lentes DVR y revisión de fuentes de poder.",
            "fecha": (base_date + timedelta(days=3)).isoformat(),
            "client_idx": 1,
        },
        {
            "key": "demo_visit_3",
            "tipo": "instalacion",
            "notas": "Instalación control de acceso biométrico en portería principal.",
            "fecha": (base_date + timedelta(days=5)).isoformat(),
            "client_idx": 2,
        },
        {
            "key": "demo_visit_4",
            "tipo": "cotizacion_campo",
            "notas": "Levantamiento para automatización de iluminación en áreas comunes.",
            "fecha": (base_date + timedelta(days=7)).isoformat(),
            "client_idx": 3,
        },
    ]
    visit_ids = [_ensure_visit(db, v, clients[v["client_idx"]]) for v in visits_spec]

    reports_spec = [
        {
            "key": "demo_report_1",
            "titulo": "Informe técnico — Infraestructura PoE",
            "content_md": "## Hallazgos\nSwitch PoE requerido para 8 cámaras IP.",
            "visit_idx": 0,
            "client_idx": 0,
        },
        {
            "key": "demo_report_2",
            "titulo": "Informe mantenimiento CCTV Albatros",
            "content_md": "## Trabajo realizado\nLimpieza y ajuste de 12 cámaras.",
            "visit_idx": 1,
            "client_idx": 1,
        },
        {
            "key": "demo_report_3",
            "titulo": "Informe instalación control acceso",
            "content_md": "## Estado\nBiométrico operativo en portería.",
            "visit_idx": 2,
            "client_idx": 2,
        },
    ]
    report_ids = [
        _ensure_report(db, r, clients[r["client_idx"]], visit_ids[r["visit_idx"]]) for r in reports_spec
    ]

    catalog_n = _ensure_catalog(db)

    return {
        "ok": True,
        "removed_duplicate_quotes": removed_dups,
        "clients": len(clients),
        "suppliers": len(supplier_ids),
        "quotes": len(quote_ids),
        "visits": len(visit_ids),
        "reports": len(report_ids),
        "catalog_products": catalog_n,
        "message": "Demo data seeded (idempotent). Duplicate $212.75 quotes deduped.",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_seed(), indent=2))
