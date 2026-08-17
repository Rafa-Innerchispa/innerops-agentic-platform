"""Libro contable unificado — espejo Contifico + correo + RalfIA.

Un solo lugar tabular para facturas, retenciones, cotizaciones.
Estructura compatible con contifico_documents para migración gradual.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store

LEDGER_COL = "ralfia_ledger_documents"
CONTIFICO_DOCS_COL = "contifico_documents"
CONTIFICO_PERSONAS_COL = "contifico_personas"
EMAIL_CAPTURE_COL = "email_captured_documents"

# Tipos Contifico conocidos
SALE_TIPOS = frozenset({"FAC", "COT", "NCT", "PRE"})
PURCHASE_TIPOS = frozenset({"DAC", "DNA", "LQC"})
RETENTION_TIPOS = frozenset({"RET", "RTI"})

EMAIL_TIPO_MAP = {
    "factura": "FAC",
    "cotizacion": "COT",
    "nota_credito": "NCT",
    "retencion": "RET",
    "guia_remision": "GRM",
    "orden_compra": "POC",
    "liquidacion_compra": "LQC",
    "documento": "DOC",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _parse_float(value: Any) -> float:
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_date_iso(value: Any) -> tuple[str | None, int | None, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None, None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(raw[:19], fmt.replace("T%H:%M:%S", "") if "T" not in raw else fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date().isoformat(), dt.year, dt.month
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return f"{y}-{mo:02d}-{m.group(3)}", y, mo
    return None, None, None


def _ralfia_number(tipo: str, documento: str) -> str:
    td = (tipo or "DOC").strip().upper()
    num = (documento or "").strip()
    return f"{td}-{num}" if num else td


def _parse_documento_seq(documento: str | None) -> int:
    digits = "".join(ch for ch in str(documento or "") if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _direction_for_tipo(tipo: str, *, source: str = "contifico") -> str:
    t = (tipo or "").upper()
    if t in PURCHASE_TIPOS or t == "RET":
        return "purchase"
    if t in SALE_TIPOS:
        return "sale"
    if source == "email":
        if t in RETENTION_TIPOS or t == "RET":
            return "purchase"
        if t in ("FAC", "LQC", "DOC"):
            return "purchase"
        if t == "COT":
            return "sale"
    return "purchase" if source == "email" else "sale"


def _ensure_indexes() -> None:
    db = _db()
    specs = [
        ([("ledger_id", 1)], {"unique": True, "name": "ux_ledger_id"}),
        ([("contifico_id", 1)], {"sparse": True, "name": "ix_ledger_contifico"}),
        ([("mail_id", 1)], {"sparse": True, "name": "ix_ledger_mail"}),
        ([("year", 1), ("month", 1), ("tipo_documento", 1)], {"name": "ix_ledger_period_tipo"}),
        ([("persona_ruc", 1)], {"sparse": True, "name": "ix_ledger_ruc"}),
        ([("sri_access_key", 1)], {"sparse": True, "name": "ix_ledger_sri_key"}),
        ([("ralfia_number", 1)], {"sparse": True, "name": "ix_ledger_ralfia_number"}),
        ([("fecha_iso", -1)], {"name": "ix_ledger_fecha"}),
    ]
    for keys, kwargs in specs:
        try:
            db[LEDGER_COL].create_index(keys, **kwargs)
        except Exception:
            pass


def _persona_lookup(persona_id: str | None) -> dict[str, str]:
    if not persona_id:
        return {}
    p = _db()[CONTIFICO_PERSONAS_COL].find_one({"persona_id": str(persona_id)})
    if not p:
        return {}
    return {
        "persona_nombre": str(p.get("nombre") or p.get("nombre_comercial") or ""),
        "persona_ruc": str(p.get("ruc") or p.get("ruc_raw") or ""),
    }


def _upsert_ledger(doc: dict[str, Any]) -> dict[str, Any]:
    _ensure_indexes()
    ledger_id = str(doc.get("ledger_id") or "").strip()
    if not ledger_id:
        return {"ok": False, "error": "ledger_id_required"}
    doc["updated_at"] = _now()
    if not doc.get("created_at"):
        doc["created_at"] = _now()
    _db()[LEDGER_COL].update_one({"ledger_id": ledger_id}, {"$set": doc}, upsert=True)
    return {"ok": True, "ledger_id": ledger_id, "ralfia_number": doc.get("ralfia_number")}


def ledger_from_contifico(row: dict[str, Any]) -> dict[str, Any]:
    """Mapea contifico_documents → ralfia_ledger_documents."""
    cid = str(row.get("contifico_id") or "")
    tipo = str(row.get("tipo_documento") or "DOC").upper()
    documento = str(row.get("documento") or "")
    fecha_iso, year, month = _parse_date_iso(row.get("fecha_iso") or row.get("fecha_emision"))
    persona = _persona_lookup(row.get("persona_id"))
    total = row.get("total_num")
    if total is None:
        total = _parse_float(row.get("total"))
    subtotal = row.get("subtotal_num")
    if subtotal is None:
        subtotal = _parse_float(row.get("subtotal"))
    iva = row.get("iva_num")
    if iva is None:
        iva = _parse_float(row.get("iva"))

    return {
        "ledger_id": f"contifico:{cid}",
        "source": "contifico",
        "contifico_id": cid,
        "mail_id": None,
        "payable_id": row.get("payable_id"),
        "receivable_id": row.get("receivable_id"),
        "tipo_documento": tipo,
        "documento": documento,
        "ralfia_number": row.get("ralfia_number") or _ralfia_number(tipo, documento),
        "documento_seq": row.get("documento_seq") or _parse_documento_seq(documento),
        "direction": _direction_for_tipo(tipo, source="contifico"),
        "persona_id": row.get("persona_id"),
        "persona_nombre": row.get("persona_nombre") or persona.get("persona_nombre"),
        "persona_ruc": row.get("persona_ruc") or persona.get("persona_ruc"),
        "fecha_emision": row.get("fecha_emision"),
        "fecha_vencimiento": row.get("fecha_vencimiento"),
        "fecha_iso": fecha_iso,
        "year": year,
        "month": month,
        "total_num": total,
        "subtotal_num": subtotal,
        "iva_num": iva,
        "estado": row.get("estado") or "P",
        "descripcion": (row.get("descripcion") or "")[:500],
        "lineas_count": len(row.get("lineas") or []),
        "product_ids": [
            str(ln.get("producto_id"))
            for ln in (row.get("lineas") or [])
            if ln.get("producto_id")
        ][:50],
        "sri_access_key": row.get("sri_access_key"),
        "contifico_linked": True,
        "status": "synced",
    }


def ledger_from_email_capture(capture: dict[str, Any]) -> dict[str, Any]:
    """Mapea email_captured_documents → ledger (CxP proveedor)."""
    mail_id = str(capture.get("mail_id") or "")
    fields = capture.get("fields") or {}
    doc_type = str(capture.get("doc_type") or fields.get("doc_type") or "documento")
    tipo = EMAIL_TIPO_MAP.get(doc_type, "DOC")
    invoice_hint = fields.get("invoice_number_hint")
    sri_keys = fields.get("sri_access_keys") or []
    sri_key = sri_keys[0] if sri_keys else None
    amounts = fields.get("amount_candidates") or []
    amount = amounts[0] if amounts else 0.0
    rucs = fields.get("ruc_candidates") or []
    ruc = rucs[0] if rucs else None

    received = capture.get("received_at")
    fecha_iso, year, month = _parse_date_iso(received)
    if isinstance(received, datetime):
        fecha_iso = received.date().isoformat()
        year, month = received.year, received.month

    documento = invoice_hint or (sri_key[-9:] if sri_key else mail_id.replace("mail_", "")[:12])
    direction = _direction_for_tipo(tipo, source="email")

    return {
        "ledger_id": f"email:{mail_id}",
        "source": "email",
        "contifico_id": capture.get("contifico_id"),
        "mail_id": mail_id,
        "payable_id": capture.get("payable_id"),
        "receivable_id": None,
        "tipo_documento": tipo,
        "documento": documento,
        "ralfia_number": _ralfia_number(tipo, documento),
        "documento_seq": _parse_documento_seq(documento),
        "direction": direction,
        "persona_id": capture.get("persona_id"),
        "persona_nombre": fields.get("from_addr") or capture.get("persona_nombre"),
        "persona_ruc": ruc,
        "fecha_emision": fecha_iso,
        "fecha_vencimiento": None,
        "fecha_iso": fecha_iso,
        "year": year,
        "month": month,
        "total_num": amount,
        "subtotal_num": round(amount / 1.15, 2) if amount and tipo == "FAC" else amount,
        "iva_num": round(amount - amount / 1.15, 2) if amount and tipo == "FAC" else 0.0,
        "estado": "P",
        "descripcion": (fields.get("subject") or capture.get("category") or "")[:500],
        "lineas_count": 0,
        "sri_access_key": sri_key,
        "contifico_linked": bool(capture.get("contifico_id")),
        "status": capture.get("status") or "pending_review",
        "account_address": capture.get("account_address"),
    }


def sync_contifico_to_ledger(*, limit: int = 5000) -> dict[str, Any]:
    """Importa contifico_documents → ralfia_ledger_documents."""
    _ensure_indexes()
    db = _db()
    rows = list(db[CONTIFICO_DOCS_COL].find({}).sort("fecha_emision", -1).limit(max(1, min(limit, 20000))))
    synced = 0
    for row in rows:
        doc = ledger_from_contifico(row)
        _upsert_ledger(doc)
        synced += 1
    return {
        "ok": True,
        "synced": synced,
        "ledger_total": db[LEDGER_COL].count_documents({}),
        "from_contifico": db[LEDGER_COL].count_documents({"source": "contifico"}),
    }


def promote_email_capture_to_ledger(
    mail_id: str,
    *,
    create_payable_draft: bool = True,
) -> dict[str, Any]:
    """Correo capturado → ledger + borrador CxP opcional."""
    db = _db()
    capture = db[EMAIL_CAPTURE_COL].find_one({"mail_id": mail_id})
    if not capture:
        return {"ok": False, "error": "capture_not_found", "mail_id": mail_id}

    ledger_doc = ledger_from_email_capture(capture)
    saved = _upsert_ledger(ledger_doc)

    payable_result = None
    if create_payable_draft and ledger_doc["direction"] == "purchase" and ledger_doc["tipo_documento"] in (
        "FAC", "RET", "LQC", "DOC"
    ):
        try:
            from raphiia_openai.operational import accounting_store

            payable_result = accounting_store.create_payable_draft(
                {
                    "source": "email_capture",
                    "payable_type": "invoice",
                    "supplier_name": ledger_doc.get("persona_nombre") or "Proveedor email",
                    "tax_id": ledger_doc.get("persona_ruc") or "",
                    "invoice_number": ledger_doc.get("documento") or "",
                    "amount": ledger_doc.get("total_num") or 0,
                    "issue_date": ledger_doc.get("fecha_iso") or "",
                    "notes": f"Capturado de correo {mail_id}. SRI: {ledger_doc.get('sri_access_key') or 'N/A'}",
                    "tags": ["email_capture", ledger_doc.get("tipo_documento", "").lower()],
                    "reference": mail_id,
                }
            )
            if payable_result.get("draft_id"):
                ledger_doc["payable_id"] = payable_result.get("draft_id") or payable_result.get("payable_id")
                _upsert_ledger({**ledger_doc, "payable_id": ledger_doc["payable_id"]})
        except Exception as exc:
            payable_result = {"ok": False, "error": str(exc)[:180]}

    db[EMAIL_CAPTURE_COL].update_one(
        {"mail_id": mail_id},
        {
            "$set": {
                "contifico_linked": True,
                "ledger_id": ledger_doc["ledger_id"],
                "status": "in_ledger",
                "updated_at": _now(),
            }
        },
    )
    return {
        "ok": True,
        "mail_id": mail_id,
        "ledger": saved,
        "ledger_id": ledger_doc["ledger_id"],
        "ralfia_number": ledger_doc.get("ralfia_number"),
        "payable": payable_result,
    }


def sync_all_captures_to_ledger(*, limit: int = 500) -> dict[str, Any]:
    """Promueve capturas email pendientes al ledger."""
    db = _db()
    rows = list(
        db[EMAIL_CAPTURE_COL].find({"status": {"$in": ["pending_review", "in_ledger"]}})
        .sort("received_at", -1)
        .limit(max(1, min(limit, 2000)))
    )
    promoted = 0
    errors = 0
    for row in rows:
        r = promote_email_capture_to_ledger(str(row.get("mail_id")), create_payable_draft=True)
        if r.get("ok"):
            promoted += 1
        else:
            errors += 1
    return {"ok": True, "promoted": promoted, "errors": errors}


def search_ledger_documents(
    *,
    query: str | None = None,
    year: int | None = None,
    month: int | None = None,
    tipo_documento: str | None = None,
    direction: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Búsqueda tabular estilo Contifico."""
    db = _db()
    filt: dict[str, Any] = {}
    if year:
        filt["year"] = int(year)
    if month:
        filt["month"] = int(month)
    if tipo_documento:
        filt["tipo_documento"] = tipo_documento.strip().upper()
    if direction:
        filt["direction"] = direction.strip().lower()
    if source:
        filt["source"] = source.strip().lower()
    if query:
        q = query.strip()
        filt["$or"] = [
            {"ralfia_number": {"$regex": re.escape(q), "$options": "i"}},
            {"documento": {"$regex": re.escape(q), "$options": "i"}},
            {"persona_nombre": {"$regex": re.escape(q), "$options": "i"}},
            {"persona_ruc": q},
            {"descripcion": {"$regex": re.escape(q), "$options": "i"}},
            {"sri_access_key": q},
            {"mail_id": q},
        ]
    rows = list(db[LEDGER_COL].find(filt, {"_id": 0}).sort([("fecha_iso", -1), ("documento_seq", -1)]).limit(max(1, min(limit, 200))))
    return {"ok": True, "count": len(rows), "filter": filt, "documents": rows}


def monthly_ledger_summary(*, year: int, month: int | None = None) -> dict[str, Any]:
    """Resumen mensual — facturas recibidas, emitidas, retenciones."""
    db = _db()
    match: dict[str, Any] = {"year": int(year)}
    if month:
        match["month"] = int(month)

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "month": "$month",
                    "tipo": "$tipo_documento",
                    "direction": "$direction",
                    "source": "$source",
                },
                "count": {"$sum": 1},
                "total": {"$sum": {"$ifNull": ["$total_num", 0]}},
                "iva": {"$sum": {"$ifNull": ["$iva_num", 0]}},
                "pending": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$estado", ["P", "pending_review", "pending"]]},
                            {"$ifNull": ["$total_num", 0]},
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"_id.month": 1, "_id.tipo": 1}},
    ]
    groups = list(db[LEDGER_COL].aggregate(pipeline))

    purchases = db[LEDGER_COL].count_documents({**match, "direction": "purchase"})
    sales = db[LEDGER_COL].count_documents({**match, "direction": "sale"})
    retenciones = db[LEDGER_COL].count_documents({**match, "tipo_documento": {"$in": list(RETENTION_TIPOS) + ["RET"]}})

    return {
        "ok": True,
        "year": year,
        "month": month,
        "totals": {
            "documents": db[LEDGER_COL].count_documents(match),
            "purchases_count": purchases,
            "sales_count": sales,
            "retenciones_count": retenciones,
        },
        "breakdown": [
            {
                "month": g["_id"]["month"],
                "tipo_documento": g["_id"]["tipo"],
                "direction": g["_id"]["direction"],
                "source": g["_id"]["source"],
                "count": g["count"],
                "total_num": round(g["total"], 2),
                "iva_num": round(g["iva"], 2),
                "pending_num": round(g["pending"], 2),
            }
            for g in groups
        ],
    }


def peek_next_contifico_number(tipo_documento: str = "FAC") -> dict[str, Any]:
    """Siguiente número compatible Contifico (para continuidad al cortar)."""
    db = _db()
    tipo = tipo_documento.strip().upper()

    max_doc = db[LEDGER_COL].find_one({"tipo_documento": tipo}, sort=[("documento_seq", -1)])
    if not max_doc:
        max_doc = db[CONTIFICO_DOCS_COL].find_one({"tipo_documento": tipo}, sort=[("documento_seq", -1)])

    last_documento = str((max_doc or {}).get("documento") or "")
    last_seq = int((max_doc or {}).get("documento_seq") or 0)

    next_documento = last_documento
    if last_documento and "-" in last_documento:
        parts = last_documento.split("-")
        try:
            seq_part = int(parts[-1])
            parts[-1] = f"{seq_part + 1:0{len(parts[-1])}d}"
            next_documento = "-".join(parts)
        except ValueError:
            next_documento = f"{last_documento}-NEXT"
    elif last_seq:
        next_documento = str(last_seq + 1)

    return {
        "ok": True,
        "tipo_documento": tipo,
        "last_documento": last_documento or None,
        "last_ralfia_number": (max_doc or {}).get("ralfia_number"),
        "last_documento_seq": last_seq or None,
        "next_documento": next_documento,
        "next_ralfia_number": _ralfia_number(tipo, next_documento),
        "note": "Continúa secuencia Contifico (establecimiento-punto-secuencial). Usar al emitir desde RalfIA.",
    }


def link_fac_to_cot_quotes(*, limit: int = 1000, reprocess: bool = False) -> dict[str, Any]:
    """Relaciona FAC emitidas con COT del mismo cliente (monto/fecha)."""
    db = _db()
    filt: dict[str, Any] = {"tipo_documento": "FAC", "direction": "sale"}
    if not reprocess:
        filt["related_cot_contifico_id"] = {"$exists": False}
    facs = list(db[LEDGER_COL].find(filt).sort("fecha_iso", -1).limit(max(1, min(limit, 5000))))
    linked = 0
    for fac in facs:
        pid = fac.get("persona_id")
        total = float(fac.get("total_num") or 0)
        fecha = fac.get("fecha_iso")
        if not pid:
            continue
        cot_filt: dict[str, Any] = {"persona_id": pid, "tipo_documento": "COT"}
        if fecha:
            cot_filt["fecha_iso"] = {"$lte": fecha}
        cots = list(db[CONTIFICO_DOCS_COL].find(cot_filt).sort("fecha_iso", -1).limit(30))
        best = None
        best_conf = 0.0
        for cot in cots:
            cot_total = float(cot.get("total_num") or _parse_float(cot.get("total")))
            conf = 0.5
            if total and cot_total and abs(cot_total - total) <= max(0.02 * total, 1.0):
                conf = 0.95
                best = cot
                best_conf = conf
                break
            if total and cot_total and abs(cot_total - total) <= max(0.1 * total, 5.0):
                conf = 0.7
                if conf > best_conf:
                    best = cot
                    best_conf = conf
        if not best and cots:
            best = cots[0]
            best_conf = 0.4
        if not best:
            continue
        db[LEDGER_COL].update_one(
            {"ledger_id": fac["ledger_id"]},
            {
                "$set": {
                    "related_cot_contifico_id": best.get("contifico_id"),
                    "related_cot_number": best.get("ralfia_number")
                    or _ralfia_number("COT", str(best.get("documento") or "")),
                    "related_cot_documento": best.get("documento"),
                    "link_method": "persona_total_date",
                    "link_confidence": best_conf,
                    "updated_at": _now(),
                }
            },
        )
        linked += 1
    return {"ok": True, "linked": linked, "scanned": len(facs)}


def sync_inventory_from_contifico(*, hydrate_max: int = 80, inventory_limit: int = 2000) -> dict[str, Any]:
    """Rellena inventario local desde catálogo Contifico (stock + productos vendidos)."""
    from raphiia_openai import contifico_bridge
    from raphiia_openai.operational import inventory_store

    hydrate = contifico_bridge.hydrate_contifico_products_from_documents(
        max_fetch=hydrate_max, dry_run=False
    )
    materialize = contifico_bridge.materialize_local_product_catalog(dry_run=False)

    db = _db()
    catalog = db[contifico_bridge.CATALOG_COL].find_one({"kind": "productos"}) or {}
    upserted = 0
    for prod in (catalog.get("items") or [])[:inventory_limit]:
        pid = str(prod.get("id") or prod.get("contifico_product_id") or "")
        if not pid:
            continue
        sku = _norm_sku(prod.get("ralfia_sku") or prod.get("codigo") or pid)
        inventory_store.upsert_inventory_item(
            {
                "sku": sku,
                "name": prod.get("nombre") or prod.get("name") or pid,
                "product_key": f"contifico:{pid}",
                "source": "contifico",
                "source_doc": str(prod.get("legacy_codigo") or prod.get("codigo") or ""),
                "category": prod.get("categoria_root") or prod.get("categoria_nombre") or "",
                "qty_on_hand": _parse_float(prod.get("cantidad_stock")),
                "entity_id": "ent_pcdoctor",
            }
        )
        upserted += 1

    stats = inventory_store.inventory_catalog_stats()
    return {
        "ok": True,
        "upserted": upserted,
        "hydrate": hydrate,
        "materialize": materialize,
        "inventory_stats": stats,
    }


def _norm_sku(value: Any) -> str:
    return re.sub(r"\s+", "-", str(value or "").strip())[:80]


def daily_contifico_pipeline(*, incremental_pages: int = 10) -> dict[str, Any]:
    """Pipeline diario completo — 100% local excepto lectura Contifico API."""
    steps: dict[str, Any] = {}

    try:
        from raphiia_openai import contifico_bridge

        steps["contifico_incremental"] = contifico_bridge.import_contifico_incremental(
            pages=incremental_pages, size=50, dry_run=False
        )
    except Exception as exc:
        steps["contifico_incremental"] = {"ok": False, "error": str(exc)[:200]}

    try:
        from raphiia_openai import contifico_normalize

        steps["normalize"] = contifico_normalize.normalize_contifico_documents()
    except Exception as exc:
        steps["normalize"] = {"ok": False, "error": str(exc)[:200]}

    steps["ledger_sync"] = sync_contifico_to_ledger(limit=10000)
    steps["fac_cot_links"] = link_fac_to_cot_quotes(limit=500, reprocess=False)
    steps["ledger_email"] = sync_all_captures_to_ledger(limit=200)
    steps["inventory"] = sync_inventory_from_contifico(hydrate_max=60, inventory_limit=2000)

    try:
        from raphiia_openai.notifications import email_router
        from raphiia_openai import mongo_store as ms

        db = ms.get_db()
        recent = list(
            db.email_messages.find(
                {"ralfia_intelligence_at": {"$exists": False}},
                {"_id": 0},
            )
            .sort("received_at", -1)
            .limit(50)
        )
        routed = 0
        for row in recent:
            review = row.get("ralfia_review") or {}
            if review.get("category") in ("marketing", "security_code"):
                continue
            try:
                email_router.process_email_intelligence(row, create_task=False, analysis=review or None)
                routed += 1
            except Exception:
                pass
        steps["email_intelligence"] = {"ok": True, "routed": routed}
    except Exception as exc:
        steps["email_intelligence"] = {"ok": False, "error": str(exc)[:120]}

    steps["status"] = get_ledger_status()
    steps["inventory_stats"] = steps.get("inventory", {}).get("inventory_stats")
    return {"ok": True, "pipeline": "daily_contifico", "steps": steps}


def get_ledger_status() -> dict[str, Any]:
    db = _db()
    by_source = {}
    for src in ("contifico", "email", "ralfia"):
        by_source[src] = db[LEDGER_COL].count_documents({"source": src})
    now = datetime.now(timezone.utc)
    this_month = db[LEDGER_COL].count_documents({"year": now.year, "month": now.month})
    pending_email = db[EMAIL_CAPTURE_COL].count_documents({"status": "pending_review"})
    fac_with_cot = db[LEDGER_COL].count_documents({"related_cot_contifico_id": {"$exists": True, "$ne": None}})
    return {
        "ok": True,
        "ledger_total": db[LEDGER_COL].count_documents({}),
        "by_source": by_source,
        "this_month": this_month,
        "fac_linked_to_cot": fac_with_cot,
        "contifico_in_mongo": db[CONTIFICO_DOCS_COL].count_documents({}),
        "email_captures_pending": pending_email,
        "collection": LEDGER_COL,
        "schema": "compatible contifico_documents + direction + sri_access_key",
        "daily_timer": "ralfia-daily-contifico-sync.timer @ 06:15",
    }


def full_accounting_sync(*, contifico_limit: int = 5000) -> dict[str, Any]:
    """Pipeline completo manual — preferir daily_contifico_pipeline para cron."""
    return daily_contifico_pipeline(incremental_pages=max(10, contifico_limit // 50))
