"""Contífico analytics — query DSL read-only (piloto Capability Router Fase 0).

No SQL/Mongo libre. Allowlist de medidas/dimensiones/filtros.
No escribe en Contífico. Audita en contifico_query_log.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import contifico_normalize, mongo_store

QUERY_LOG_COL = "contifico_query_log"
DOCS_COL = "contifico_documents"
TXN_COL = "contifico_transactions"
BANK_MOVES_COL = "contifico_bank_movements"

# Contífico estados observados: C cobrado/cerrado, P pendiente, A anulado
ESTADO_PENDING = {"P", "p", "pendiente"}
ESTADO_CANCELLED = {"A", "a", "anulado"}

METRICS: dict[str, dict[str, Any]] = {
    "gross_sales": {
        "label": "Ventas brutas (FAC)",
        "formula": "sum(total_num) where tipo_documento=FAC and estado not in (A)",
        "sources": [DOCS_COL],
        "default_tipo": "FAC",
    },
    "invoiced_total": {
        "label": "Total facturado",
        "formula": "alias de gross_sales",
        "sources": [DOCS_COL],
        "default_tipo": "FAC",
    },
    "quote_count": {
        "label": "Cantidad cotizaciones",
        "formula": "count docs tipo COT",
        "sources": [DOCS_COL],
        "default_tipo": "COT",
        "agg": "count",
    },
    "quote_total": {
        "label": "Monto cotizado",
        "formula": "sum(total_num) COT",
        "sources": [DOCS_COL],
        "default_tipo": "COT",
    },
    "credit_notes": {
        "label": "Notas de crédito",
        "formula": "sum(total_num) NCT",
        "sources": [DOCS_COL],
        "default_tipo": "NCT",
    },
    "open_receivables": {
        "label": "Cartera pendiente",
        "formula": "sum(total_num) FAC estado=P",
        "sources": [DOCS_COL],
        "default_tipo": "FAC",
        "estado": "P",
    },
    "paid_bank_movements": {
        "label": "Movimientos bancarios (monto)",
        "formula": "sum(monto) contifico_bank_movements",
        "sources": [BANK_MOVES_COL],
    },
    "txn_total": {
        "label": "Total transacciones/caja",
        "formula": "sum(total) contifico_transactions",
        "sources": [TXN_COL],
    },
    "document_count": {
        "label": "Conteo documentos",
        "formula": "count docs con filtros",
        "sources": [DOCS_COL],
        "agg": "count",
    },
}

DIMENSIONS = {"year", "month", "tipo_documento", "estado", "persona_id", "party_name"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def analytics_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "read_only_pilot",
        "domains": ["sales", "quotes", "receivables", "banking", "cash"],
        "metrics": {k: {"label": v["label"], "formula": v["formula"]} for k, v in METRICS.items()},
        "dimensions": sorted(DIMENSIONS),
        "filters": ["year", "month", "persona_query", "persona_id", "tax_id", "tipo_documento", "estado", "limit"],
        "note": "DSL allowlist. No Mongo/SQL libre. Contífico=conector; MOD-ACCOUNTING=canónico futuro.",
    }


def explain_metric(metric: str) -> dict[str, Any]:
    key = (metric or "").strip().lower()
    if key not in METRICS:
        return {"ok": False, "error": "unknown_metric", "available": sorted(METRICS)}
    m = METRICS[key]
    return {"ok": True, "metric": key, **m}


def resolve_entity(query: str, entity_type: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Resuelve party/persona/documento/banco con ranking simple."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query_required"}
    et = (entity_type or "auto").lower()
    matches: list[dict[str, Any]] = []
    if et in {"auto", "party", "persona", "client", "supplier"}:
        pers = contifico_normalize.resolve_contifico_persona(q, limit=limit)
        for i, m in enumerate(pers.get("matches") or []):
            matches.append(
                {
                    "type": "persona",
                    "id": m.get("persona_id"),
                    "label": m.get("nombre"),
                    "tax_id": m.get("ruc"),
                    "party_id": m.get("party_id"),
                    "rank": i + 1,
                    "score": max(0.1, 1.0 - i * 0.08),
                    "aliases": [m.get("nombre_comercial")] if m.get("nombre_comercial") else [],
                }
            )
    if et in {"auto", "document", "doc"} and len(q) >= 4:
        docs = contifico_normalize.search_contifico_documents(query=q, documento=q, limit=min(limit, 10))
        for i, d in enumerate(docs.get("documents") or []):
            matches.append(
                {
                    "type": "document",
                    "id": d.get("contifico_id"),
                    "label": d.get("ralfia_number") or f"{d.get('tipo_documento')}-{d.get('documento')}",
                    "persona_id": d.get("persona_id"),
                    "rank": i + 1,
                    "score": 0.85 - i * 0.05,
                }
            )
    if et in {"auto", "bank", "account"}:
        from raphiia_openai import contifico_ledger

        banks = contifico_ledger.get_bank_account_balance(q if len(q) > 2 else None)
        for i, a in enumerate(banks.get("accounts") or []):
            matches.append(
                {
                    "type": "bank_account",
                    "id": a.get("account_id"),
                    "label": a.get("nombre"),
                    "numero": a.get("numero"),
                    "saldo_calculado": a.get("saldo_calculado"),
                    "rank": i + 1,
                    "score": 0.9 - i * 0.05,
                }
            )
    matches.sort(key=lambda x: -float(x.get("score") or 0))
    return {
        "ok": True,
        "query": q,
        "entity_type": et,
        "count": len(matches[:limit]),
        "matches": matches[:limit],
        "best": matches[0] if matches else None,
    }


def _resolve_persona_id(filters: dict[str, Any]) -> str | None:
    if filters.get("persona_id"):
        return str(filters["persona_id"])
    q = filters.get("persona_query") or filters.get("tax_id") or filters.get("client")
    if not q:
        return None
    best = contifico_normalize.resolve_contifico_persona(str(q), limit=1).get("best_match")
    return (best or {}).get("persona_id")


def _log_query(entry: dict[str, Any]) -> str:
    qid = f"cq_{uuid.uuid4().hex[:16]}"
    doc = {"query_id": qid, **entry, "created_at": _now()}
    try:
        _db()[QUERY_LOG_COL].insert_one(doc)
    except Exception:
        pass
    return qid


def contifico_query(
    *,
    domain: str = "sales",
    measures: list[str] | None = None,
    dimensions: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    sort: str | None = None,
    limit: int = 20,
    include_details: bool = False,
    natural_language: str | None = None,
    actor: str = "mcp",
) -> dict[str, Any]:
    """Consulta parametrizada allowlist."""
    t0 = time.perf_counter()
    filters = dict(filters or {})
    measures = measures or ["gross_sales"]
    dimensions = dimensions or []
    for m in measures:
        if m not in METRICS:
            return {"ok": False, "error": "unknown_measure", "measure": m, "available": sorted(METRICS)}
    for d in dimensions:
        if d not in DIMENSIONS:
            return {"ok": False, "error": "unknown_dimension", "dimension": d, "available": sorted(DIMENSIONS)}

    persona_id = _resolve_persona_id(filters)
    year = filters.get("year")
    month = filters.get("month")
    tipo = filters.get("tipo_documento")
    estado = filters.get("estado")
    lim = max(1, min(int(limit or 20), 100))

    results: list[dict[str, Any]] = []
    provenance: list[str] = []

    # Banking / txn measures
    if any(m in {"paid_bank_movements", "txn_total"} for m in measures):
        from raphiia_openai import contifico_ledger

        if "paid_bank_movements" in measures:
            mov = contifico_ledger.search_bank_movements(
                persona_query=filters.get("persona_query"),
                year=int(year) if year else None,
                limit=lim,
            )
            provenance.append(BANK_MOVES_COL)
            results.append(
                {
                    "measure": "paid_bank_movements",
                    "value": mov.get("total_amount"),
                    "count": mov.get("count"),
                    "rows": mov.get("movements") if include_details else None,
                }
            )
        if "txn_total" in measures:
            tx = contifico_ledger.search_transactions(
                persona_query=filters.get("persona_query"),
                year=int(year) if year else None,
                limit=lim,
            )
            provenance.append(TXN_COL)
            results.append(
                {
                    "measure": "txn_total",
                    "value": tx.get("total_amount"),
                    "count": tx.get("count"),
                    "rows": tx.get("transactions") if include_details else None,
                }
            )

    doc_measures = [m for m in measures if m not in {"paid_bank_movements", "txn_total"}]
    if doc_measures:
        provenance.append(DOCS_COL)
        db = _db()
        for measure in doc_measures:
            meta = METRICS[measure]
            match: dict[str, Any] = {}
            doc_tipo = tipo or meta.get("default_tipo")
            if doc_tipo:
                match["tipo_documento"] = str(doc_tipo).upper()
            if year:
                match["year"] = int(year)
            if month:
                match["month"] = int(month)
            if persona_id:
                match["persona_id"] = persona_id
            est = estado or meta.get("estado")
            if est:
                match["estado"] = est
            elif measure == "gross_sales" or measure == "invoiced_total":
                match["estado"] = {"$nin": list(ESTADO_CANCELLED)}

            # Top / group by client
            group_by_persona = "persona_id" in dimensions or sort in {"top", "top_client", "-value"}
            if group_by_persona and not persona_id and measure in {
                "gross_sales",
                "invoiced_total",
                "quote_total",
                "quote_count",
                "open_receivables",
                "document_count",
            }:
                value_expr: Any = {"$sum": 1} if meta.get("agg") == "count" or measure == "quote_count" else {"$sum": {"$ifNull": ["$total_num", 0]}}
                pipe = [
                    {"$match": match},
                    {"$group": {"_id": "$persona_id", "value": value_expr, "count": {"$sum": 1}}},
                    {"$sort": {"value": -1}},
                    {"$limit": lim},
                ]
                rows = list(db[DOCS_COL].aggregate(pipe))
                enriched = []
                for row in rows:
                    pid = row.get("_id")
                    p = db.contifico_personas.find_one({"persona_id": pid}, {"nombre": 1, "ruc": 1}) or {}
                    enriched.append(
                        {
                            "persona_id": pid,
                            "nombre": p.get("nombre") or pid,
                            "ruc": p.get("ruc"),
                            "value": round(float(row.get("value") or 0), 2),
                            "count": row.get("count"),
                        }
                    )
                results.append(
                    {
                        "measure": measure,
                        "grouped_by": "persona_id",
                        "rows": enriched,
                        "top": enriched[0] if enriched else None,
                    }
                )
                continue

            if meta.get("agg") == "count" or measure == "quote_count":
                n = db[DOCS_COL].count_documents(match)
                results.append({"measure": measure, "value": n, "filter": match})
            else:
                pipe = [
                    {"$match": match},
                    {
                        "$group": {
                            "_id": None,
                            "value": {"$sum": {"$ifNull": ["$total_num", 0]}},
                            "count": {"$sum": 1},
                        }
                    },
                ]
                agg = list(db[DOCS_COL].aggregate(pipe))
                summary = agg[0] if agg else {"value": 0, "count": 0}
                detail_rows = None
                if include_details:
                    detail_rows = list(
                        db[DOCS_COL]
                        .find(match, {"_id": 0, "lineas": 0, "cobros": 0})
                        .sort("fecha_iso", -1)
                        .limit(lim)
                    )
                results.append(
                    {
                        "measure": measure,
                        "value": round(float(summary.get("value") or 0), 2),
                        "count": summary.get("count", 0),
                        "filter": match,
                        "rows": detail_rows,
                    }
                )

    ms = int((time.perf_counter() - t0) * 1000)
    qid = _log_query(
        {
            "actor": actor,
            "natural_language": natural_language,
            "domain": domain,
            "measures": measures,
            "dimensions": dimensions,
            "filters": filters,
            "persona_id": persona_id,
            "sources": provenance,
            "row_count": sum(int(r.get("count") or len(r.get("rows") or []) or 0) for r in results),
            "execution_ms": ms,
            "catalog_version": __import__("raphiia_openai.mcp_catalog.tool_catalog", fromlist=["MCP_VERSION"]).MCP_VERSION,
        }
    )
    return {
        "ok": True,
        "query_id": qid,
        "domain": domain,
        "results": results,
        "persona_id": persona_id,
        "provenance": {
            "collections": provenance,
            "filters": filters,
            "execution_ms": ms,
            "mode": "read_only_pilot",
        },
    }


def get_document(document_id: str | None = None, number: str | None = None) -> dict[str, Any]:
    db = _db()
    doc = None
    if document_id:
        doc = db[DOCS_COL].find_one({"contifico_id": document_id})
    if not doc and number:
        doc = db[DOCS_COL].find_one({"ralfia_number": number}) or db[DOCS_COL].find_one({"documento": number})
    if not doc:
        return {"ok": False, "error": "not_found"}
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    # strip huge payloads optionally keep lineas
    persona = None
    if doc.get("persona_id"):
        persona = db.contifico_personas.find_one({"persona_id": doc["persona_id"]}, {"_id": 0, "raw": 0})
    return {"ok": True, "document": doc, "persona": persona}


def get_party_360(query: str, period_year: int | None = None) -> dict[str, Any]:
    pers = contifico_normalize.resolve_contifico_persona(query, limit=1).get("best_match")
    if not pers:
        return {"ok": False, "error": "persona_not_found", "query": query}
    year = period_year
    summary = contifico_normalize.get_contifico_client_summary(query, year=year)
    sales = contifico_query(
        domain="sales",
        measures=["gross_sales", "quote_count", "quote_total", "credit_notes", "open_receivables"],
        filters={"persona_query": query, "year": year} if year else {"persona_query": query},
        actor="party_360",
    )
    bank = contifico_query(
        domain="banking",
        measures=["paid_bank_movements", "txn_total"],
        filters={"persona_query": query, "year": year} if year else {"persona_query": query},
        actor="party_360",
    )
    return {
        "ok": True,
        "persona": pers,
        "year": year,
        "by_type": (summary or {}).get("by_type"),
        "analytics": {"sales": sales.get("results"), "banking": bank.get("results")},
        "recent_documents": (summary or {}).get("recent_documents", [])[:10],
    }
