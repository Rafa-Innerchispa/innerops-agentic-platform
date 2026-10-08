"""Import contable Contifico por entidad (PC Doctor + Domotika) → Mongo + ledger."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from inneros_core_runtime import contifico_entities as entities
from inneros_core_runtime.contifico_bridge import (
    CONTIFICO_API_BASE,
    DEFAULT_TIMEOUT,
    DOCS_COL,
    READ_ENDPOINTS,
    _parse_documento_seq,
    _ralfia_number,
)
from inneros_core_runtime.operational import accounting_ledger as ledger
from raphiia_openai import mongo_store
from raphiia_openai.settings import CONTIFICO_REQUEST_DELAY_MS

MIRROR_COL = "contifico_mirror"
PERSONAS_COL = "contifico_personas"
SYNC_STATE_COL = "contifico_sync_state"
ACCT_COL = "contifico_accounts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _throttle() -> None:
    delay = max(0.0, CONTIFICO_REQUEST_DELAY_MS / 1000.0)
    if delay:
        time.sleep(delay)


def entity_stamp(ent: entities.ContificoEntity) -> dict[str, Any]:
    return {
        "contifico_entity_id": ent.entity_id,
        "issuer_ruc": ent.ruc,
        "issuer_legal_name": ent.legal_name,
        "issuer_trade_name": ent.trade_name,
    }


def _headers(ent: entities.ContificoEntity) -> dict[str, str]:
    key = entities.entity_api_key(ent)
    if not key:
        raise ValueError(f"{ent.api_key_env} not configured")
    return {"Authorization": key, "Accept": "application/json"}


def _get(ent: entities.ContificoEntity, path: str, *, page: int = 1, size: int = 50) -> dict[str, Any]:
    _throttle()
    params = {"result_page": page, "result_size": size}
    url = f"{CONTIFICO_API_BASE.rstrip('/')}{path}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(ent), params=params)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": (resp.text or "")[:400]}
    if not resp.is_success:
        return {"ok": False, "status": resp.status_code, "error": data}
    items = data if isinstance(data, list) else (data.get("results") if isinstance(data, dict) else [])
    if not isinstance(items, list):
        items = []
    return {"ok": True, "items": items, "count": len(items)}


def _fetch_pages(ent: entities.ContificoEntity, path: str, *, size: int = 50, max_pages: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = _get(ent, path, page=page, size=size)
        if not batch.get("ok"):
            break
        rows = batch.get("items") or []
        if not rows:
            break
        out.extend(rows)
        if len(rows) < size:
            break
    return out


def backfill_legacy_pcdoctor_tags() -> dict[str, Any]:
    """Documentos/personas sin entity_id → pcdoctor (histórico PC Doctor)."""
    ent = entities.PCDOCTOR
    stamp = entity_stamp(ent)
    db = mongo_store.get_db()
    docs = db[DOCS_COL].update_many(
        {"contifico_entity_id": {"$exists": False}},
        {"$set": stamp},
    )
    personas = db[PERSONAS_COL].update_many(
        {"contifico_entity_id": {"$exists": False}},
        {"$set": stamp},
    )
    led = db[ledger.LEDGER_COL].update_many(
        {"source": "contifico", "contifico_entity_id": {"$exists": False}},
        {"$set": stamp},
    )
    return {
        "ok": True,
        "contifico_documents": docs.modified_count,
        "contifico_personas": personas.modified_count,
        "ralfia_ledger_documents": led.modified_count,
    }


def import_entity_mirror_lists(
    entity_id: str,
    *,
    resources: list[str] | None = None,
    max_pages: int = 30,
) -> dict[str, Any]:
    ent = entities.resolve_entity(entity_id)
    keys = resources or ["personas", "cuentas_contables", "banco_cuentas", "banco_movimientos", "transacciones", "centros_costo"]
    db = mongo_store.get_db()
    summary: dict[str, int] = {}
    for key in keys:
        path = READ_ENDPOINTS.get(key)
        if not path:
            continue
        items = _fetch_pages(ent, path, size=100, max_pages=max_pages)
        db[MIRROR_COL].update_one(
            {"resource": key, "contifico_entity_id": ent.entity_id},
            {
                "$set": {
                    "resource": key,
                    **entity_stamp(ent),
                    "items": items,
                    "count": len(items),
                    "synced_at": _now(),
                }
            },
            upsert=True,
        )
        summary[key] = len(items)
    return {"ok": True, "entity_id": ent.entity_id, "resources": summary}


def _persona_doc(raw: dict[str, Any], ent: entities.ContificoEntity) -> dict[str, Any]:
    pid = str(raw.get("id") or "").strip()
    nombre = str(raw.get("razon_social") or raw.get("nombre_comercial") or "").strip()
    return {
        **entity_stamp(ent),
        "persona_id": pid,
        "nombre": nombre,
        "nombre_comercial": raw.get("nombre_comercial"),
        "cedula": raw.get("cedula"),
        "ruc": raw.get("ruc"),
        "email": raw.get("email"),
        "es_cliente": raw.get("es_cliente"),
        "es_proveedor": raw.get("es_proveedor"),
        "synced_at": _now(),
    }


def import_entity_personas(entity_id: str, *, max_pages: int = 40) -> dict[str, Any]:
    ent = entities.resolve_entity(entity_id)
    items = _fetch_pages(ent, READ_ENDPOINTS["personas"], size=50, max_pages=max_pages)
    db = mongo_store.get_db()
    upserted = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        doc = _persona_doc(raw, ent)
        if not doc["persona_id"]:
            continue
        db[PERSONAS_COL].update_one(
            {"contifico_entity_id": ent.entity_id, "persona_id": doc["persona_id"]},
            {"$set": doc},
            upsert=True,
        )
        upserted += 1
    return {"ok": True, "entity_id": ent.entity_id, "upserted": upserted, "fetched": len(items)}


def import_entity_documents(
    entity_id: str,
    *,
    max_docs: int = 120,
    list_pages: int = 8,
) -> dict[str, Any]:
    ent = entities.resolve_entity(entity_id)
    stubs = _fetch_pages(ent, READ_ENDPOINTS["documentos"], size=50, max_pages=max(1, list_pages))
    db = mongo_store.get_db()
    now = _now()
    imported = created = updated = 0
    for stub in stubs[:max_docs]:
        did = stub.get("id")
        if not did:
            continue
        filt = {"contifico_entity_id": ent.entity_id, "contifico_id": str(did)}
        existed = db[DOCS_COL].find_one(filt, {"_id": 1})
        _throttle()
        url = f"{CONTIFICO_API_BASE.rstrip('/')}/documento/{did}/"
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(url, headers=_headers(ent))
        if not resp.is_success:
            continue
        detail = resp.json()
        tipo = detail.get("tipo_documento") or stub.get("tipo_documento")
        numero = detail.get("documento") or stub.get("documento")
        row = {
            **entity_stamp(ent),
            "contifico_id": str(did),
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
        db[DOCS_COL].update_one(filt, {"$set": row}, upsert=True)
        imported += 1
        if existed:
            updated += 1
        else:
            created += 1
    mongo_store.get_db()[SYNC_STATE_COL].update_one(
        {"kind": "entity_accounting", "entity_id": ent.entity_id},
        {
            "$set": {
                "kind": "entity_accounting",
                "entity_id": ent.entity_id,
                "last_documents_sync": now,
                "progress": {"imported": imported, "created": created, "updated": updated},
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return {
        "ok": True,
        "entity_id": ent.entity_id,
        "imported": imported,
        "created": created,
        "updated": updated,
        "stubs_seen": min(len(stubs), max_docs),
    }


def import_entity_chart(entity_id: str, *, max_pages: int = 20) -> dict[str, Any]:
    """Plan de cuentas en mirror por entidad (evita colisión índice legacy account_id)."""
    ent = entities.resolve_entity(entity_id)
    res = import_entity_mirror_lists(ent.entity_id, resources=["cuentas_contables"], max_pages=max_pages)
    count = (res.get("resources") or {}).get("cuentas_contables", 0)
    return {"ok": True, "entity_id": ent.entity_id, "accounts_in_mirror": count, "collection": MIRROR_COL}


def sync_entity_to_ledger(entity_id: str, *, limit: int = 5000) -> dict[str, Any]:
    ent = entities.resolve_entity(entity_id)
    db = mongo_store.get_db()
    rows = list(
        db[DOCS_COL]
        .find({"contifico_entity_id": ent.entity_id})
        .sort("fecha_emision", -1)
        .limit(max(1, min(limit, 20000)))
    )
    synced = 0
    for row in rows:
        doc = ledger.ledger_from_contifico(row)
        ledger._upsert_ledger(doc)
        synced += 1
    return {
        "ok": True,
        "entity_id": ent.entity_id,
        "synced": synced,
        "ledger_total_entity": db[ledger.LEDGER_COL].count_documents({"contifico_entity_id": ent.entity_id}),
    }



def validate_entity_api(entity_id: str) -> dict[str, Any]:
    """Confirma que la API key pertenece al RUC de la entidad (v2 /pos/)."""
    from inneros_core_runtime import contifico_billing as bill

    ent = entities.resolve_entity(entity_id)
    if not entities.entity_api_key(ent):
        return {"ok": False, "entity_id": ent.entity_id, "error": f"{ent.api_key_env} missing"}
    pos = bill.list_pos_emission_points(entity_id=ent.entity_id)
    ruc = (pos.get("points") or [{}])[0].get("ruc") if pos.get("ok") else None
    match = ruc == ent.ruc if ruc else False
    return {
        "ok": bool(pos.get("ok")) and match,
        "entity_id": ent.entity_id,
        "expected_ruc": ent.ruc,
        "connected_company_ruc": ruc,
        "ruc_matches_registry": match,
        "api_key_fingerprint": bill.connection_status(entity_id=ent.entity_id).get("api_key_fingerprint"),
    }


def sync_all_entities_accounting(
    *,
    entity_ids: list[str] | None = None,
    max_docs_per_entity: int = 100,
    include_personas: bool = True,
    include_chart: bool = True,
    push_ledger: bool = True,
) -> dict[str, Any]:
    ids = entity_ids or [e.entity_id for e in entities.list_entities()]
    backfill = backfill_legacy_pcdoctor_tags()
    results: list[dict[str, Any]] = []
    for eid in ids:
        ent = entities.resolve_entity(eid)
        if entities.entity_is_standby(ent):
            results.append({"entity_id": ent.entity_id, "ok": True, "skipped": True, "standby": True, "note": "sin API; migración manual"})
            continue
        if not entities.entity_api_key(ent):
            results.append({"entity_id": ent.entity_id, "ok": False, "skipped": True, "error": f"{ent.api_key_env} missing"})
            continue
        api_check = validate_entity_api(ent.entity_id)
        if not api_check.get("ok"):
            results.append(
                {
                    "entity_id": ent.entity_id,
                    "ok": False,
                    "skipped": True,
                    "error": "api_key_ruc_mismatch",
                    "validation": api_check,
                    "hint": "Genera API key en el portal Contifico de esa empresa (RUC distinto).",
                }
            )
            continue
        block: dict[str, Any] = {"entity_id": ent.entity_id, "ok": True, "validation": api_check}
        block["mirror"] = import_entity_mirror_lists(ent.entity_id, max_pages=15)
        if include_personas:
            block["personas"] = import_entity_personas(ent.entity_id, max_pages=25)
        block["documents"] = import_entity_documents(ent.entity_id, max_docs=max_docs_per_entity)
        if include_chart:
            block["chart"] = import_entity_chart(ent.entity_id, max_pages=10)
        if push_ledger:
            block["ledger"] = sync_entity_to_ledger(ent.entity_id)
        results.append(block)
    return {"ok": True, "backfill": backfill, "entities": results}


def accounting_entities_status() -> dict[str, Any]:
    db = mongo_store.get_db()
    from collections import Counter

    out: list[dict[str, Any]] = []
    for ent in entities.list_entities():
        key_ok = bool(entities.entity_api_key(ent))
        doc_filt = {"contifico_entity_id": ent.entity_id}
        legacy = {"contifico_entity_id": {"$exists": False}} if ent.entity_id == "pcdoctor" else {}
        doc_count = db[DOCS_COL].count_documents(doc_filt)
        if legacy:
            doc_count += db[DOCS_COL].count_documents(legacy)
        tipos = Counter(
            d.get("tipo_documento")
            for d in db[DOCS_COL].find({**doc_filt}, {"tipo_documento": 1})
        )
        out.append(
            {
                **ent.public_dict(),
                "standby": entities.entity_is_standby(ent),
                "api_configured": key_ok and not entities.entity_is_standby(ent),
                "documents_in_mongo": doc_count,
                "documents_by_type": dict(tipos),
                "personas_in_mongo": db[PERSONAS_COL].count_documents(doc_filt),
                "ledger_rows": db[ledger.LEDGER_COL].count_documents({"contifico_entity_id": ent.entity_id}),
                "accounts_in_mongo": db[ACCT_COL].count_documents(doc_filt),
            }
        )
    return {"ok": True, "entities": out, "registry": entities.entities_registry_public()}
