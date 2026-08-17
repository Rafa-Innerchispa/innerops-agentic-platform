"""Normalización Contífico ledger (bancos, transacciones, cuentas) + consultas.

Convierte contifico_mirror → colecciones tipadas consultables.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from raphiia_openai import mongo_store

MIRROR_COL = "contifico_mirror"
BANK_ACCOUNTS_COL = "contifico_bank_accounts"
BANK_MOVES_COL = "contifico_bank_movements"
TXN_COL = "contifico_transactions"
ACCT_COL = "contifico_accounts"
COST_CENTERS_COL = "contifico_cost_centers"
WAREHOUSES_COL = "contifico_warehouses"
PERSONAS_COL = "contifico_personas"


def _db():
    return mongo_store.get_db()


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip().replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(text) if text not in {"", ".", "-", "-."} else default
    except ValueError:
        return default


def _parse_fecha(raw: Any) -> dict[str, Any]:
    text = _norm(raw)
    out = {"fecha_raw": text, "fecha_iso": None, "year": None, "month": None}
    if not text:
        return out
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text[:10], fmt)
            out["fecha_iso"] = dt.date().isoformat()
            out["year"] = dt.year
            out["month"] = dt.month
            return out
        except ValueError:
            continue
    return out


def ensure_ledger_indexes() -> dict[str, Any]:
    db = _db()
    specs = [
        (BANK_ACCOUNTS_COL, [("account_id", 1)], {"name": "ux_cba_id", "unique": True}),
        (BANK_MOVES_COL, [("movement_id", 1)], {"name": "ux_cbm_id", "unique": True}),
        (BANK_MOVES_COL, [("cuenta_bancaria_id", 1), ("fecha_iso", -1)], {"name": "ix_cbm_cuenta_fecha"}),
        (BANK_MOVES_COL, [("persona_id", 1)], {"name": "ix_cbm_persona", "sparse": True}),
        (TXN_COL, [("txn_id", 1)], {"name": "ux_ctxn_id", "unique": True}),
        (TXN_COL, [("persona_id", 1), ("fecha_iso", -1)], {"name": "ix_ctxn_persona_fecha"}),
        (TXN_COL, [("tipo", 1), ("year", 1)], {"name": "ix_ctxn_tipo_year"}),
        (ACCT_COL, [("account_id", 1)], {"name": "ux_cacct_id", "unique": True}),
        (ACCT_COL, [("codigo", 1)], {"name": "ix_cacct_codigo"}),
        (COST_CENTERS_COL, [("center_id", 1)], {"name": "ux_ccc_id", "unique": True}),
        (WAREHOUSES_COL, [("warehouse_id", 1)], {"name": "ux_cwh_id", "unique": True}),
    ]
    created = []
    for col, keys, kwargs in specs:
        try:
            db[col].create_index(keys, **kwargs)
            created.append(kwargs.get("name"))
        except Exception:
            continue
    return {"ok": True, "indexes": created}


def _mirror_items(resource: str) -> list[dict[str, Any]]:
    doc = _db()[MIRROR_COL].find_one({"resource": resource}) or {}
    items = doc.get("items") or []
    return [i for i in items if isinstance(i, dict)]


def normalize_bank_accounts() -> dict[str, Any]:
    db = _db()
    ensure_ledger_indexes()
    n = 0
    for raw in _mirror_items("banco_cuentas"):
        aid = _norm(raw.get("id"))
        if not aid:
            continue
        db[BANK_ACCOUNTS_COL].update_one(
            {"account_id": aid},
            {
                "$set": {
                    "account_id": aid,
                    "nombre": _norm(raw.get("nombre")),
                    "numero": _norm(raw.get("numero")),
                    "tipo_cuenta": _norm(raw.get("tipo_cuenta")),
                    "estado": _norm(raw.get("estado")),
                    "saldo_inicial": _safe_float(raw.get("saldo_inicial")),
                    "cuenta_contable": raw.get("cuenta_contable"),
                    "fecha_corte": raw.get("fecha_corte"),
                    "normalized_at": _now(),
                    "source": "contifico_mirror",
                }
            },
            upsert=True,
        )
        n += 1
    return {"ok": True, "upserted": n, "total": db[BANK_ACCOUNTS_COL].count_documents({})}


def normalize_bank_movements() -> dict[str, Any]:
    db = _db()
    ensure_ledger_indexes()
    n = 0
    for raw in _mirror_items("banco_movimientos"):
        mid = _norm(raw.get("id"))
        if not mid:
            continue
        fecha = _parse_fecha(raw.get("fecha_emision"))
        detalles = raw.get("detalles") if isinstance(raw.get("detalles"), list) else []
        monto = 0.0
        for d in detalles:
            if isinstance(d, dict):
                monto += _safe_float(d.get("monto") or d.get("valor") or d.get("valor_pago"))
        persona = raw.get("persona")
        persona_id = ""
        persona_nombre = ""
        if isinstance(persona, dict):
            persona_id = _norm(persona.get("id") or persona.get("persona_id"))
            persona_nombre = _norm(persona.get("razon_social") or persona.get("nombre") or persona.get("nombre_comercial"))
        elif persona:
            persona_id = _norm(persona)
        db[BANK_MOVES_COL].update_one(
            {"movement_id": mid},
            {
                "$set": {
                    "movement_id": mid,
                    "cuenta_bancaria_id": _norm(raw.get("cuenta_bancaria_id")),
                    "tipo": _norm(raw.get("tipo")),
                    "tipo_registro": _norm(raw.get("tipo_registro")),
                    "numero_comprobante": _norm(raw.get("numero_comprobante")),
                    "fecha_emision": raw.get("fecha_emision"),
                    "fecha_iso": fecha["fecha_iso"],
                    "year": fecha["year"],
                    "month": fecha["month"],
                    "monto": round(monto, 2),
                    "persona_id": persona_id,
                    "persona_nombre": persona_nombre,
                    "detalles_count": len(detalles),
                    "normalized_at": _now(),
                    "source": "contifico_mirror",
                }
            },
            upsert=True,
        )
        n += 1
    return {"ok": True, "upserted": n, "total": db[BANK_MOVES_COL].count_documents({})}


def normalize_transactions() -> dict[str, Any]:
    import hashlib

    db = _db()
    ensure_ledger_indexes()
    n = 0
    synthetic = 0
    for raw in _mirror_items("transacciones"):
        tid = _norm(raw.get("id"))
        syn = False
        if not tid:
            # Contífico a veces entrega transacciones sin id — ID estable por campos + detalle
            det_blob = ""
            detalles_raw = raw.get("detalles") if isinstance(raw.get("detalles"), list) else []
            for d in detalles_raw[:5]:
                if isinstance(d, dict):
                    det_blob += f"|{d.get('documento_id')}:{d.get('valor_pago')}:{d.get('cuenta_id')}"
            basis = "|".join(
                [
                    _norm(raw.get("numero_comprobante")),
                    _norm(raw.get("fecha_emision")),
                    _norm(raw.get("persona_id")),
                    _norm(raw.get("documento_id")),
                    str(raw.get("total") or ""),
                    _norm(raw.get("tipo")),
                    _norm(raw.get("forma")),
                    det_blob,
                ]
            )
            if not basis.replace("|", ""):
                continue
            tid = "syn_txn_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:22]
            syn = True
        fecha = _parse_fecha(raw.get("fecha_emision"))
        detalles = raw.get("detalles") if isinstance(raw.get("detalles"), list) else []
        pago_sum = 0.0
        for d in detalles:
            if isinstance(d, dict):
                pago_sum += _safe_float(d.get("valor_pago") or d.get("monto") or d.get("valor"))
        total = _safe_float(raw.get("total"), pago_sum)
        db[TXN_COL].update_one(
            {"txn_id": tid},
            {
                "$set": {
                    "txn_id": tid,
                    "txn_id_synthetic": syn,
                    "tipo": _norm(raw.get("tipo")),
                    "forma": _norm(raw.get("forma")),
                    "numero_comprobante": _norm(raw.get("numero_comprobante")),
                    "persona_id": _norm(raw.get("persona_id")),
                    "documento_id": _norm(raw.get("documento_id")),
                    "cuenta_id": _norm(raw.get("cuenta_id")),
                    "fecha_emision": raw.get("fecha_emision"),
                    "fecha_iso": fecha["fecha_iso"],
                    "year": fecha["year"],
                    "month": fecha["month"],
                    "total": round(total, 2),
                    "detalles_count": len(detalles),
                    "pos": raw.get("pos"),
                    "normalized_at": _now(),
                    "source": "contifico_mirror",
                }
            },
            upsert=True,
        )
        n += 1
        if syn:
            synthetic += 1
    return {
        "ok": True,
        "upserted": n,
        "synthetic_ids": synthetic,
        "total": db[TXN_COL].count_documents({}),
    }


def normalize_accounts() -> dict[str, Any]:
    db = _db()
    ensure_ledger_indexes()
    n = 0
    for raw in _mirror_items("cuentas_contables"):
        aid = _norm(raw.get("id"))
        if not aid:
            continue
        db[ACCT_COL].update_one(
            {"account_id": aid},
            {
                "$set": {
                    "account_id": aid,
                    "codigo": _norm(raw.get("codigo")),
                    "nombre": _norm(raw.get("nombre")),
                    "tipo": _norm(raw.get("tipo")),
                    "normalized_at": _now(),
                    "source": "contifico_mirror",
                }
            },
            upsert=True,
        )
        n += 1
    return {"ok": True, "upserted": n, "total": db[ACCT_COL].count_documents({})}


def normalize_cost_centers() -> dict[str, Any]:
    db = _db()
    ensure_ledger_indexes()
    n = 0
    for raw in _mirror_items("centros_costo"):
        cid = _norm(raw.get("id"))
        if not cid:
            continue
        db[COST_CENTERS_COL].update_one(
            {"center_id": cid},
            {
                "$set": {
                    "center_id": cid,
                    "codigo": _norm(raw.get("codigo")),
                    "nombre": _norm(raw.get("nombre")),
                    "tipo": _norm(raw.get("tipo")),
                    "estado": _norm(raw.get("estado")),
                    "padre_id": _norm(raw.get("padre_id")),
                    "normalized_at": _now(),
                    "source": "contifico_mirror",
                }
            },
            upsert=True,
        )
        n += 1
    return {"ok": True, "upserted": n, "total": db[COST_CENTERS_COL].count_documents({})}


def normalize_warehouses() -> dict[str, Any]:
    db = _db()
    ensure_ledger_indexes()
    n = 0
    for raw in _mirror_items("bodegas"):
        wid = _norm(raw.get("id"))
        if not wid:
            continue
        db[WAREHOUSES_COL].update_one(
            {"warehouse_id": wid},
            {
                "$set": {
                    "warehouse_id": wid,
                    "codigo": _norm(raw.get("codigo")),
                    "nombre": _norm(raw.get("nombre")),
                    "compra": bool(raw.get("compra")),
                    "venta": bool(raw.get("venta")),
                    "produccion": bool(raw.get("produccion")),
                    "normalized_at": _now(),
                    "source": "contifico_mirror",
                }
            },
            upsert=True,
        )
        n += 1
    return {"ok": True, "upserted": n, "total": db[WAREHOUSES_COL].count_documents({})}


def normalize_all_ledger() -> dict[str, Any]:
    return {
        "ok": True,
        "bank_accounts": normalize_bank_accounts(),
        "bank_movements": normalize_bank_movements(),
        "transactions": normalize_transactions(),
        "accounts": normalize_accounts(),
        "cost_centers": normalize_cost_centers(),
        "warehouses": normalize_warehouses(),
    }


def list_bank_accounts() -> dict[str, Any]:
    db = _db()
    rows = list(db[BANK_ACCOUNTS_COL].find({}, {"_id": 0}).sort("nombre", 1))
    # enrich with movement totals
    enriched = []
    for acc in rows:
        aid = acc.get("account_id")
        pipe = [
            {"$match": {"cuenta_bancaria_id": aid}},
            {"$group": {"_id": None, "n": {"$sum": 1}, "monto": {"$sum": "$monto"}}},
        ]
        agg = list(db[BANK_MOVES_COL].aggregate(pipe))
        summary = agg[0] if agg else {"n": 0, "monto": 0}
        saldo_calc = round(_safe_float(acc.get("saldo_inicial")) + _safe_float(summary.get("monto")), 2)
        enriched.append(
            {
                **acc,
                "movements_count": summary.get("n", 0),
                "movements_sum": round(_safe_float(summary.get("monto")), 2),
                "saldo_calculado": saldo_calc,
            }
        )
    return {"ok": True, "count": len(enriched), "accounts": enriched}


def get_bank_account_balance(account_query: str | None = None) -> dict[str, Any]:
    """Saldo por cuenta bancaria (nombre, número o id)."""
    accounts = list_bank_accounts().get("accounts") or []
    if not account_query:
        return {"ok": True, "accounts": accounts}
    q = account_query.strip().lower()
    matched = [
        a
        for a in accounts
        if q in _norm(a.get("nombre")).lower()
        or q in _norm(a.get("numero")).lower()
        or q == _norm(a.get("account_id")).lower()
    ]
    if not matched:
        return {"ok": False, "error": "account_not_found", "query": account_query, "hint": [a.get("nombre") for a in accounts]}
    return {"ok": True, "count": len(matched), "accounts": matched, "best": matched[0]}


def search_bank_movements(
    *,
    account_id: str | None = None,
    persona_query: str | None = None,
    year: int | None = None,
    tipo: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    db = _db()
    filt: dict[str, Any] = {}
    if account_id:
        filt["cuenta_bancaria_id"] = account_id
    if year:
        filt["year"] = int(year)
    if tipo:
        filt["tipo"] = {"$regex": re.escape(tipo), "$options": "i"}
    if persona_query:
        from raphiia_openai import contifico_normalize as cn

        persona = cn.resolve_contifico_persona(persona_query, limit=1).get("best_match")
        if persona:
            filt["$or"] = [
                {"persona_id": persona.get("persona_id")},
                {"persona_nombre": {"$regex": re.escape(persona_query), "$options": "i"}},
            ]
        else:
            filt["persona_nombre"] = {"$regex": re.escape(persona_query), "$options": "i"}
    rows = list(db[BANK_MOVES_COL].find(filt, {"_id": 0}).sort([("fecha_iso", -1)]).limit(max(1, min(limit, 200))))
    total = round(sum(_safe_float(r.get("monto")) for r in rows), 2)
    return {"ok": True, "count": len(rows), "total_amount": total, "filter": filt, "movements": rows}


def search_transactions(
    *,
    persona_query: str | None = None,
    year: int | None = None,
    tipo: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    db = _db()
    filt: dict[str, Any] = {}
    if year:
        filt["year"] = int(year)
    if tipo:
        filt["tipo"] = {"$regex": re.escape(tipo), "$options": "i"}
    if persona_query:
        from raphiia_openai import contifico_normalize as cn

        persona = cn.resolve_contifico_persona(persona_query, limit=1).get("best_match")
        if persona:
            filt["persona_id"] = persona.get("persona_id")
        else:
            return {"ok": False, "error": "persona_not_found", "query": persona_query}
    rows = list(db[TXN_COL].find(filt, {"_id": 0}).sort([("fecha_iso", -1)]).limit(max(1, min(limit, 200))))
    total = round(sum(_safe_float(r.get("total")) for r in rows), 2)
    return {"ok": True, "count": len(rows), "total_amount": total, "filter": filt, "transactions": rows}


def search_accounts(query: str | None = None, limit: int = 50) -> dict[str, Any]:
    db = _db()
    filt: dict[str, Any] = {}
    if query:
        q = query.strip()
        filt["$or"] = [
            {"codigo": {"$regex": re.escape(q), "$options": "i"}},
            {"nombre": {"$regex": re.escape(q), "$options": "i"}},
            {"account_id": q},
        ]
    rows = list(db[ACCT_COL].find(filt, {"_id": 0}).sort("codigo", 1).limit(max(1, min(limit, 200))))
    return {"ok": True, "count": len(rows), "accounts": rows}


def ledger_inventory_summary() -> dict[str, Any]:
    db = _db()
    return {
        "ok": True,
        "bank_accounts": db[BANK_ACCOUNTS_COL].count_documents({}),
        "bank_movements": db[BANK_MOVES_COL].count_documents({}),
        "transactions": db[TXN_COL].count_documents({}),
        "accounts": db[ACCT_COL].count_documents({}),
        "cost_centers": db[COST_CENTERS_COL].count_documents({}),
        "warehouses": db[WAREHOUSES_COL].count_documents({}),
        "personas": db[PERSONAS_COL].count_documents({}),
    }
