"""Contífico Read-Only Query Engine.

Provides unified read-only querying across Contífico accounting documents (purchases and sales),
transactions, persons, and line items by proveedor, producto, documento, and fecha.
Also provides price, cost, and margin cross-referencing.
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

    filt: Dict[str, Any] = {}
    if pid:
        filt["persona_id"] = pid
    elif target_persona:
        filt["$or"] = [
            {"descripcion": {"$regex": re.escape(target_persona), "$options": "i"}},
            {"persona_id": target_persona},
        ]

    if documento:
        doc_q = documento.strip()
        filt["$or"] = [
            {"documento": {"$regex": re.escape(doc_q), "$options": "i"}},
            {"contifico_id": doc_q},
            {"ralfia_number": {"$regex": re.escape(doc_q), "$options": "i"}},
        ]

    if year:
        filt["$or"] = [
            {"year": int(year)},
            {"fecha_emision": {"$regex": f"/{year}$"}},
        ]
    if fecha:
        filt["fecha_emision"] = {"$regex": re.escape(fecha), "$options": "i"}

    tipo_norm = str(tipo or "all").lower().strip()
    if proveedor or tipo_norm == "compra":
        if "persona_id" in filt:
            filt["$or"] = [{"tipo_registro": "PRO"}, {"persona_id": pid}]
        else:
            filt["tipo_registro"] = "PRO"
    elif cliente or tipo_norm == "venta":
        filt["tipo_registro"] = {"$ne": "PRO"}
        filt["tipo_documento"] = {"$in": ["FAC", "COT"]}

    if producto:
        p_re = {"$regex": re.escape(producto.strip()), "$options": "i"}
        filt["$or"] = [
            {"lineas.producto_nombre": p_re},
            {"lineas.descripcion": p_re},
            {"descripcion": p_re},
        ]

    cur = db[DOCS_COL].find(filt).sort("fecha_emision", -1).limit(lim)
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
                    "cantidad": float(l.get("cantidad") or 0),
                    "precio": float(l.get("precio") or 0),
                    "total": float(l.get("total") or l.get("base_gravable") or 0),
                })

        formatted_docs.append({
            "contifico_id": d.get("contifico_id"),
            "documento": d.get("documento"),
            "tipo_documento": d.get("tipo_documento"),
            "tipo_registro": d.get("tipo_registro", "CLI"),
            "fecha_emision": d.get("fecha_emision"),
            "total": float(d.get("total_num") or d.get("total") or 0),
            "subtotal": float(d.get("subtotal_num") or d.get("subtotal") or 0),
            "iva": float(d.get("iva_num") or d.get("iva") or 0),
            "persona_id": d.get("persona_id"),
            "lineas": matching_lines if include_detalles else None,
            "lineas_count": len(matching_lines),
        })

    # Cruce de margen si solicitado
    cruce_resultados: List[Dict[str, Any]] = []
    if cruce_margen or tipo_norm == "cruce":
        # Extract purchases
        purchase_items = []
        for fd in formatted_docs:
            if fd.get("tipo_registro") == "PRO":
                for l in (fd.get("lineas") or []):
                    purchase_items.append({
                        "doc_compra": fd["documento"],
                        "fecha_compra": fd["fecha_emision"],
                        "producto": l["producto"],
                        "costo_unitario": l["precio"],
                        "cantidad_compra": l["cantidad"],
                    })

        # Pre-query candidate sales documents
        sales_docs = list(db[DOCS_COL].find({
            "tipo_documento": "FAC",
            "tipo_registro": {"$ne": "PRO"},
            "persona_id": {"$ne": pid}
        }))

        sales_hardware = []
        for sd in sales_docs:
            for sl in sd.get("lineas") or []:
                sname = str(sl.get("producto_nombre") or "")
                sprice = float(sl.get("precio") or 0)
                if sprice > 0 and not any(nw in sname.lower() for nw in NOISE_WORDS):
                    sales_hardware.append({
                        "doc_venta": sd.get("documento"),
                        "fecha_venta": sd.get("fecha_emision"),
                        "producto_venta": sname,
                        "precio_venta": sprice,
                        "sname_lower": sname.lower(),
                    })

        for p_item in purchase_items:
            tokens = [
                w.lower() for w in re.findall(r"[A-Za-z0-9]+", p_item["producto"])
                if len(w) >= 3 and w.lower() not in NOISE_WORDS
            ]
            if not tokens:
                continue

            # Look for sale match containing key product descriptors
            for s in sales_hardware:
                match_count = sum(1 for t in tokens[:3] if t in s["sname_lower"])
                if match_count >= min(2, len(tokens)):
                    cost = p_item["costo_unitario"]
                    price = s["precio_venta"]
                    if price > cost:
                        margen = round(price - cost, 2)
                        pct_margen = round((margen / price) * 100, 1)
                        markup = round((margen / cost) * 100, 1)
                        cruce_resultados.append({
                            "categoria": tokens[0].upper(),
                            "producto_compra": p_item["producto"],
                            "doc_compra": p_item["doc_compra"],
                            "fecha_compra": p_item["fecha_compra"],
                            "costo_unitario": cost,
                            "producto_venta": s["producto_venta"],
                            "doc_venta": s["doc_venta"],
                            "fecha_venta": s["fecha_venta"],
                            "precio_venta_unitario": price,
                            "margen_bruto_unitario": margen,
                            "margen_pct": pct_margen,
                            "markup_pct": markup,
                        })
                        break

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
        "cruce_margen": cruce_resultados if (cruce_margen or tipo_norm == "cruce") else None,
        "cruce_count": len(cruce_resultados) if (cruce_margen or tipo_norm == "cruce") else 0,
        "provenance": {
            "source": f"pcdoctor_swarm.{DOCS_COL} + live_api",
            "read_only": True,
            "mode": "verified_accounting_records",
        },
    }

    _log_query(response_payload["query"], len(formatted_docs), t0, entity_id=entity_id)
    return response_payload
