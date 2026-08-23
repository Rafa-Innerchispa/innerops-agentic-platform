"""Puente read-only Contifico → RalfIA (migración gradual)."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.settings import (
    CONTIFICO_API_BASE,
    CONTIFICO_API_KEY,
    CONTIFICO_BATCH_PAUSE_EVERY,
    CONTIFICO_BATCH_PAUSE_MS,
    CONTIFICO_COMPANY_TOKEN,
    CONTIFICO_REQUEST_DELAY_MS,
)

MIRROR_COL = "contifico_mirror"
CATALOG_COL = "contifico_catalog"
DOCS_COL = "contifico_documents"
LOCAL_PRODUCTS_COL = "ralfia_local_product_catalog"
SYNC_STATE_COL = "contifico_sync_state"
DEFAULT_TIMEOUT = 60.0

# Endpoints read-only permitidos en fase 1
READ_ENDPOINTS = {
    "cuentas_contables": "/contabilidad/cuenta-contable/",
    "centros_costo": "/contabilidad/centro-costo/",
    "personas": "/persona/",
    "documentos": "/documento/",
    "banco_cuentas": "/banco/cuenta/",
    "banco_movimientos": "/banco/movimiento/",
    "transacciones": "/registro/transaccion/",
    "categorias": "/categoria/",
    "marcas": "/marca/",
    "productos": "/producto/",
    "bodegas": "/bodega/",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _throttle(counter: int) -> None:
    delay = max(0.0, CONTIFICO_REQUEST_DELAY_MS / 1000.0)
    if delay:
        time.sleep(delay)
    if CONTIFICO_BATCH_PAUSE_EVERY > 0 and counter > 0 and counter % CONTIFICO_BATCH_PAUSE_EVERY == 0:
        time.sleep(max(0.0, CONTIFICO_BATCH_PAUSE_MS / 1000.0))


def _sync_state() -> dict[str, Any]:
    doc = mongo_store.get_db()[SYNC_STATE_COL].find_one({"kind": "full_import"}) or {}
    return doc if isinstance(doc, dict) else {}


def _save_sync_state(**fields: Any) -> None:
    mongo_store.get_db()[SYNC_STATE_COL].update_one(
        {"kind": "full_import"},
        {"$set": {"kind": "full_import", "updated_at": _now(), **fields}},
        upsert=True,
    )


def _ralfia_number(tipo: str | None, documento: str | None) -> str:
    td = (tipo or "DOC").strip().upper()
    num = (documento or "").strip()
    return f"{td}-{num}" if num else td


def _parse_documento_seq(documento: str | None) -> int:
    raw = (documento or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _headers() -> dict[str, str]:
    key = (CONTIFICO_API_KEY or "").strip()
    if not key:
        raise ValueError("CONTIFICO_API_KEY no configurado en .env")
    return {"Authorization": key, "Accept": "application/json"}


def _get(path: str, *, page: int = 1, size: int = 50, extra: dict[str, Any] | None = None, throttle_counter: int = 0) -> dict[str, Any]:
    _throttle(throttle_counter)
    params: dict[str, Any] = {"result_page": page, "result_size": size}
    if extra:
        params.update(extra)
    url = f"{CONTIFICO_API_BASE.rstrip('/')}{path}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if not resp.is_success:
        return {"ok": False, "status": resp.status_code, "error": data}
    if isinstance(data, list):
        return {"ok": True, "items": data, "count": len(data), "page": page, "size": size}
    return {"ok": True, "data": data}


def get_contifico_status() -> dict[str, Any]:
    key = (CONTIFICO_API_KEY or "").strip()
    if not key:
        return {"ok": False, "configured": False, "message": "Falta CONTIFICO_API_KEY"}
    try:
        probe = _get("/banco/cuenta/", page=1, size=1)
        return {
            "ok": probe.get("ok", False),
            "configured": True,
            "connected": probe.get("ok", False),
            "api_base": CONTIFICO_API_BASE,
            "company_token_set": bool((CONTIFICO_COMPANY_TOKEN or "").strip()),
            "module": "MOD-CONTIFICO",
            "mode": "read_only_phase_1",
            "readable_endpoints": list(READ_ENDPOINTS.keys()),
        }
    except Exception as exc:
        return {"ok": False, "configured": True, "connected": False, "error": str(exc)}


def list_contifico_cuentas_contables(page: int = 1, size: int = 100) -> dict[str, Any]:
    return _get(READ_ENDPOINTS["cuentas_contables"], page=page, size=size)


def list_contifico_personas(page: int = 1, size: int = 50, role: str | None = None) -> dict[str, Any]:
    out = _get(READ_ENDPOINTS["personas"], page=page, size=size)
    if not out.get("ok") or not role:
        return out
    role = role.lower()
    items = out.get("items") or []
    if role == "cliente":
        items = [p for p in items if p.get("es_cliente")]
    elif role == "proveedor":
        items = [p for p in items if p.get("es_proveedor")]
    out["items"] = items
    out["count"] = len(items)
    return out


def list_contifico_documentos(
    page: int = 1,
    size: int = 20,
    tipo_documento: str | None = None,
) -> dict[str, Any]:
    out = _get(READ_ENDPOINTS["documentos"], page=page, size=size)
    if not out.get("ok") or not tipo_documento:
        return out
    td = tipo_documento.upper()
    items = [d for d in (out.get("items") or []) if str(d.get("tipo_documento") or "").upper() == td]
    out["items"] = items
    out["count"] = len(items)
    return out


def get_contifico_documento(documento_id: str) -> dict[str, Any]:
    doc_id = (documento_id or "").strip()
    if not doc_id:
        return {"ok": False, "error": "documento_id_required"}
    url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{doc_id}/"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if not resp.is_success:
        return {"ok": False, "status": resp.status_code, "error": data}
    return {"ok": True, "documento": data}


def list_contifico_documento_cobros(documento_id: str) -> dict[str, Any]:
    doc_id = (documento_id or "").strip()
    if not doc_id:
        return {"ok": False, "error": "documento_id_required"}
    url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{doc_id}/cobro/"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if not resp.is_success:
        return {"ok": False, "status": resp.status_code, "error": data}
    items = data if isinstance(data, list) else data.get("results") or []
    return {"ok": True, "count": len(items), "cobros": items}


def list_contifico_banco_cuentas(page: int = 1, size: int = 50) -> dict[str, Any]:
    return _get(READ_ENDPOINTS["banco_cuentas"], page=page, size=size)


def list_contifico_banco_movimientos(page: int = 1, size: int = 50) -> dict[str, Any]:
    return _get(READ_ENDPOINTS["banco_movimientos"], page=page, size=size)


def list_contifico_transacciones(page: int = 1, size: int = 50) -> dict[str, Any]:
    return _get(READ_ENDPOINTS["transacciones"], page=page, size=size)


def contifico_capabilities() -> dict[str, Any]:
    """Mapa de lo que Contifico expone y cómo lo usaremos en RalfIA."""
    return {
        "ok": True,
        "phase": "read_only_import",
        "goal": "Migrar a MOD-ACCOUNTING propio y dejar de pagar Contifico",
        "auth": "Header Authorization: API_KEY (el Token UUID es referencia interna/UI)",
        "import_now": {
            "personas": "→ parties (clientes/proveedores)",
            "documentos_FAC": "→ receivables (AR)",
            "documentos_compra": "→ payables (AP)",
            "documento_cobro": "→ collections / payments",
            "banco_movimientos": "→ cheques/pagos bancarios",
            "transacciones": "→ movimientos caja/transferencias",
            "cuentas_contables": "→ plan de cuentas referencia",
            "centros_costo": "→ dimensiones por entidad/proyecto",
            "productos_categorias": "→ inventario/catálogo",
        },
        "actions_later_ralfia_only": [
            "crear factura sin Contifico",
            "registrar cobro/pago",
            "cheques grupo WhatsApp",
            "reportes AP/AR nativos",
        ],
        "write_in_contifico_not_default": [
            "POST documento",
            "POST cobro",
            "PUT envio SRI",
            "POST asiento",
        ],
        "endpoints": READ_ENDPOINTS,
    }


def sync_contifico_snapshot(
    *,
    resources: list[str] | None = None,
    page: int = 1,
    size: int = 50,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Espejo read-only en Mongo para análisis/migración."""
    keys = resources or ["personas", "banco_cuentas", "banco_movimientos", "documentos", "transacciones"]
    plan: dict[str, Any] = {}
    for key in keys:
        path = READ_ENDPOINTS.get(key)
        if not path:
            plan[key] = {"ok": False, "error": "unknown_resource"}
            continue
        if dry_run:
            plan[key] = {"ok": True, "dry_run": True, "endpoint": path, "page": page, "size": size}
            continue
        fetched = _get(path, page=page, size=size)
        if not fetched.get("ok"):
            plan[key] = fetched
            continue
        items = fetched.get("items") or []
        db = mongo_store.get_db()
        db[MIRROR_COL].update_one(
            {"resource": key},
            {
                "$set": {
                    "resource": key,
                    "items": items,
                    "count": len(items),
                    "page": page,
                    "size": size,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
        plan[key] = {"ok": True, "count": len(items), "synced": True}
    return {"ok": True, "dry_run": dry_run, "resources": plan}


def _slug_code(text: str, max_len: int = 12) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").upper()).strip("-")
    return (s[:max_len] or "ITEM").replace("--", "-")


def _fetch_all_pages(path: str, *, size: int = 100, max_pages: int = 200) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    req = 0
    for page in range(1, max_pages + 1):
        fetched = _get(path, page=page, size=size, throttle_counter=req)
        req += 1
        if not fetched.get("ok"):
            break
        batch = fetched.get("items") or []
        if not batch:
            break
        new_batch = []
        for row in batch:
            rid = str(row.get("id") or "")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            new_batch.append(row)
        if not new_batch:
            break
        items.extend(new_batch)
        if len(batch) < size:
            break
    return items


def _fetch_product(product_id: str, *, throttle_counter: int = 0) -> dict[str, Any] | None:
    pid = (product_id or "").strip()
    if not pid:
        return None
    _throttle(throttle_counter)
    url = f"{CONTIFICO_API_BASE.rstrip('/')}/producto/{pid}/"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
    if not resp.is_success:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _collect_product_ids_from_local_documents(db: Any | None = None) -> set[str]:
    """IDs de producto únicos en documentos ya importados (sin API)."""
    database = mongo_store.get_db() if db is None else db
    return {
        str(pid)
        for pid in database[DOCS_COL].distinct(
            "lineas.producto_id",
            {"lineas.producto_id": {"$exists": True, "$ne": None}},
        )
        if pid
    }


def contifico_product_stats() -> dict[str, Any]:
    """Estadísticas del catálogo local (extraído de Contifico, sin llamadas API)."""
    db = mongo_store.get_db()
    catalog = db[CATALOG_COL].find_one({"kind": "productos"}) or {}
    hydrated = int(catalog.get("count") or len(catalog.get("items") or []))
    local_count = db[LOCAL_PRODUCTS_COL].estimated_document_count()
    referenced = local_count or len(
        db[DOCS_COL].distinct("lineas.producto_id", {"lineas.producto_id": {"$exists": True, "$ne": None}})
    )
    cat_doc = db[CATALOG_COL].find_one({"kind": "categorias"}) or {}
    brand_doc = db[CATALOG_COL].find_one({"kind": "marcas"}) or {}
    local_meta = db[LOCAL_PRODUCTS_COL].find_one({"_kind": "meta"}) or {}
    return {
        "ok": True,
        "catalog_source": "local_extracted",
        "local_products": local_count,
        "referenced_product_ids": referenced,
        "hydrated_products": hydrated,
        "categorias": int(cat_doc.get("count") or 0),
        "marcas": int(brand_doc.get("count") or 0),
        "materialized_at": local_meta.get("materialized_at"),
        "note": "Todo local en Mongo; Contifico no se consulta en búsquedas.",
    }


def materialize_local_product_catalog(*, dry_run: bool = False) -> dict[str, Any]:
    """Construye catálogo local desde líneas de documentos ya importados (sin API)."""
    db = mongo_store.get_db()
    if dry_run:
        referenced = len(
            db[DOCS_COL].distinct("lineas.producto_id", {"lineas.producto_id": {"$exists": True, "$ne": None}})
        )
        return {"ok": True, "dry_run": True, "would_materialize": referenced}

    pipeline = [
        {"$match": {"lineas.producto_id": {"$exists": True, "$ne": None}, "lineas.producto_nombre": {"$exists": True, "$ne": None}}},
        {"$unwind": "$lineas"},
        {"$match": {"lineas.producto_id": {"$exists": True, "$ne": None}, "lineas.producto_nombre": {"$exists": True, "$ne": None}}},
        {"$sort": {"fecha_emision": -1}},
        {"$group": {
            "_id": "$lineas.producto_id",
            "name": {"$first": "$lineas.producto_nombre"},
            "last_price": {"$first": "$lineas.precio"},
            "last_document": {"$first": "$ralfia_number"},
            "last_date": {"$first": "$fecha_emision"},
            "usage_count": {"$sum": 1},
        }},
    ]
    rows = list(db[DOCS_COL].aggregate(pipeline, allowDiskUse=True))
    if not dry_run:
        db[LOCAL_PRODUCTS_COL].delete_many({"_kind": {"$ne": "meta"}})
        now = _now()
        if rows:
            docs = []
            for row in rows:
                pid = str(row.get("_id") or "")
                if not pid:
                    continue
                price_raw = row.get("last_price")
                try:
                    price = float(price_raw) if price_raw not in (None, "") else None
                except (TypeError, ValueError):
                    price = None
                docs.append({
                    "product_id": pid,
                    "name": row.get("name") or pid,
                    "last_price": price,
                    "last_document": row.get("last_document"),
                    "last_date": row.get("last_date"),
                    "usage_count": int(row.get("usage_count") or 0),
                    "source": "contifico_documents_local",
                    "materialized_at": now,
                })
            if docs:
                db[LOCAL_PRODUCTS_COL].insert_many(docs, ordered=False)
        db[LOCAL_PRODUCTS_COL].update_one(
            {"_kind": "meta"},
            {"$set": {"_kind": "meta", "count": len(rows), "materialized_at": now, "source": "contifico_documents"}},
            upsert=True,
        )
        db[LOCAL_PRODUCTS_COL].create_index("product_id", unique=True, sparse=True)
        db[LOCAL_PRODUCTS_COL].create_index("name")
    return {"ok": True, "dry_run": False, "materialized": len(rows), "collection": LOCAL_PRODUCTS_COL}


def search_contifico_products(query: str, *, limit: int = 20) -> dict[str, Any]:
    """Busca productos en catálogo local (sin llamadas a Contifico)."""
    from raphiia_openai.operational.inventory_store import accent_insensitive_regex

    raw = (query or "").strip()
    if not raw:
        return {"ok": True, "count": 0, "items": [], "local_only": True}

    db = mongo_store.get_db()
    pattern = accent_insensitive_regex(raw)
    regex = {"$regex": pattern, "$options": "i"}
    seen: set[str] = set()
    items: list[dict[str, Any]] = []

    for prod in db[LOCAL_PRODUCTS_COL].find({"name": regex, "_kind": {"$ne": "meta"}}).sort("usage_count", -1).limit(limit):
        pid = str(prod.get("product_id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        items.append({
            "source": "local_product_catalog",
            "contifico_product_id": pid,
            "codigo": prod.get("codigo"),
            "name": prod.get("name") or prod.get("nombre") or pid,
            "nombre": prod.get("nombre") or prod.get("name"),
            "descripcion": prod.get("descripcion"),
            "marca_nombre": prod.get("marca_nombre"),
            "categoria_nombre": prod.get("categoria_nombre"),
            "categoria_root": prod.get("categoria_root"),
            "unit_price": prod.get("last_price") or prod.get("pvp4") or prod.get("pvp1"),
            "pvp4": prod.get("pvp4"),
            "cantidad_stock": prod.get("cantidad_stock"),
            "sku": prod.get("codigo") or pid,
            "usage_count": prod.get("usage_count"),
            "hydrated": bool(prod.get("codigo")),
        })

    if len(items) < limit:
        catalog = db[CATALOG_COL].find_one({"kind": "productos"}) or {}
        for prod in catalog.get("items") or []:
            pid = str(prod.get("id") or prod.get("contifico_product_id") or "")
            name = str(prod.get("nombre") or prod.get("descripcion") or "")
            codigo = str(prod.get("codigo") or prod.get("legacy_codigo") or "")
            haystack = f"{name} {codigo} {prod.get('categoria_nombre') or ''}".lower()
            if not re.search(pattern, haystack, re.I):
                continue
            if pid in seen:
                continue
            seen.add(pid)
            price = prod.get("precio") or prod.get("precio_venta")
            items.append({
                "source": "contifico_catalog_local",
                "contifico_product_id": pid,
                "name": name or codigo or pid,
                "sku": prod.get("ralfia_sku") or codigo,
                "unit_price": float(price) if price not in (None, "") else None,
                "category": prod.get("categoria_nombre") or prod.get("categoria_root"),
            })
            if len(items) >= limit:
                break

    stats = contifico_product_stats()
    return {
        "ok": True,
        "count": len(items),
        "items": items[:limit],
        "query": raw,
        "local_only": True,
        "local_products_total": stats.get("local_products") or stats.get("referenced_product_ids"),
    }


def hydrate_contifico_products_from_documents(*, max_fetch: int = 200, dry_run: bool = False) -> dict[str, Any]:
    """Hidrata productos Contifico faltantes a partir de producto_id en documentos importados."""
    db = mongo_store.get_db()
    all_ids = {
        str(pid)
        for pid in db[DOCS_COL].distinct("lineas.producto_id", {"lineas.producto_id": {"$exists": True, "$ne": None}})
        if pid
    }
    catalog = db[CATALOG_COL].find_one({"kind": "productos"}) or {}
    existing = {
        str(p.get("id") or p.get("contifico_product_id"))
        for p in (catalog.get("items") or [])
        if p.get("id") or p.get("contifico_product_id")
    }
    missing = sorted(all_ids - existing)
    to_fetch = missing[:max(1, max_fetch)]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "referenced_total": len(all_ids),
            "hydrated_before": len(existing),
            "missing": len(missing),
            "would_fetch": len(to_fetch),
        }

    categorias = catalog.get("items") and db[CATALOG_COL].find_one({"kind": "categorias"}) or {}
    cat_items = (categorias.get("items") if isinstance(categorias, dict) else None) or []
    if not cat_items:
        cat_items = _fetch_all_pages(READ_ENDPOINTS["categorias"], size=500, max_pages=5)
    cat_by_id = {c.get("id"): c for c in cat_items if c.get("id")}

    products = list(catalog.get("items") or [])
    fetched = 0
    req = 0
    for pid in to_fetch:
        prod = _fetch_product(pid, throttle_counter=req)
        req += 1
        if not prod:
            continue
        cat = cat_by_id.get(prod.get("categoria_id")) or {}
        root_name = cat.get("nombre") or "GENERAL"
        if cat.get("padre_id") and cat.get("padre_id") in cat_by_id:
            root_name = cat_by_id[cat["padre_id"]].get("nombre") or root_name
        products.append({
            **prod,
            "ralfia_sku": f"{_slug_code(root_name, 8)}-{_slug_code(prod.get('nombre') or 'item', 10)}",
            "legacy_codigo": prod.get("codigo") or prod.get("id"),
            "categoria_nombre": cat.get("nombre"),
            "categoria_root": root_name,
            "contifico_product_id": prod.get("id"),
        })
        fetched += 1

    now = _now()
    db[CATALOG_COL].update_one(
        {"kind": "productos"},
        {"$set": {"kind": "productos", "items": products, "count": len(products), "synced_at": now}},
        upsert=True,
    )
    return {
        "ok": True,
        "dry_run": False,
        "referenced_total": len(all_ids),
        "hydrated_before": len(existing),
        "missing_before": len(missing),
        "fetched": fetched,
        "hydrated_after": len(products),
    }


def import_contifico_catalog(*, dry_run: bool = False) -> dict[str, Any]:
    """Importa categorías, marcas y productos (vía IDs en documentos)."""
    categorias = _fetch_all_pages(READ_ENDPOINTS["categorias"], size=500, max_pages=3)
    marcas = _fetch_all_pages(READ_ENDPOINTS["marcas"], size=200, max_pages=5)

    cat_by_id = {c.get("id"): c for c in categorias if c.get("id")}
    roots = [c for c in categorias if not c.get("padre_id")]
    db = mongo_store.get_db()
    product_ids = _collect_product_ids_from_local_documents(db)

    docs = _fetch_all_pages(READ_ENDPOINTS["documentos"], size=50, max_pages=2)
    for doc in docs:
        did = doc.get("id")
        if not did:
            continue
        url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{did}/"
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(url, headers=_headers())
        if not resp.is_success:
            continue
        try:
            detail = resp.json()
        except Exception:
            continue
        for line in detail.get("detalles") or []:
            if line.get("producto_id"):
                product_ids.add(str(line["producto_id"]))

    products: list[dict[str, Any]] = []
    for pid in list(product_ids)[:150]:
        prod = _fetch_product(pid)
        if not prod:
            continue
        cat = cat_by_id.get(prod.get("categoria_id")) or {}
        root_name = cat.get("nombre") or "GENERAL"
        if cat.get("padre_id") and cat.get("padre_id") in cat_by_id:
            root_name = cat_by_id[cat["padre_id"]].get("nombre") or root_name
        legacy = prod.get("codigo") or prod.get("id")
        ralfia_sku = f"{_slug_code(root_name, 8)}-{_slug_code(prod.get('nombre') or 'item', 10)}"
        products.append({
            **prod,
            "ralfia_sku": ralfia_sku,
            "legacy_codigo": legacy,
            "categoria_nombre": cat.get("nombre"),
            "categoria_root": root_name,
            "contifico_product_id": prod.get("id"),
        })

    summary = {
        "categorias": len(categorias),
        "marcas": len(marcas),
        "productos": len(products),
        "documentos_scanned": len(docs),
        "roots": len(roots),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, **summary, "sample_roots": [r.get("nombre") for r in roots[:15]]}

    db = mongo_store.get_db()
    now = datetime.now(timezone.utc).isoformat()
    db[CATALOG_COL].update_one(
        {"kind": "categorias"},
        {"$set": {"kind": "categorias", "items": categorias, "count": len(categorias), "synced_at": now}},
        upsert=True,
    )
    db[CATALOG_COL].update_one(
        {"kind": "marcas"},
        {"$set": {"kind": "marcas", "items": marcas, "count": len(marcas), "synced_at": now}},
        upsert=True,
    )
    db[CATALOG_COL].update_one(
        {"kind": "productos"},
        {"$set": {"kind": "productos", "items": products, "count": len(products), "synced_at": now}},
        upsert=True,
    )
    mongo_store.log_sync("contifico_catalog_import", **summary)
    return {"ok": True, "dry_run": False, **summary}


def import_contifico_documents(*, max_docs: int = 200, dry_run: bool = False) -> dict[str, Any]:
    """Importa FAC/COT/NCT con detalle y descripción narrativa."""
    docs = _fetch_all_pages(READ_ENDPOINTS["documentos"], size=50, max_pages=max(1, max_docs // 50))
    imported: list[dict[str, Any]] = []
    for doc in docs[:max_docs]:
        did = doc.get("id")
        if not did:
            continue
        url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{did}/"
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(url, headers=_headers())
        if not resp.is_success:
            continue
        detail = resp.json()
        imported.append({
            "contifico_id": did,
            "ralfia_number": _ralfia_number(detail.get("tipo_documento") or doc.get("tipo_documento"), detail.get("documento") or doc.get("documento")),
            "documento_seq": _parse_documento_seq(detail.get("documento") or doc.get("documento")),
            "tipo_documento": detail.get("tipo_documento") or doc.get("tipo_documento"),
            "documento": detail.get("documento") or doc.get("documento"),
            "fecha_emision": detail.get("fecha_emision"),
            "fecha_vencimiento": detail.get("fecha_vencimiento"),
            "total": detail.get("total"),
            "subtotal": detail.get("subtotal"),
            "iva": detail.get("iva"),
            "descripcion": detail.get("descripcion"),
            "persona_id": detail.get("persona_id"),
            "estado": detail.get("estado"),
            "lineas": detail.get("detalles") or [],
            "cobros": detail.get("cobros") or [],
        })
    if dry_run:
        from collections import Counter
        td = Counter(i.get("tipo_documento") for i in imported)
        return {"ok": True, "dry_run": True, "count": len(imported), "tipos": dict(td)}

    db = mongo_store.get_db()
    now = datetime.now(timezone.utc).isoformat()
    for row in imported:
        db[DOCS_COL].update_one({"contifico_id": row["contifico_id"]}, {"$set": {**row, "synced_at": now}}, upsert=True)
    mongo_store.log_sync("contifico_documents_import", count=len(imported))
    return {"ok": True, "dry_run": False, "count": len(imported)}


def import_contifico_incremental(
    *,
    pages: int = 10,
    size: int = 50,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync diario: importa/actualiza documentos recientes desde Contifico API.

    Recorre las primeras páginas del listado (documentos más recientes) y
    siempre refresca el detalle para capturar nuevas FAC/COT y cambios de estado.
    """
    stubs = _fetch_all_pages(READ_ENDPOINTS["documentos"], size=size, max_pages=max(1, pages))
    if dry_run:
        db = mongo_store.get_db()
        existing = set(db[DOCS_COL].distinct("contifico_id"))
        new_ids = [s.get("id") for s in stubs if s.get("id") and str(s.get("id")) not in existing]
        return {
            "ok": True,
            "dry_run": True,
            "stubs_scanned": len(stubs),
            "would_upsert": len(stubs),
            "would_create_new": len(new_ids),
        }

    db = mongo_store.get_db()
    now = _now()
    imported = 0
    created = 0
    updated = 0
    req = 0
    for stub in stubs:
        did = stub.get("id")
        if not did:
            continue
        existed = db[DOCS_COL].find_one({"contifico_id": str(did)}, {"_id": 1})
        _throttle(req)
        req += 1
        url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{did}/"
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(url, headers=_headers())
        if not resp.is_success:
            continue
        detail = resp.json()
        tipo = detail.get("tipo_documento") or stub.get("tipo_documento")
        numero = detail.get("documento") or stub.get("documento")
        row = {
            "contifico_id": did,
            "ralfia_number": _ralfia_number(tipo, numero),
            "documento_seq": _parse_documento_seq(numero),
            "tipo_documento": tipo,
            "documento": numero,
            "fecha_emision": detail.get("fecha_emision"),
            "fecha_vencimiento": detail.get("fecha_vencimiento"),
            "total": detail.get("total"),
            "subtotal": detail.get("subtotal"),
            "iva": detail.get("iva"),
            "descripcion": detail.get("descripcion"),
            "persona_id": detail.get("persona_id"),
            "estado": detail.get("estado"),
            "lineas": detail.get("detalles") or [],
            "cobros": detail.get("cobros") or [],
            "synced_at": now,
        }
        db[DOCS_COL].update_one({"contifico_id": did}, {"$set": row}, upsert=True)
        imported += 1
        if existed:
            updated += 1
        else:
            created += 1

    _save_sync_state(
        status="idle",
        phase="daily_incremental",
        last_daily_sync=now,
        progress={"imported": imported, "created": created, "updated": updated, "stubs": len(stubs)},
    )
    mongo_store.log_sync(
        "contifico_incremental",
        imported=imported,
        created=created,
        updated=updated,
    )
    return {
        "ok": True,
        "dry_run": False,
        "stubs_scanned": len(stubs),
        "imported": imported,
        "created": created,
        "updated": updated,
    }


def import_contifico_all(*, dry_run: bool = False) -> dict[str, Any]:
    """Importación completa fase 1: personas, bancos, catálogo, documentos."""
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_import": ["personas", "banco_cuentas", "banco_movimientos", "transacciones", "cuentas_contables", "catalog", "documents"],
        }
    results = {
        "snapshot": sync_contifico_snapshot(
            resources=["personas", "banco_cuentas", "banco_movimientos", "transacciones", "cuentas_contables", "centros_costo"],
            page=1,
            size=100,
            dry_run=False,
        ),
        "catalog": import_contifico_catalog(dry_run=False),
        "documents": import_contifico_documents(max_docs=200, dry_run=False),
    }
    return {"ok": True, "results": results}


def get_contifico_sync_status() -> dict[str, Any]:
    """Estado del import numerado con throttling (resume/checkpoint)."""
    st = _sync_state()
    db = mongo_store.get_db()
    from collections import Counter

    tipos = Counter(d.get("tipo_documento") for d in db[DOCS_COL].find({}, {"tipo_documento": 1}))
    return {
        "ok": True,
        "status": st.get("status", "idle"),
        "phase": st.get("phase"),
        "progress": st.get("progress"),
        "delay_ms": CONTIFICO_REQUEST_DELAY_MS,
        "batch_pause_every": CONTIFICO_BATCH_PAUSE_EVERY,
        "documents_in_mongo": db[DOCS_COL].count_documents({}),
        "documents_by_type": dict(tipos),
        "catalog": {d["kind"]: d.get("count") for d in db[CATALOG_COL].find({}, {"kind": 1, "count": 1})},
        "last_error": st.get("last_error"),
        "updated_at": st.get("updated_at"),
    }


def import_contifico_full_sync(
    *,
    dry_run: bool = False,
    resume: bool = True,
    max_documents: int | None = None,
) -> dict[str, Any]:
    """Importación completa con throttling, checkpoint y numeración Contifico→RalfIA."""
    state = _sync_state()
    if state.get("status") == "running":
        return {"ok": False, "error": "import_already_running", "progress": state.get("progress")}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_run": [
                "mirror_all_lists",
                "catalog_categorias_marcas",
                "documents_all_with_detail",
                "products_from_document_lines",
            ],
            "rate_limit": {
                "delay_ms": CONTIFICO_REQUEST_DELAY_MS,
                "batch_pause_every": CONTIFICO_BATCH_PAUSE_EVERY,
                "batch_pause_ms": CONTIFICO_BATCH_PAUSE_MS,
            },
            "numbering": "ralfia_number = TIPO-documento (ej. COT-202607000184)",
            "resume": resume,
        }

    _save_sync_state(status="running", phase="mirror", started_at=_now(), progress={"mirror": 0, "docs": 0, "products": 0})
    db = mongo_store.get_db()
    req = 0
    summary: dict[str, Any] = {}

    try:
        mirror_resources = [
            "personas", "banco_cuentas", "banco_movimientos", "transacciones",
            "cuentas_contables", "centros_costo", "bodegas",
        ]
        for key in mirror_resources:
            path = READ_ENDPOINTS[key]
            items = _fetch_all_pages(path, size=100, max_pages=100)
            db[MIRROR_COL].update_one(
                {"resource": key},
                {"$set": {"resource": key, "items": items, "count": len(items), "synced_at": _now()}},
                upsert=True,
            )
            summary[key] = len(items)
            _save_sync_state(phase="mirror", progress={"mirror": summary, "docs": 0})

        _save_sync_state(phase="catalog")
        categorias = _fetch_all_pages(READ_ENDPOINTS["categorias"], size=500, max_pages=5)
        marcas = _fetch_all_pages(READ_ENDPOINTS["marcas"], size=200, max_pages=5)
        cat_by_id = {c.get("id"): c for c in categorias if c.get("id")}
        now = _now()
        for kind, items in [("categorias", categorias), ("marcas", marcas)]:
            db[CATALOG_COL].update_one(
                {"kind": kind},
                {"$set": {"kind": kind, "items": items, "count": len(items), "synced_at": now}},
                upsert=True,
            )

        _save_sync_state(phase="documents")
        doc_stubs = _fetch_all_pages(READ_ENDPOINTS["documentos"], size=50, max_pages=200)
        if max_documents is not None:
            doc_stubs = doc_stubs[:max_documents]

        done_ids: set[str] = set()
        if resume:
            done_ids = set(db[DOCS_COL].distinct("contifico_id"))

        imported_docs = 0
        product_ids: set[str] = set()
        for idx, stub in enumerate(doc_stubs, start=1):
            did = stub.get("id")
            if not did:
                continue
            if resume and str(did) in done_ids:
                continue
            _throttle(req)
            req += 1
            url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{did}/"
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                resp = client.get(url, headers=_headers())
            if not resp.is_success:
                continue
            detail = resp.json()
            tipo = detail.get("tipo_documento") or stub.get("tipo_documento")
            numero = detail.get("documento") or stub.get("documento")
            row = {
                "contifico_id": did,
                "ralfia_number": _ralfia_number(tipo, numero),
                "documento_seq": _parse_documento_seq(numero),
                "tipo_documento": tipo,
                "documento": numero,
                "fecha_emision": detail.get("fecha_emision"),
                "fecha_vencimiento": detail.get("fecha_vencimiento"),
                "total": detail.get("total"),
                "subtotal": detail.get("subtotal"),
                "iva": detail.get("iva"),
                "descripcion": detail.get("descripcion"),
                "persona_id": detail.get("persona_id"),
                "estado": detail.get("estado"),
                "lineas": detail.get("detalles") or [],
                "cobros": detail.get("cobros") or [],
                "synced_at": now,
            }
            db[DOCS_COL].update_one({"contifico_id": did}, {"$set": row}, upsert=True)
            imported_docs += 1
            for line in row["lineas"]:
                if line.get("producto_id"):
                    product_ids.add(str(line["producto_id"]))
            if idx % 10 == 0:
                _save_sync_state(
                    phase="documents",
                    progress={"mirror": summary, "docs": {"total_stubs": len(doc_stubs), "imported": imported_docs, "current": idx}},
                )

        _save_sync_state(phase="products")
        product_ids = _collect_product_ids_from_local_documents(db)
        existing_catalog = db[CATALOG_COL].find_one({"kind": "productos"}) or {}
        existing_by_id = {
            str(p.get("id") or p.get("contifico_product_id")): p
            for p in (existing_catalog.get("items") or [])
            if p.get("id") or p.get("contifico_product_id")
        }
        products: list[dict[str, Any]] = list(existing_by_id.values())
        for pidx, pid in enumerate(sorted(product_ids - set(existing_by_id.keys())), start=1):
            prod = _fetch_product(pid, throttle_counter=req)
            req += 1
            if not prod:
                continue
            cat = cat_by_id.get(prod.get("categoria_id")) or {}
            root_name = cat.get("nombre") or "GENERAL"
            if cat.get("padre_id") and cat.get("padre_id") in cat_by_id:
                root_name = cat_by_id[cat["padre_id"]].get("nombre") or root_name
            products.append({
                **prod,
                "ralfia_sku": f"{_slug_code(root_name, 8)}-{_slug_code(prod.get('nombre') or 'item', 10)}",
                "legacy_codigo": prod.get("codigo") or prod.get("id"),
                "categoria_nombre": cat.get("nombre"),
                "categoria_root": root_name,
                "contifico_product_id": prod.get("id"),
            })
            if pidx % 20 == 0:
                _save_sync_state(phase="products", progress={"mirror": summary, "docs": imported_docs, "products": pidx})

        db[CATALOG_COL].update_one(
            {"kind": "productos"},
            {"$set": {"kind": "productos", "items": products, "count": len(products), "synced_at": now}},
            upsert=True,
        )

        local_catalog = materialize_local_product_catalog()

        from collections import Counter
        tipos = Counter(d.get("tipo_documento") for d in db[DOCS_COL].find({}, {"tipo_documento": 1}))
        final = {
            "mirror": summary,
            "categorias": len(categorias),
            "marcas": len(marcas),
            "documents_imported_this_run": imported_docs,
            "documents_total": db[DOCS_COL].count_documents({}),
            "documents_by_type": dict(tipos),
            "productos": len(products),
            "product_ids_in_documents": len(product_ids),
            "local_products_materialized": local_catalog.get("materialized"),
            "requests_throttled": req,
        }
        _save_sync_state(status="completed", phase="done", progress=final, completed_at=_now(), last_error=None)
        mongo_store.log_sync("contifico_full_sync", **final)
        return {"ok": True, "dry_run": False, **final}
    except Exception as exc:
        _save_sync_state(status="error", last_error=str(exc))
        return {"ok": False, "error": str(exc), "progress": _sync_state().get("progress")}
