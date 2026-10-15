"""Contífico Read-Only Query Engine.

Provides unified read-only querying across Contífico accounting documents (purchases and sales),
transactions, persons, and line items by proveedor, producto, documento, and fecha.
Also provides price, cost, and margin cross-referencing with verifiable SKU correspondence
and strict temporal traceability.
Strictly non-destructive: zero accounting mutations, zero secret leakage.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pymongo import MongoClient

from inneros_core_runtime import mongo_store

DOCS_COL = "contifico_documents"
PERSONAS_COL = "contifico_personas"
TXN_COL = "contifico_transactions"
MIRROR_COL = "contifico_mirror"
QUERY_LOG_COL = "contifico_query_log"

NOISE_WORDS = {
    "para", "con", "por", "del", "las", "los", "una", "uno", "sin", "sobre",
    "tipo", "integ", "mantenimiento", "limpieza", "cambio", "instalacion", "servicio",
    "revision", "chequeo", "mano", "obra", "mesa", "cable"
}


def _db():
    return mongo_store.get_db()


def _log_query(query_params: dict[str, Any], count: int, t0: float, entity_id: str = "pcdoctor") -> None:
    try:
        dur_ms = round((time.perf_counter() - t0) * 1000, 2)
        db = _db()
        db[QUERY_LOG_COL].insert_one({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entity_id": entity_id,
            "query": query_params,
            "result_count": count,
            "duration_ms": dur_ms,
            "read_only": True,
        })
    except Exception:
        pass


def parse_and_normalize_date(d_val: Any) -> Optional[datetime]:
    """Parse date from multiple formats and return datetime object."""
    if not d_val:
        return None
    if isinstance(d_val, datetime):
        return d_val
    s = str(d_val).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.split("T")[0] if "T" in s and fmt == "%Y-%m-%d" else s, fmt)
        except Exception:
            pass
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except Exception:
            pass
    m2 = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m2:
        try:
            return datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except Exception:
            pass
    return None


def format_iso_date(d_val: Any) -> Optional[str]:
    """Normalize date to standard ISO YYYY-MM-DD string."""
    dt = parse_and_normalize_date(d_val)
    return dt.strftime("%Y-%m-%d") if dt else (str(d_val) if d_val else None)


def normalize_sku_name(name: str) -> str:
    """Normalize SKU or product name for strict matching."""
    if not name:
        return ""
    s = re.sub(r"[^\w\s]", " ", name.lower())
    return " ".join(s.split())


def resolve_persona_cached_or_live(query: str, entity_id: str = "pcdoctor") -> Optional[dict[str, Any]]:
    """Resolves persona by RUC, cédula, persona_id, or name from Mongo or live API."""
    q = (query or "").strip()
    if not q:
        return None
    db = _db()
    p = db[PERSONAS_COL].find_one({
        "$or": [
            {"ruc": q},
            {"cedula": q},
            {"persona_id": q},
            {"nombre": {"$regex": f"^{re.escape(q)}$", "$options": "i"}},
            {"nombre_comercial": {"$regex": f"^{re.escape(q)}$", "$options": "i"}},
            {"nombre": {"$regex": re.escape(q), "$options": "i"}},
            {"nombre_comercial": {"$regex": re.escape(q), "$options": "i"}},
        ]
    })
    if p:
        return {
            "persona_id": p.get("persona_id") or str(p.get("id") or ""),
            "nombre": p.get("nombre") or p.get("razon_social"),
            "nombre_comercial": p.get("nombre_comercial"),
            "ruc": p.get("ruc") or p.get("cedula"),
            "source": "mongo_personas",
        }

    try:
        from inneros_core_runtime import contifico_billing as bill
        res = bill.customer_search(query=q, entity_id=entity_id, max_pages=3)
        if res.get("ok") and res.get("customers"):
            first = res["customers"][0]
            return {
                "persona_id": first.get("persona_id"),
                "nombre": first.get("razon_social"),
                "nombre_comercial": first.get("nombre_comercial"),
                "ruc": first.get("ruc") or first.get("cedula"),
                "source": "contifico_api_live",
            }
    except Exception:
        pass
    return None


def contifico_read_query(
    *,
    proveedor: Optional[str] = None,
    cliente: Optional[str] = None,
    producto: Optional[str] = None,
    documento: Optional[str] = None,
    fecha: Optional[str] = None,
    year: Optional[int] = None,
    tipo: str = "all",
    cruce_margen: bool = False,
    limit: int = 50,
    include_detalles: bool = True,
    entity_id: str = "pcdoctor",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute a read-only query for purchases, sales, products, and margin analysis."""
    t0 = time.perf_counter()
    db = _db()
    lim = max(1, min(int(limit or 50), 200))

    target_persona = proveedor or cliente
    persona_info = resolve_persona_cached_or_live(target_persona, entity_id=entity_id) if target_persona else None
    pid = persona_info["persona_id"] if persona_info else None

    tipo_norm = str(tipo or "all").lower().strip()

    # Build conjunction of filters (AND logic)
    and_clauses: List[Dict[str, Any]] = []

    # 1. Persona & Tipo Registro filters
    if pid:
        and_clauses.append({"persona_id": pid})
    elif target_persona:
        and_clauses.append({
            "$or": [
                {"descripcion": {"$regex": re.escape(target_persona), "$options": "i"}},
                {"persona_id": target_persona},
            ]
        })

    if proveedor or tipo_norm == "compra":
        and_clauses.append({"tipo_registro": "PRO"})
    elif cliente or tipo_norm == "venta":
        and_clauses.append({"tipo_registro": {"$ne": "PRO"}})
        and_clauses.append({"tipo_documento": {"$in": ["FAC", "COT"]}})

    # 2. Document filter
    if documento:
        doc_q = documento.strip()
        and_clauses.append({
            "$or": [
                {"documento": {"$regex": re.escape(doc_q), "$options": "i"}},
                {"contifico_id": doc_q},
                {"ralfia_number": {"$regex": re.escape(doc_q), "$options": "i"}},
            ]
        })

    # 3. Date / Year filters with normalization
    if year:
        y_int = int(year)
        and_clauses.append({
            "$or": [
                {"year": y_int},
                {"fecha_iso": {"$regex": f"^{y_int}-"}},
                {"fecha_emision": {"$regex": f"/{y_int}$|/{y_int} "}},
            ]
        })

    if fecha:
        dt_parsed = parse_and_normalize_date(fecha)
        if dt_parsed:
            d_dmY = dt_parsed.strftime("%d/%m/%Y")
            d_Ymd = dt_parsed.strftime("%Y-%m-%d")
            and_clauses.append({
                "$or": [
                    {"fecha_emision": {"$regex": re.escape(d_dmY)}},
                    {"fecha_emision": {"$regex": re.escape(d_Ymd)}},
                    {"fecha_iso": d_Ymd},
                ]
            })
        else:
            and_clauses.append({
                "$or": [
                    {"fecha_emision": {"$regex": re.escape(fecha), "$options": "i"}},
                    {"fecha_iso": {"$regex": re.escape(fecha), "$options": "i"}},
                ]
            })

    # 4. Product filter
    if producto:
        p_re = {"$regex": re.escape(producto.strip()), "$options": "i"}
        and_clauses.append({
            "$or": [
                {"lineas.producto_nombre": p_re},
                {"lineas.descripcion": p_re},
                {"descripcion": p_re},
            ]
        })

    query_filter: Dict[str, Any] = {"$and": and_clauses} if and_clauses else {}

    cur = db[DOCS_COL].find(query_filter).sort("fecha_emision", -1).limit(lim)
    raw_docs = list(cur)

    formatted_docs: List[Dict[str, Any]] = []
    prod_lower = (producto or "").lower().strip()

    for d in raw_docs:
        matching_lines = []
        for l in d.get("lineas") or []:
            pname = str(l.get("producto_nombre") or l.get("descripcion") or "")
            if not prod_lower or prod_lower in pname.lower():
                matching_lines.append({
                    "producto": pname,
                    "producto_id": l.get("producto_id"),
                    "sku": l.get("codigo_bien") or l.get("serie"),
                    "cantidad": float(l.get("cantidad") or 0),
                    "precio": float(l.get("precio") or 0),
                    "total": float(l.get("total") or l.get("base_gravable") or 0),
                })

        raw_fecha = d.get("fecha_emision")
        iso_fecha = format_iso_date(raw_fecha) or d.get("fecha_iso")

        formatted_docs.append({
            "contifico_id": d.get("contifico_id"),
            "documento": d.get("documento"),
            "tipo_documento": d.get("tipo_documento"),
            "tipo_registro": d.get("tipo_registro", "CLI"),
            "fecha_emision": iso_fecha or raw_fecha,
            "fecha_emision_raw": raw_fecha,
            "fecha_iso": iso_fecha,
            "total": float(d.get("total_num") or d.get("total") or 0),
            "subtotal": float(d.get("subtotal_num") or d.get("subtotal") or 0),
            "iva": float(d.get("iva_num") or d.get("iva") or 0),
            "persona_id": d.get("persona_id"),
            "lineas": matching_lines if include_detalles else None,
            "lineas_count": len(matching_lines),
        })

    # Cruce de margen con correspondencia verificable y trazabilidad temporal
    cruce_resultados: List[Dict[str, Any]] = []
    if cruce_margen or tipo_norm == "cruce":
        # Extract purchase line items
        purchase_items = []
        for fd in formatted_docs:
            if fd.get("tipo_registro") == "PRO":
                p_dt = parse_and_normalize_date(fd.get("fecha_emision_raw") or fd.get("fecha_emision"))
                for l in (fd.get("lineas") or []):
                    purchase_items.append({
                        "doc_compra": fd["documento"],
                        "fecha_compra": fd["fecha_emision"],
                        "fecha_compra_dt": p_dt,
                        "producto": l["producto"],
                        "producto_id": l.get("producto_id"),
                        "sku": l.get("sku"),
                        "costo_unitario": l["precio"],
                        "cantidad_compra": l["cantidad"],
                    })

        if purchase_items:
            # Query candidate sales
            sales_docs = list(db[DOCS_COL].find({
                "tipo_documento": "FAC",
                "tipo_registro": {"$ne": "PRO"},
                "persona_id": {"$ne": pid}
            }))

            # Index sales by producto_id and by exact normalized product name
            sales_by_pid: Dict[str, List[Dict[str, Any]]] = {}
            sales_by_norm_name: Dict[str, List[Dict[str, Any]]] = {}

            for sd in sales_docs:
                s_dt = parse_and_normalize_date(sd.get("fecha_emision"))
                for sl in sd.get("lineas") or []:
                    sname = str(sl.get("producto_nombre") or "").strip()
                    sprice = float(sl.get("precio") or 0)
                    spid = sl.get("producto_id")
                    if sprice > 0:
                        sale_item = {
                            "doc_venta": sd.get("documento"),
                            "fecha_venta": format_iso_date(sd.get("fecha_emision")),
                            "fecha_venta_dt": s_dt,
                            "producto_venta": sname,
                            "precio_venta": sprice,
                            "producto_id": spid,
                            "norm_name": normalize_sku_name(sname),
                        }
                        if spid:
                            sales_by_pid.setdefault(spid, []).append(sale_item)
                        if sale_item["norm_name"]:
                            sales_by_norm_name.setdefault(sale_item["norm_name"], []).append(sale_item)

            for p_item in purchase_items:
                pid_k = p_item.get("producto_id")
                norm_p = normalize_sku_name(p_item["producto"])
                p_dt = p_item.get("fecha_compra_dt")
                cost = p_item["costo_unitario"]

                # 1. Look for verified matches: primary by exact producto_id
                candidates: List[Dict[str, Any]] = []
                match_method = "none"
                if pid_k and pid_k in sales_by_pid:
                    candidates = sales_by_pid[pid_k]
                    match_method = "sku_producto_id"
                elif norm_p and norm_p in sales_by_norm_name:
                    candidates = sales_by_norm_name[norm_p]
                    match_method = "sku_exact_name"

                # 2. Enforce temporal traceability: sale must occur on or after purchase
                valid_sales = [
                    c for c in candidates
                    if c.get("fecha_venta_dt") and p_dt and c["fecha_venta_dt"] >= p_dt
                ]

                if valid_sales:
                    # Pick the closest chronological sale on or after purchase date
                    valid_sales.sort(key=lambda x: x["fecha_venta_dt"])
                    best_sale = valid_sales[0]
                    price = best_sale["precio_venta"]
                    margen = round(price - cost, 2)
                    pct_margen = round((margen / price) * 100, 1) if price > 0 else 0.0
                    markup = round((margen / cost) * 100, 1) if cost > 0 else 0.0
                    days_diff = (best_sale["fecha_venta_dt"] - p_dt).days if p_dt else None

                    cruce_resultados.append({
                        "categoria": p_item["producto"].split()[0].upper() if p_item["producto"] else "GENERAL",
                        "producto_compra": p_item["producto"],
                        "producto_id": pid_k,
                        "doc_compra": p_item["doc_compra"],
                        "fecha_compra": p_item["fecha_compra"],
                        "costo_unitario": cost,
                        "producto_venta": best_sale["producto_venta"],
                        "doc_venta": best_sale["doc_venta"],
                        "fecha_venta": best_sale["fecha_venta"],
                        "precio_venta_unitario": price,
                        "margen_bruto_unitario": margen,
                        "margen_pct": pct_margen,
                        "markup_pct": markup,
                        "estado": "verificado",
                        "correspondencia": match_method,
                        "trazabilidad_temporal": f"valida (+{days_diff}d)" if days_diff is not None else "valida",
                        "dias_hasta_venta": days_diff,
                    })
                else:
                    # Insufficient verifiable correspondence or no sale after purchase
                    cruce_resultados.append({
                        "categoria": p_item["producto"].split()[0].upper() if p_item["producto"] else "GENERAL",
                        "producto_compra": p_item["producto"],
                        "producto_id": pid_k,
                        "doc_compra": p_item["doc_compra"],
                        "fecha_compra": p_item["fecha_compra"],
                        "costo_unitario": cost,
                        "producto_venta": None,
                        "doc_venta": None,
                        "fecha_venta": None,
                        "precio_venta_unitario": None,
                        "margen_bruto_unitario": "sin margen verificable",
                        "margen_pct": "sin margen verificable",
                        "markup_pct": "sin margen verificable",
                        "estado": "sin margen verificable",
                        "correspondencia": match_method if candidates else "no_match",
                        "trazabilidad_temporal": "sin venta posterior verificable",
                        "dias_hasta_venta": None,
                    })

    has_cruce = bool(cruce_margen or tipo_norm == "cruce")
    verified_cruces = [c for c in cruce_resultados if c.get("estado") == "verificado"]

    response_payload = {
        "ok": True,
        "entity_id": entity_id,
        "query": {
            "proveedor": proveedor,
            "cliente": cliente,
            "persona_resuelta": persona_info,
            "producto": producto,
            "documento": documento,
            "fecha": fecha or year,
            "tipo": tipo_norm,
        },
        "count": len(formatted_docs),
        "documentos": formatted_docs,
        "cruce_margen": cruce_resultados if has_cruce else None,
        "cruce_count": len(cruce_resultados) if has_cruce else 0,
        "cruce_verificados_count": len(verified_cruces) if has_cruce else 0,
        "cruce_status": (
            "verificado" if verified_cruces else "sin margen verificable"
        ) if has_cruce else None,
        "provenance": {
            "source": f"pcdoctor_swarm.{DOCS_COL} + live_api",
            "read_only": True,
            "mode": "verified_accounting_records",
            "date_normalized": True,
            "temporal_traceability_enforced": True,
            "sku_correspondence_enforced": True,
        },
    }

    _log_query(response_payload["query"], len(formatted_docs), t0, entity_id=entity_id)
    return response_payload
