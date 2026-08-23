"""Demo guiada con datos reales: cliente, catálogo, cotización con líneas."""

from __future__ import annotations

from typing import Any

from tools.client_sanitize import normalize_tax_id_field, sanitize_empty_client_rucs, valid_tax_id
from tools.mongo import create_client, get_db, lookup_client_by_ruc
from tools.schema import ensure_client_hub


def _ensure_client(
    ruc: str,
    name: str,
    phone: str = "",
    address: str = "",
    city: str = "Guayaquil",
) -> dict:
    db = get_db()
    ruc = normalize_tax_id_field(ruc)
    if valid_tax_id(ruc):
        hit = lookup_client_by_ruc(ruc)
        if hit:
            db.clients.update_one(
                {"client_id": hit["client_id"]},
                {"$set": {"name": name or hit.get("name"), "phone": phone or hit.get("phone"), "address": address or hit.get("address")}},
            )
            return db.clients.find_one({"client_id": hit["client_id"]}, {"_id": 0}) or hit
        return create_client(
            {
                "ruc": ruc,
                "name": name or f"Client {ruc}",
                "phone": phone,
                "address": address,
                "city": city,
                "pais": "Ecuador",
                "estado": "Cliente",
            }
        )
    # Sin RUC — cliente manual (NO guardar ruc: "" — índice único sparse falla)
    label = (name or "Walk-in client").strip()
    hit = db.clients.find_one(
        {"name": label, "$or": [{"ruc": {"$exists": False}}, {"ruc": None}]},
        {"_id": 0},
    )
    if hit:
        return hit
    from datetime import datetime, timezone
    from tools.schema import new_id

    client_id = new_id("cli")
    now = datetime.now(timezone.utc)
    doc = {
        "client_id": client_id,
        "name": label,
        "phone": phone,
        "address": address,
        "city": city,
        "pais": "Ecuador",
        "estado": "Cliente",
        "entidades": [],
        "hub_ready": False,
        "created_at": now,
        "updated_at": now,
    }
    db.clients.insert_one(doc)
    doc.pop("_id", None)
    ensure_client_hub(db, client_id, doc["name"])
    return doc


def _findings_from_catalog(product_codes: list[str]) -> list[dict]:
    db = get_db()
    findings: list[dict] = []
    for code in product_codes:
        prod = db.catalog_products.find_one({"code": code}, {"_id": 0}) or db.inventory_items.find_one(
            {"sku": code}, {"_id": 0}
        )
        if not prod:
            continue
        price = float(prod.get("precio_sugerido") or prod.get("precio_contado") or 0)
        nombre = prod.get("nombre") or prod.get("name") or code
        tipo = prod.get("tipo") or "producto"
        findings.append(
            {
                "item": nombre,
                "severity": "alta" if tipo == "producto" else "media",
                "detail": prod.get("descripcion_comercial") or f"{tipo}: {nombre}",
                "qty": 1,
                "estimated_unit_price": price or 50.0,
                "code": code,
            }
        )
    return findings


def _load_existing_demo_run(db, email_mail_id: str) -> dict[str, Any] | None:
    run = db.guided_demo_runs.find_one({"mail_id": email_mail_id}, sort=[("created_at", -1)])
    if not run:
        return None
    client = (
        db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0}) if run.get("client_id") else None
    )
    quote = db.quotes.find_one({"quote_id": run["quote_id"]}, {"_id": 0}) if run.get("quote_id") else None
    inspection_id = run.get("inspection_id")
    visit = (
        db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0})
        if inspection_id
        else None
    )
    report_v2 = None
    if run.get("report_id"):
        report_v2 = db.reports.find_one({"report_id": run["report_id"]}, {"_id": 0})
    return {
        "inspection_id": inspection_id,
        "flow": "guided_production_pipeline",
        "visit": visit,
        "client": client or {},
        "findings": [],
        "report": {},
        "report_v2": report_v2 or {},
        "quote": quote or {},
        "review": {"approved": True, "issues": [], "notes": "Guided demo — existing records reused"},
        "codes": {
            "visit": (visit or {}).get("code"),
            "report": (report_v2 or {}).get("code"),
            "quote": (quote or {}).get("code"),
        },
        "status": "skipped_duplicate",
        "skipped_duplicate": True,
    }


def run_guided_demo(
    voice_text: str,
    *,
    client_ruc: str = "",
    client_name: str = "",
    client_phone: str = "",
    client_address: str = "",
    product_codes: list[str] | None = None,
    company_id: str = "pcdoctor",
    email_mail_id: str = "",
    skip_if_processed: bool = False,
) -> dict[str, Any]:
    """Pipeline guiada: cliente real + líneas de catálogo + cotización enriquecida."""
    db = get_db()
    sanitize_empty_client_rucs(db)
    if skip_if_processed and email_mail_id:
        existing = _load_existing_demo_run(db, email_mail_id)
        if existing:
            return existing
        if client_ruc:
            hit = lookup_client_by_ruc(client_ruc.strip())
            if hit:
                client = db.clients.find_one({"client_id": hit["client_id"]}, {"_id": 0}) or hit
                latest_quote = db.quotes.find_one(
                    {"client_id": client.get("client_id")},
                    {"_id": 0},
                    sort=[("created_at", -1)],
                )
                return {
                    "inspection_id": None,
                    "flow": "guided_production_pipeline",
                    "visit": None,
                    "client": client,
                    "findings": [],
                    "report": {},
                    "report_v2": {},
                    "quote": latest_quote or {},
                    "review": {"approved": True, "issues": [], "notes": "Client already exists — no duplicate quote"},
                    "codes": {"visit": None, "report": None, "quote": (latest_quote or {}).get("code")},
                    "status": "skipped_duplicate",
                    "skipped_duplicate": True,
                }

    from tools.mongo import save_report, update_inspection
    from tools.pdf_generator import export_quote, export_technical_report
    from tools.workflow_v2 import (
        register_document,
        save_quote_v2,
        save_technical_report_v2,
        start_field_visit,
        sync_findings_to_visit,
    )
    from agents.crew import _fallback_quote

    product_codes = product_codes or []
    client = _ensure_client(
        normalize_tax_id_field(client_ruc),
        (client_name or "").strip(),
        (client_phone or "").strip(),
        (client_address or "").strip(),
    )
    client_id = client.get("client_id")
    ruc = client.get("ruc") or client_ruc

    voice = voice_text.strip() or f"Quote for {client.get('name', 'client')}"
    if product_codes:
        voice += " — items: " + ", ".join(product_codes)

    visit_info = start_field_visit(voice, ruc=ruc or None)
    inspection_id = visit_info["inspection_id"]

    db = get_db()
    db.sop_visits.update_one(
        {"legacy_inspection_id": inspection_id},
        {"$set": {"client_id": client_id, "client_name": client.get("name"), "client_ruc": ruc}},
    )

    findings = _findings_from_catalog(product_codes) if product_codes else []
    if not findings:
        from agents.crew import _demo_findings

        findings = _demo_findings(voice)

    update_inspection(inspection_id, {"findings": findings, "pending_tasks": ["Client approval", "Schedule install"]})
    sync_findings_to_visit(inspection_id)

    report = {
        "summary": f"Technical inspection — {client.get('name', '')}",
        "location": client_address or client.get("address", "Site"),
        "technician": "PC Doctor Field Tech",
        "findings_text": "; ".join(f.get("detail", "") for f in findings),
        "work_done": "Site survey and infrastructure assessment",
        "final_status": "Pending quote approval",
        "recommendations": "Proceed with quoted items and schedule installation",
    }
    save_report(inspection_id, report)
    report_v2 = save_technical_report_v2(inspection_id, report, client_id=client_id)

    lines = [
        {
            "name": f.get("item"),
            "descripcion": f.get("detail"),
            "qty": f.get("qty", 1),
            "unit_price": f.get("estimated_unit_price", 0),
            "tipo": "Producto" if f.get("code") else "Servicio",
        }
        for f in findings
    ]
    quote = _fallback_quote(findings)
    quote["lines"] = lines
    quote["scope"] = voice[:500]
    if ruc:
        quote["client_ruc"] = ruc
    quote_v2 = save_quote_v2(inspection_id, quote, client_id=client_id)
    db.quotes.update_one(
        {"quote_id": quote_v2["quote_id"]},
        {"$set": {"company_id": company_id, "client_id": client_id, "titulo": f"Quote — {client.get('name', '')}"}},
    )
    quote_v2 = db.quotes.find_one({"quote_id": quote_v2["quote_id"]}, {"_id": 0}) or quote_v2

    report_path = export_technical_report(inspection_id, report, client, code=report_v2.get("code"))
    quote_path = export_quote(inspection_id, quote_v2, client, code=quote_v2.get("code"))
    register_document(report_path, "technical_report", report_v2["report_id"], client_id=client_id)
    register_document(quote_path, "quote", quote_v2["quote_id"], client_id=client_id)

    return {
        "inspection_id": inspection_id,
        "flow": "guided_production_pipeline",
        "visit": db.sop_visits.find_one({"legacy_inspection_id": inspection_id}, {"_id": 0}),
        "client": client,
        "findings": findings,
        "report": report,
        "report_v2": report_v2,
        "quote": quote_v2,
        "review": {"approved": True, "issues": [], "notes": "Guided demo — real MongoDB records"},
        "codes": {
            "visit": visit_info.get("code"),
            "report": report_v2.get("code"),
            "quote": quote_v2.get("code"),
        },
        "status": "completed",
    }
