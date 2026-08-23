"""
Flujo operativo v2 — SOP Campo PC Doctor.

Cadena: DB04 → DB05? → Hub → DB42 → DB45 → DB27/DB38 → documents → gates

NOTA: No usa las 52 DB en cada visita. Ver docs/ARQUITECTURA_FLUJOS.md
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.gates import calc_quote_from_lines, run_ready_to_send, run_verification_rules
from tools.mongo import get_db, log_action
from tools.schema import ensure_client_hub, new_id, next_serial


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _link_hub(db, client_id: str, section: str, ref_id: str) -> None:
    if not client_id:
        return
    db.client_hubs.update_one(
        {"client_id": client_id},
        {"$addToSet": {f"sections.{section}": ref_id}, "$set": {"updated_at": _now()}},
    )


def start_field_visit(raw_input: str, inspection_id: str | None = None, ruc: str | None = None) -> dict:
    """
    Inicia visita: legacy inspection + DB42 sop_visit con código PCD-SOP.
    """
    from tools.crew_tools import start_inspection_record

    iid = start_inspection_record(raw_input, inspection_id=inspection_id)
    db = get_db()

    client_id = None
    if ruc:
        cl = db.clients.find_one({"ruc": ruc}, {"_id": 0, "client_id": 1})
        if cl:
            client_id = cl["client_id"]

    existing = db.sop_visits.find_one({"legacy_inspection_id": iid}, {"_id": 0})
    if existing:
        return {**existing, "inspection_id": iid}

    serial = next_serial(db, "PCD", "SOP")
    visit_id = new_id("vis")
    visit = {
        "visit_id": visit_id,
        "legacy_inspection_id": iid,
        "code": serial["code"],
        "entity": "PCD",
        "client_id": client_id,
        "ruc": ruc,
        "fecha": _now(),
        "estado": "En ejecución",
        "raw_input": raw_input,
        "findings": [],
        "pending_tasks": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    from pymongo.errors import DuplicateKeyError

    try:
        db.sop_visits.insert_one(visit)
    except DuplicateKeyError:
        existing = db.sop_visits.find_one({"legacy_inspection_id": iid}, {"_id": 0})
        if existing:
            return {**existing, "inspection_id": iid}
        raise
    visit.pop("_id", None)
    log_action("director", "sop_visit_started", {"visit_id": visit_id, "code": serial["code"], "target_type": "sop_visit", "target_id": visit_id})
    return {**visit, "inspection_id": iid}


def sync_findings_to_visit(inspection_id: str) -> dict | None:
    db = get_db()
    insp = db.inspections.find_one({"inspection_id": inspection_id}, {"_id": 0})
    if not insp:
        return None
    patch = {
        "findings": insp.get("findings", []),
        "pending_tasks": insp.get("pending_tasks", []),
        "updated_at": _now(),
    }
    db.sop_visits.update_one({"legacy_inspection_id": inspection_id}, {"$set": patch})
    return db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})


def save_technical_report_v2(
    inspection_id: str,
    report: dict,
    client_id: str | None = None,
) -> dict:
    db = get_db()
    visit = db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
    if not visit:
        raise ValueError(f"Visita no encontrada para inspection_id={inspection_id}")

    visit_id = visit["visit_id"]
    client_id = client_id or visit.get("client_id")
    existing = db.technical_reports.find_one({"visit_id": visit_id}, {"_id": 0})

    if existing:
        db.technical_reports.update_one(
            {"report_id": existing["report_id"]},
            {
                "$set": {
                    **report,
                    "findings": visit.get("findings", []),
                    "pending_tasks": visit.get("pending_tasks", []),
                    "updated_at": _now(),
                }
            },
        )
        doc = db.technical_reports.find_one({"report_id": existing["report_id"]}, {"_id": 0})
    else:
        serial = next_serial(db, "PCD", "RPT")
        report_id = new_id("rpt")
        doc = {
            "report_id": report_id,
            "code": serial["code"],
            "visit_id": visit_id,
            "legacy_inspection_id": inspection_id,
            "client_id": client_id,
            "estado": "Borrador",
            "tipo_reporte": report.get("tipo_reporte", "Visita técnica / Avance"),
            "resumen_ejecutivo": report.get("summary", ""),
            "hallazgos_clave": report.get("findings_text", ""),
            "pendientes": "; ".join(visit.get("pending_tasks", [])),
            "bitacora": report.get("work_done", ""),
            "tecnico": report.get("technician", ""),
            "ubicacion": report.get("location", ""),
            "recomendaciones": report.get("recommendations", ""),
            "findings": visit.get("findings", []),
            "created_at": _now(),
            "updated_at": _now(),
        }
        db.technical_reports.insert_one(doc)
        doc.pop("_id", None)

    _link_hub(db, client_id, "reportes", doc["report_id"])
    log_action("informes", "technical_report_saved", {"target_type": "technical_report", "target_id": doc["report_id"]})
    return doc


def save_quote_v2(inspection_id: str, quote: dict, client_id: str | None = None) -> dict:
    """DB27 cabecera + DB38 líneas. Totales recalculados desde líneas."""
    db = get_db()
    visit = db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
    if not visit:
        raise ValueError(f"Visita no encontrada para inspection_id={inspection_id}")

    client_id = client_id or visit.get("client_id")
    if client_id:
        ensure_client_hub(db, client_id)

    report = db.technical_reports.find_one({"visit_id": visit["visit_id"]}, {"_id": 0})
    report_id = report["report_id"] if report else None

    existing = db.quotes.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
    if existing:
        quote_id = existing["quote_id"]
    else:
        serial = next_serial(db, "PCD", "COT")
        quote_id = new_id("qot")
        from pymongo.errors import DuplicateKeyError

        try:
            db.quotes.insert_one(
                {
                    "quote_id": quote_id,
                    "code": serial["code"],
                    "legacy_inspection_id": inspection_id,
                    "visit_id": visit["visit_id"],
                    "report_id": report_id,
                    "client_id": client_id,
                    "client_ruc": quote.get("client_ruc"),
                    "estado": "Borrador",
                    "moneda": "USD",
                    "iva_15": True,
                    "scope": quote.get("scope", ""),
                    "created_at": _now(),
                }
            )
        except DuplicateKeyError:
            dup = db.quotes.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
            if dup:
                quote_id = dup["quote_id"]
            else:
                raise

    # DB38 líneas
    db.quote_lines.delete_many({"quote_id": quote_id})
    lines_in = quote.get("lines", [])
    for i, line in enumerate(lines_in, 1):
        qty = float(line.get("qty") or line.get("cantidad") or 1)
        price = float(line.get("unit_price") or line.get("precio_unitario") or 0)
        subtotal_linea = round(qty * price, 2)
        db.quote_lines.insert_one(
            {
                "quote_id": quote_id,
                "line_no": i,
                "legacy_inspection_id": inspection_id,
                "tipo": line.get("tipo", "Servicio"),
                "descripcion": line.get("name") or line.get("descripcion", ""),
                "cantidad": qty,
                "precio_unitario": price,
                "subtotal_linea": subtotal_linea,
            }
        )

    calc = calc_quote_from_lines(quote_id)
    db.quotes.update_one(
        {"quote_id": quote_id},
        {
            "$set": {
                "subtotal": calc["subtotal"],
                "monto_iva": calc["iva"],
                "total": calc["total"],
                "subtotal_calculado": calc["subtotal"],
                "total_calculado": calc["total"],
                "scope": quote.get("scope", ""),
                "client_ruc": quote.get("client_ruc"),
                "updated_at": _now(),
            }
        },
    )

    header = db.quotes.find_one({"quote_id": quote_id}, {"_id": 0})
    _link_hub(db, client_id, "cotizaciones", quote_id)
    log_action("cotizador", "quote_saved_v2", {"target_type": "quote", "target_id": quote_id})
    return {**header, "lines": calc["lines"]}


def register_document(
    path: str,
    target_type: str,
    target_id: str,
    client_id: str | None = None,
    formato: str = "md",
) -> dict:
    """PDF-first → colección documents + hub pdfs_exportables."""
    db = get_db()
    p = Path(path)
    content = p.read_bytes() if p.exists() else b""
    sha = hashlib.sha256(content).hexdigest() if content else ""

    hub_id = None
    if client_id:
        cl = db.clients.find_one({"client_id": client_id}, {"_id": 0, "hub_id": 1})
        hub_id = cl.get("hub_id") if cl else None

    doc_id = new_id("doc")
    doc = {
        "document_id": doc_id,
        "target_type": target_type,
        "target_id": target_id,
        "client_id": client_id,
        "hub_id": hub_id,
        "formato": formato,
        "path": str(path),
        "sha256": sha,
        "version": 1,
        "created_at": _now(),
    }
    db.documents.insert_one(doc)
    doc.pop("_id", None)
    _link_hub(db, client_id, "pdfs_exportables", doc_id)

    if target_type == "technical_report":
        db.technical_reports.update_one(
            {"report_id": target_id},
            {"$set": {"pdf_first_path": str(path), "listo_exportar_pdf": True}},
        )
    if target_type == "quote":
        db.quotes.update_one({"quote_id": target_id}, {"$set": {"pdf_first_path": str(path)}})

    log_action("informes", "document_registered", {"target_type": target_type, "target_id": target_id})
    return doc


def finalize_field_flow(inspection_id: str, client_id: str | None = None) -> dict:
    """Cierra visita, corre gates DB41 y listo-para-enviar."""
    db = get_db()
    visit = db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
    if not visit:
        return {"error": "visita no encontrada"}

    db.sop_visits.update_one(
        {"visit_id": visit["visit_id"]},
        {"$set": {"estado": "Cerrado", "updated_at": _now()}},
    )

    quote = db.quotes.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
    gates = {}
    if quote:
        cid = client_id or quote.get("client_id") or visit.get("client_id")
        gates["verification_rules"] = run_verification_rules("quote", quote["quote_id"])
        gates["ready_to_send"] = run_ready_to_send(quote["quote_id"], client_id=cid)

    return {
        "visit_id": visit["visit_id"],
        "visit_code": visit.get("code"),
        "quote_id": quote.get("quote_id") if quote else None,
        "quote_code": quote.get("code") if quote else None,
        "gates": gates,
    }


def get_flow_context(inspection_id: str) -> dict[str, Any]:
    """Contexto v2 completo para respuesta API."""
    db = get_db()
    visit = db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
    report = None
    quote = None
    documents = []
    if visit:
        report = db.technical_reports.find_one({"visit_id": visit["visit_id"]}, {"_id": 0})
        quote = db.quotes.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
        if quote:
            quote["lines"] = list(db.quote_lines.find({"quote_id": quote["quote_id"]}, {"_id": 0}))
        q = {"$or": []}
        if report:
            q["$or"].append({"target_type": "technical_report", "target_id": report["report_id"]})
        if quote:
            q["$or"].append({"target_type": "quote", "target_id": quote["quote_id"]})
        if q["$or"]:
            documents = list(db.documents.find({"$or": q["$or"]}, {"_id": 0}))

    return {
        "inspection_id": inspection_id,
        "visit": visit,
        "technical_report": report,
        "quote": quote,
        "documents": documents,
    }
