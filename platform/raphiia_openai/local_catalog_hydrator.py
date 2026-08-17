"""RAUL (AG-39) — hidratación local del catálogo Contifico (0 créditos cloud).

Extrae fichas completas vía HTTP local a Contifico (read-only), persiste en Mongo,
y usa Ollama solo para informes de progreso. Pensado para correr en AMD .5 (R9700).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.contifico_bridge import (
    CATALOG_COL,
    DOCS_COL,
    LOCAL_PRODUCTS_COL,
    _collect_product_ids_from_local_documents,
    _fetch_product,
    _now,
    _slug_code,
    contifico_product_stats,
)
from raphiia_openai.settings import (
    CONTIFICO_BATCH_PAUSE_EVERY,
    CONTIFICO_BATCH_PAUSE_MS,
    CONTIFICO_REQUEST_DELAY_MS,
)

HYDRATION_STATE_KIND = "raul_local_hydration"
DEFAULT_BATCH_SIZE = 50
DEFAULT_MODEL = "qwen2.5:14b-instruct-q4_K_M"


def _db():
    return mongo_store.get_db()


def _state_col():
    return _db()["contifico_sync_state"]


def get_hydration_state() -> dict[str, Any]:
    doc = _state_col().find_one({"kind": HYDRATION_STATE_KIND}) or {}
    stats = contifico_product_stats()
    local_full = _db()[LOCAL_PRODUCTS_COL].count_documents(
        {"_kind": {"$ne": "meta"}, "codigo": {"$exists": True, "$ne": ""}}
    )
    return {
        "ok": True,
        "agent": "AG-39_raul_local_catalog",
        "status": doc.get("status", "idle"),
        "phase": doc.get("phase"),
        "progress": doc.get("progress") or {},
        "referenced_product_ids": stats.get("referenced_product_ids"),
        "local_products_indexed": stats.get("local_products"),
        "local_products_full_hydrated": local_full,
        "hydrated_in_catalog": stats.get("hydrated_products"),
        "updated_at": doc.get("updated_at"),
        "last_error": doc.get("last_error"),
        "runtime": "local_amd",
        "cloud_credits": 0,
    }


def _save_state(**fields: Any) -> None:
    _state_col().update_one(
        {"kind": HYDRATION_STATE_KIND},
        {"$set": {"kind": HYDRATION_STATE_KIND, "updated_at": _now(), **fields}},
        upsert=True,
    )


def _usage_counts() -> dict[str, int]:
    pipeline = [
        {"$unwind": "$lineas"},
        {"$match": {"lineas.producto_id": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$lineas.producto_id", "usage_count": {"$sum": 1}}},
    ]
    return {
        str(row["_id"]): int(row.get("usage_count") or 0)
        for row in _db()[DOCS_COL].aggregate(pipeline, allowDiskUse=True)
        if row.get("_id")
    }


def _normalize_product(prod: dict[str, Any], *, cat_by_id: dict[str, Any], usage: dict[str, int]) -> dict[str, Any]:
    pid = str(prod.get("id") or prod.get("contifico_product_id") or "")
    cat = cat_by_id.get(prod.get("categoria_id")) or {}
    root_name = cat.get("nombre") or "GENERAL"
    if cat.get("padre_id") and cat.get("padre_id") in cat_by_id:
        root_name = cat_by_id[cat["padre_id"]].get("nombre") or root_name
    name = prod.get("nombre") or prod.get("descripcion") or pid
    codigo = prod.get("codigo") or prod.get("legacy_codigo") or pid
    price = prod.get("pvp4") or prod.get("pvp1") or prod.get("precio")
    try:
        last_price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        last_price = None
    return {
        "product_id": pid,
        "contifico_product_id": pid,
        "codigo": codigo,
        "nombre": name,
        "name": name,
        "descripcion": prod.get("descripcion") or "",
        "marca_nombre": prod.get("marca_nombre"),
        "categoria_nombre": prod.get("categoria_nombre") or cat.get("nombre"),
        "categoria_root": prod.get("categoria_root") or root_name,
        "tipo": prod.get("tipo"),
        "tipo_producto": prod.get("tipo_producto"),
        "pvp1": prod.get("pvp1"),
        "pvp4": prod.get("pvp4"),
        "last_price": last_price,
        "cantidad_stock": prod.get("cantidad_stock"),
        "estado": prod.get("estado"),
        "porcentaje_iva": prod.get("porcentaje_iva"),
        "fecha_creacion": prod.get("fecha_creacion"),
        "ralfia_sku": prod.get("ralfia_sku") or f"{_slug_code(root_name, 8)}-{_slug_code(name, 10)}",
        "usage_count": usage.get(pid, 0),
        "source": "contifico_api_local",
        "hydrated_at": _now(),
        "raw": prod,
    }


def _ollama_batch_report(*, done: int, total: int, errors: int, sample_names: list[str]) -> dict[str, Any]:
    """Informe breve con Ollama local (0 tokens cloud)."""
    try:
        from raphiia_openai.local_model_router import run_local_model

        prompt = (
            f"Eres Raul (AG-39), agente de catálogo local PC Doctor. "
            f"Progreso hidratación Contifico→Mongo: {done}/{total} productos, {errors} errores. "
            f"Últimos: {', '.join(sample_names[:5])}. "
            f"Responde en 2 líneas en español: estado y siguiente paso."
        )
        return run_local_model(task_type="summary", prompt=prompt, model=DEFAULT_MODEL, max_tokens=120)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "fallback": f"Hidratados {done}/{total}, errores {errors}"}


def run_local_hydration(
    *,
    max_fetch: int | None = None,
    resume: bool = True,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    ollama_reports: bool = True,
) -> dict[str, Any]:
    """Hidrata fichas Contifico completas en Mongo. Corre en AMD .5, sin LLM cloud."""
    db = _db()
    state = get_hydration_state()
    if state.get("status") == "running":
        return {"ok": False, "error": "hydration_already_running", "progress": state.get("progress")}

    all_ids = sorted(_collect_product_ids_from_local_documents(db))
    already_full = {
        str(doc.get("product_id"))
        for doc in db[LOCAL_PRODUCTS_COL].find(
            {"_kind": {"$ne": "meta"}, "codigo": {"$exists": True, "$ne": ""}},
            {"product_id": 1},
        )
        if doc.get("product_id")
    }
    pending = [pid for pid in all_ids if pid not in already_full]
    if max_fetch is not None:
        pending = pending[: max(0, max_fetch)]

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "agent": "AG-39_raul_local_catalog",
            "referenced_total": len(all_ids),
            "already_hydrated": len(already_full),
            "pending": len(pending),
            "would_fetch": len(pending if max_fetch is None else pending[:max_fetch]),
            "estimated_minutes": round(len(pending) * CONTIFICO_REQUEST_DELAY_MS / 60000, 1),
            "runtime": "local_amd",
        }

    cat_doc = db[CATALOG_COL].find_one({"kind": "categorias"}) or {}
    cat_items = cat_doc.get("items") or []
    cat_by_id = {c.get("id"): c for c in cat_items if c.get("id")}
    usage = _usage_counts()

    existing_catalog = db[CATALOG_COL].find_one({"kind": "productos"}) or {}
    catalog_by_id = {
        str(p.get("id") or p.get("contifico_product_id")): p
        for p in (existing_catalog.get("items") or [])
        if p.get("id") or p.get("contifico_product_id")
    }

    _save_state(status="running", phase="hydrate", progress={"total": len(all_ids), "pending": len(pending), "done": 0})
    fetched = 0
    errors = 0
    req = 0
    sample_names: list[str] = []
    t0 = time.time()

    try:
        for idx, pid in enumerate(pending, start=1):
            prod = _fetch_product(pid, throttle_counter=req)
            req += 1
            if not prod:
                errors += 1
                continue

            cat = cat_by_id.get(prod.get("categoria_id")) or {}
            root_name = cat.get("nombre") or "GENERAL"
            if cat.get("padre_id") and cat.get("padre_id") in cat_by_id:
                root_name = cat_by_id[cat["padre_id"]].get("nombre") or root_name
            enriched = {
                **prod,
                "ralfia_sku": f"{_slug_code(root_name, 8)}-{_slug_code(prod.get('nombre') or 'item', 10)}",
                "legacy_codigo": prod.get("codigo") or prod.get("id"),
                "categoria_nombre": cat.get("nombre"),
                "categoria_root": root_name,
                "contifico_product_id": prod.get("id"),
            }
            catalog_by_id[pid] = enriched
            local_doc = _normalize_product(enriched, cat_by_id=cat_by_id, usage=usage)
            db[LOCAL_PRODUCTS_COL].update_one({"product_id": pid}, {"$set": local_doc}, upsert=True)
            fetched += 1
            sample_names.append(str(local_doc.get("nombre") or pid)[:60])

            if idx % batch_size == 0 or idx == len(pending):
                db[CATALOG_COL].update_one(
                    {"kind": "productos"},
                    {
                        "$set": {
                            "kind": "productos",
                            "items": list(catalog_by_id.values()),
                            "count": len(catalog_by_id),
                            "synced_at": _now(),
                        }
                    },
                    upsert=True,
                )
                progress = {
                    "total": len(all_ids),
                    "pending_start": len(pending),
                    "fetched_this_run": fetched,
                    "errors": errors,
                    "current": idx,
                    "elapsed_sec": round(time.time() - t0, 1),
                }
                _save_state(phase="hydrate", progress=progress)
                if ollama_reports and sample_names:
                    _ollama_batch_report(
                        done=len(already_full) + fetched,
                        total=len(all_ids),
                        errors=errors,
                        sample_names=sample_names[-5:],
                    )
                    sample_names.clear()

            if CONTIFICO_BATCH_PAUSE_EVERY > 0 and req % CONTIFICO_BATCH_PAUSE_EVERY == 0:
                time.sleep(max(0.0, CONTIFICO_BATCH_PAUSE_MS / 1000.0))

        final = {
            "referenced_total": len(all_ids),
            "hydrated_before": len(already_full),
            "fetched_this_run": fetched,
            "errors": errors,
            "hydrated_after": len(already_full) + fetched,
            "elapsed_sec": round(time.time() - t0, 1),
            "catalog_products": len(catalog_by_id),
        }
        _save_state(status="completed", phase="done", progress=final, last_error=None)
        mongo_store.log_sync("raul_local_hydration", **final)
        return {"ok": True, "dry_run": False, "agent": "AG-39_atlas_local_catalog", **final}
    except Exception as exc:
        _save_state(status="error", last_error=str(exc))
        return {"ok": False, "error": str(exc), "fetched": fetched, "errors": errors}
