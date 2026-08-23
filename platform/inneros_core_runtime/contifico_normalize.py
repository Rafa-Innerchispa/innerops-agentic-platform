"""Normalización Contífico → colecciones consultables + queries analíticas + CRM.

Objetivo: poder preguntar desde MCP / WhatsApp / frontend:
- ¿cuántas COT tiene un cliente?
- ¿quién tiene más cotizaciones este año?
- buscar por RUC / nombre / número de documento
- personas Contífico enlazadas al CRM RalfIA
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from raphiia_openai import contifico_bridge, mongo_store

PERSONAS_COL = "contifico_personas"
DOCS_COL = "contifico_documents"
LINES_COL = "contifico_document_lines"
MIRROR_COL = "contifico_mirror"


def _db():
    return mongo_store.get_db()


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _norm_key(v: Any) -> str:
    return re.sub(r"\s+", " ", _norm(v)).lower()


def _digits(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


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
    """Contífico usa DD/MM/YYYY frecuentemente."""
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


def _is_placeholder_ruc(ruc: str) -> bool:
    """RUCs basura típicos de Contífico (ceros / stubs)."""
    d = _digits(ruc)
    if len(d) < 10:
        return True
    if set(d) <= {"0"}:
        return True
    # ej. 0000000002001
    if d.startswith("000000") and d.count("0") >= 10:
        return True
    return False


def _stable_persona_id(raw: dict[str, Any]) -> tuple[str, bool]:
    """ID nativo Contífico, o sintético estable si la API entrega id=null."""
    native = _norm(raw.get("id") or raw.get("persona_id"))
    if native:
        return native, False
    ruc = _digits(raw.get("ruc") or raw.get("cedula") or raw.get("identificacion"))
    nombre = _norm_key(raw.get("razon_social") or raw.get("nombre_comercial") or raw.get("nombre") or "")
    if ruc and not _is_placeholder_ruc(ruc):
        basis = f"ruc:{ruc}"
    elif nombre:
        basis = f"name:{nombre}"
    else:
        # último recurso: hash de campos estables
        blob = "|".join(
            [
                ruc,
                nombre,
                _norm(raw.get("email")),
                _norm(raw.get("telefonos") or raw.get("telefono")),
                _norm(raw.get("tipo")),
            ]
        )
        if not blob.replace("|", ""):
            return "", True
        basis = f"stub:{blob}"
    return "syn_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:22], True


def ensure_contifico_indexes() -> dict[str, Any]:
    db = _db()
    created: list[str] = []
    specs = [
        (PERSONAS_COL, [("persona_id", 1)], {"name": "ux_contifico_persona_id", "unique": True}),
        (PERSONAS_COL, [("ruc", 1)], {"name": "ix_contifico_persona_ruc", "sparse": True}),
        (PERSONAS_COL, [("nombre_norm", 1)], {"name": "ix_contifico_persona_nombre"}),
        (PERSONAS_COL, [("party_id", 1)], {"name": "ix_contifico_persona_party", "sparse": True}),
        (PERSONAS_COL, [("client_id", 1)], {"name": "ix_contifico_persona_client", "sparse": True}),
        (DOCS_COL, [("contifico_id", 1)], {"name": "ux_contifico_doc_id", "unique": True}),
        (DOCS_COL, [("persona_id", 1), ("tipo_documento", 1)], {"name": "ix_contifico_persona_tipo"}),
        (DOCS_COL, [("tipo_documento", 1), ("year", 1)], {"name": "ix_contifico_tipo_year"}),
        (DOCS_COL, [("documento", 1)], {"name": "ix_contifico_documento"}),
        (DOCS_COL, [("ralfia_number", 1)], {"name": "ix_contifico_ralfia_number", "sparse": True}),
        (DOCS_COL, [("total_num", -1)], {"name": "ix_contifico_total_num"}),
        (LINES_COL, [("contifico_id", 1)], {"name": "ix_contifico_line_doc"}),
        (LINES_COL, [("persona_id", 1)], {"name": "ix_contifico_line_persona"}),
    ]
    for col, keys, kwargs in specs:
        try:
            db[col].create_index(keys, **kwargs)
            created.append(f"{col}:{kwargs.get('name')}")
        except Exception:
            continue
    return {"ok": True, "indexes": created}


def _persona_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    persona_id, synthetic = _stable_persona_id(raw)
    nombre = _norm(raw.get("razon_social") or raw.get("nombre_comercial") or raw.get("nombre") or raw.get("display_name"))
    ruc_raw = _digits(raw.get("ruc") or raw.get("cedula") or raw.get("identificacion") or raw.get("tax_id"))
    ruc = "" if _is_placeholder_ruc(ruc_raw) else ruc_raw
    return {
        "persona_id": persona_id,
        "persona_id_native": _norm(raw.get("id") or raw.get("persona_id")) or None,
        "persona_id_synthetic": synthetic,
        "nombre": nombre,
        "nombre_norm": _norm_key(nombre),
        "nombre_comercial": _norm(raw.get("nombre_comercial")),
        "ruc": ruc,
        "ruc_raw": ruc_raw,
        "email": _norm(raw.get("email") or raw.get("correo")),
        "telefono": _norm(raw.get("telefonos") or raw.get("telefono") or raw.get("phone")),
        "es_cliente": bool(raw.get("es_cliente")),
        "es_proveedor": bool(raw.get("es_proveedor")),
        "direccion": _norm(raw.get("direccion") or raw.get("address")),
        "ciudad": _norm(raw.get("ciudad") or raw.get("city")),
        "party_id": _norm(raw.get("party_id")),
        "client_id": _norm(raw.get("client_id")),
        "raw": {
            k: raw.get(k)
            for k in ("id", "razon_social", "ruc", "es_cliente", "es_proveedor", "tipo")
            if k in raw
        },
        "normalized_at": _now(),
        "source": "contifico",
    }


def refresh_personas_mirror(*, max_pages: int = 30) -> dict[str, Any]:
    """Re-fetch personas API → contifico_mirror (incluye filas con id=null)."""
    db = _db()
    try:
        items = contifico_bridge._fetch_all_pages(
            contifico_bridge.READ_ENDPOINTS["personas"],
            size=100,
            max_pages=max_pages,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    db[MIRROR_COL].update_one(
        {"resource": "personas"},
        {
            "$set": {
                "resource": "personas",
                "items": items,
                "count": len(items),
                "synced_at": _now(),
                "source": "api_refresh",
            }
        },
        upsert=True,
    )
    none_id = sum(1 for i in items if isinstance(i, dict) and not _norm(i.get("id")))
    return {"ok": True, "count": len(items), "none_id": none_id}


def materialize_contifico_personas(*, fetch_api: bool = True, max_pages: int = 100) -> dict[str, Any]:
    """Crea/actualiza contifico_personas desde API (preferido) o mirror.

    Filas Contífico con id=null reciben persona_id sintético estable (syn_…).
    """
    db = _db()
    ensure_contifico_indexes()
    items: list[dict[str, Any]] = []
    source = "mirror"
    if fetch_api:
        try:
            refresh = refresh_personas_mirror(max_pages=max_pages)
            if not refresh.get("ok"):
                return {"ok": False, "error": refresh.get("error")}
            items = (db[MIRROR_COL].find_one({"resource": "personas"}) or {}).get("items") or []
            source = "api"
        except Exception as exc:
            return {"ok": False, "error": f"api_fetch_failed: {exc}"}
    if not items:
        mirror = db[MIRROR_COL].find_one({"resource": "personas"}) or {}
        items = mirror.get("items") or []
        source = "mirror"
    upserted = 0
    synthetic = 0
    skipped = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        doc = _persona_from_raw(raw)
        if not doc["persona_id"]:
            skipped += 1
            continue
        if doc.get("persona_id_synthetic"):
            synthetic += 1
        # no pisar party_id/client_id ya enlazados
        existing = db[PERSONAS_COL].find_one({"persona_id": doc["persona_id"]}, {"party_id": 1, "client_id": 1}) or {}
        if existing.get("party_id"):
            doc["party_id"] = existing["party_id"]
        if existing.get("client_id"):
            doc["client_id"] = existing["client_id"]
        db[PERSONAS_COL].update_one(
            {"persona_id": doc["persona_id"]},
            {"$set": doc},
            upsert=True,
        )
        upserted += 1
    return {
        "ok": True,
        "upserted": upserted,
        "synthetic_ids": synthetic,
        "skipped_empty": skipped,
        "total_in_collection": db[PERSONAS_COL].count_documents({}),
        "source": source,
    }


def link_contifico_personas_to_crm(
    *,
    only_clients: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Upsert crm_parties (+ ops_clients si es_cliente) y escribe party_id/client_id en personas."""
    from raphiia_openai.operational import party_store, pcdoctor_store

    db = _db()
    filt: dict[str, Any] = {}
    if only_clients:
        filt["es_cliente"] = True
    cur = db[PERSONAS_COL].find(filt).sort("nombre_norm", 1)
    if limit:
        cur = cur.limit(int(limit))
    linked = 0
    clients_upserted = 0
    skipped = 0
    errors: list[str] = []
    for persona in cur:
        nombre = _norm(persona.get("nombre") or persona.get("nombre_comercial"))
        ruc = _norm(persona.get("ruc"))
        if not nombre and not ruc:
            skipped += 1
            continue
        roles: list[str] = []
        if persona.get("es_cliente"):
            roles.append("client")
        if persona.get("es_proveedor"):
            roles.append("supplier")
        if not roles:
            roles = ["contact_org"]
        try:
            party_res = party_store.upsert_party(
                {
                    "display_name": nombre or ruc or persona.get("persona_id"),
                    "legal_name": nombre,
                    "trade_name": _norm(persona.get("nombre_comercial")),
                    "tax_id": ruc,
                    "email": _norm(persona.get("email")),
                    "phone": _norm(persona.get("telefono")),
                    "city": _norm(persona.get("ciudad")),
                    "address": _norm(persona.get("direccion")),
                    "roles": roles,
                    "status": "active",
                    "notes": f"Contífico persona_id={persona.get('persona_id')}",
                    "identity_links": [
                        {
                            "source_collection": PERSONAS_COL,
                            "source_id": persona.get("persona_id"),
                            "role": "client" if persona.get("es_cliente") else ("supplier" if persona.get("es_proveedor") else "contact_org"),
                        }
                    ],
                    "auto_link": True,
                }
            )
            party_id = party_res.get("party_id")
            client_id = ""
            if persona.get("es_cliente") and (nombre or ruc):
                client_res = pcdoctor_store.upsert_client(
                    {
                        "display_name": nombre or ruc,
                        "legal_name": nombre,
                        "trade_name": _norm(persona.get("nombre_comercial")),
                        "tax_id": ruc,
                        "email": _norm(persona.get("email")),
                        "phone": _norm(persona.get("telefono")),
                        "city": _norm(persona.get("ciudad")),
                        "address": _norm(persona.get("direccion")),
                        "status": "active",
                        "source": "contifico",
                        "notes": f"Import Contífico {persona.get('persona_id')}",
                        "tags": ["contifico"],
                    }
                )
                client_id = client_res.get("client_id") or ""
                if client_id:
                    clients_upserted += 1
                    party_store._upsert_identity_link(party_id, "ops_clients", client_id, "client")
            db[PERSONAS_COL].update_one(
                {"persona_id": persona["persona_id"]},
                {"$set": {"party_id": party_id, "client_id": client_id, "crm_linked_at": _now()}},
            )
            linked += 1
        except Exception as exc:
            errors.append(f"{persona.get('persona_id')}: {exc}"[:160])
            if len(errors) >= 20:
                break
    return {
        "ok": True,
        "linked_parties": linked,
        "clients_upserted": clients_upserted,
        "skipped": skipped,
        "errors": errors,
        "crm_parties": db["crm_parties"].count_documents({}),
        "ops_clients": db["ops_clients"].count_documents({}),
        "personas_with_party": db[PERSONAS_COL].count_documents({"party_id": {"$nin": [None, ""]}}),
    }


def backfill_orphan_document_personas(*, limit: int | None = None, sleep_ms: int = 200) -> dict[str, Any]:
    """Relee detalle Contífico de docs sin persona_id y recupera cliente desde persona{ruc,razon_social}.

    Contífico a menudo deja persona_id=null pero sí manda el objeto persona embebido.
    """
    import time

    from raphiia_openai.contifico_bridge import get_contifico_documento

    db = _db()
    ensure_contifico_indexes()
    filt = {"$or": [{"persona_id": None}, {"persona_id": ""}]}
    cur = db[DOCS_COL].find(filt, {"contifico_id": 1, "documento": 1, "tipo_documento": 1})
    if limit:
        cur = cur.limit(int(limit))
    docs = list(cur)
    fixed = 0
    unresolved = 0
    errors: list[str] = []
    by_client: dict[str, int] = {}
    for doc in docs:
        cid = _norm(doc.get("contifico_id"))
        if not cid:
            unresolved += 1
            continue
        try:
            detail = get_contifico_documento(cid)
            if not detail.get("ok"):
                errors.append(f"{cid}: {detail.get('error') or detail.get('status')}")
                unresolved += 1
                continue
            raw = detail.get("documento") or {}
            persona_obj = raw.get("persona") if isinstance(raw.get("persona"), dict) else {}
            # Prefer native id if Contífico finally has one
            pid = _norm(raw.get("persona_id") or persona_obj.get("id") or persona_obj.get("persona_id"))
            ruc = _digits(persona_obj.get("ruc") or persona_obj.get("cedula"))
            if _is_placeholder_ruc(ruc):
                ruc = ""
            nombre = _norm(
                persona_obj.get("razon_social")
                or persona_obj.get("nombre_comercial")
                or persona_obj.get("nombre")
            )
            if not pid:
                # resolve existing or materialize synthetic from embedded persona
                if ruc:
                    match = resolve_contifico_persona(ruc, limit=1).get("best_match")
                    if match:
                        pid = match.get("persona_id")
                if not pid and nombre:
                    match = resolve_contifico_persona(nombre, limit=1).get("best_match")
                    if match:
                        pid = match.get("persona_id")
                if not pid and (ruc or nombre):
                    # create synthetic persona from embedded stub
                    stub = {
                        "id": None,
                        "ruc": ruc or persona_obj.get("ruc"),
                        "razon_social": nombre,
                        "nombre_comercial": persona_obj.get("nombre_comercial") or nombre,
                        "es_cliente": bool(persona_obj.get("es_cliente", True)),
                        "es_proveedor": bool(persona_obj.get("es_proveedor", False)),
                        "email": persona_obj.get("email"),
                        "telefonos": persona_obj.get("telefonos"),
                        "direccion": persona_obj.get("direccion"),
                    }
                    pdoc = _persona_from_raw(stub)
                    if pdoc.get("persona_id"):
                        db[PERSONAS_COL].update_one(
                            {"persona_id": pdoc["persona_id"]},
                            {"$set": {**pdoc, "source": "contifico_doc_embed"}},
                            upsert=True,
                        )
                        pid = pdoc["persona_id"]
            if not pid:
                unresolved += 1
                continue
            db[DOCS_COL].update_one(
                {"contifico_id": cid},
                {
                    "$set": {
                        "persona_id": pid,
                        "persona_nombre": nombre,
                        "persona_ruc": ruc,
                        "persona_backfilled_at": _now(),
                        "persona_backfill_source": "contifico_api_detail",
                    }
                },
            )
            fixed += 1
            key = nombre or ruc or pid
            by_client[key] = by_client.get(key, 0) + 1
        except Exception as exc:
            errors.append(f"{cid}: {exc}"[:160])
            unresolved += 1
        if sleep_ms:
            time.sleep(max(0, sleep_ms) / 1000.0)
    remaining = db[DOCS_COL].count_documents(filt)
    return {
        "ok": True,
        "scanned": len(docs),
        "fixed": fixed,
        "unresolved": unresolved,
        "remaining_orphans": remaining,
        "top_clients_recovered": sorted(by_client.items(), key=lambda x: -x[1])[:15],
        "errors": errors[:20],
    }


def normalize_contifico_documents(*, limit: int | None = None, materialize_lines: bool = False) -> dict[str, Any]:
    """Añade campos consultables: total_num, year, fecha_iso, line counts.

    materialize_lines=False por defecto (rápido). Activar para poblar contifico_document_lines.
    """
    from pymongo import UpdateOne

    db = _db()
    ensure_contifico_indexes()
    cur = db[DOCS_COL].find({})
    if limit:
        cur = cur.limit(int(limit))
    updated = 0
    lines_upserted = 0
    ops: list[Any] = []
    line_ops: list[Any] = []
    for doc in cur:
        fecha = _parse_fecha(doc.get("fecha_emision"))
        total_num = _safe_float(doc.get("total"))
        subtotal_num = _safe_float(doc.get("subtotal"))
        iva_num = _safe_float(doc.get("iva"))
        lineas = doc.get("lineas") or []
        cobros = doc.get("cobros") or []
        patch = {
            "total_num": total_num,
            "subtotal_num": subtotal_num,
            "iva_num": iva_num,
            "fecha_iso": fecha["fecha_iso"],
            "year": fecha["year"],
            "month": fecha["month"],
            "lineas_count": len(lineas) if isinstance(lineas, list) else 0,
            "cobros_count": len(cobros) if isinstance(cobros, list) else 0,
            "normalized_at": _now(),
        }
        if not doc.get("ralfia_number") and doc.get("tipo_documento") and doc.get("documento"):
            patch["ralfia_number"] = f"{doc.get('tipo_documento')}-{doc.get('documento')}"
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": patch}))
        updated += 1
        if materialize_lines and isinstance(lineas, list):
            for idx, line in enumerate(lineas):
                if not isinstance(line, dict):
                    continue
                line_id = f"{doc.get('contifico_id')}:{idx}"
                line_ops.append(
                    UpdateOne(
                        {"line_id": line_id},
                        {
                            "$set": {
                                "line_id": line_id,
                                "contifico_id": doc.get("contifico_id"),
                                "persona_id": doc.get("persona_id"),
                                "tipo_documento": doc.get("tipo_documento"),
                                "year": fecha["year"],
                                "producto_id": line.get("producto_id"),
                                "descripcion": _norm(line.get("descripcion") or line.get("concepto")),
                                "cantidad": _safe_float(line.get("cantidad"), 1.0),
                                "precio": _safe_float(line.get("precio") or line.get("precio_unitario")),
                                "total": _safe_float(line.get("total") or line.get("base")),
                                "normalized_at": _now(),
                            }
                        },
                        upsert=True,
                    )
                )
                lines_upserted += 1
        if len(ops) >= 500:
            db[DOCS_COL].bulk_write(ops, ordered=False)
            ops = []
        if len(line_ops) >= 500:
            db[LINES_COL].bulk_write(line_ops, ordered=False)
            line_ops = []
    if ops:
        db[DOCS_COL].bulk_write(ops, ordered=False)
    if line_ops:
        db[LINES_COL].bulk_write(line_ops, ordered=False)
    return {"ok": True, "documents_updated": updated, "lines_upserted": lines_upserted, "materialize_lines": materialize_lines}


def normalize_contifico_all(
    *,
    fetch_personas_api: bool = True,
    link_crm: bool = True,
    normalize_ledger: bool = True,
) -> dict[str, Any]:
    """Normaliza personas+docs+ledger y opcionalmente enlaza CRM."""
    personas = materialize_contifico_personas(fetch_api=fetch_personas_api)
    docs = normalize_contifico_documents()
    ledger = None
    if normalize_ledger:
        from raphiia_openai import contifico_ledger

        ledger = contifico_ledger.normalize_all_ledger()
    crm = None
    if link_crm:
        crm = link_contifico_personas_to_crm()
    inv = contifico_inventory_summary()
    return {
        "ok": True,
        "personas": personas,
        "documents": docs,
        "ledger": ledger,
        "crm": crm,
        "inventory": inv,
    }


def resolve_contifico_persona(query: str, limit: int = 10) -> dict[str, Any]:
    db = _db()
    q = _norm(query)
    if not q:
        return {"ok": False, "error": "query_required", "matches": []}

    # Exact persona_id first — never treat Contífico IDs as RUC fragments.
    exact = db[PERSONAS_COL].find_one({"persona_id": q})
    if exact:
        exact["_id"] = str(exact["_id"])
        exact.pop("raw", None)
        return {"ok": True, "count": 1, "matches": [exact], "best_match": exact}

    digits = _digits(q)
    or_filters: list[dict[str, Any]] = [
        {"nombre_norm": {"$regex": re.escape(_norm_key(q)), "$options": "i"}},
        {"nombre": {"$regex": re.escape(q), "$options": "i"}},
        {"nombre_comercial": {"$regex": re.escape(q), "$options": "i"}},
    ]
    # Only match RUC when the query looks like an ID tax number (≥8 digits).
    # Short digit fragments from Contífico IDs (e.g. "9" in BXdL9…) match almost everyone.
    if len(digits) >= 8:
        or_filters.append({"ruc": digits})
        or_filters.append({"ruc": {"$regex": f"^{re.escape(digits)}"}})

    lim = max(1, min(limit, 50))
    matches = list(db[PERSONAS_COL].find({"$or": or_filters}).limit(lim * 3))

    def _score(m: dict[str, Any]) -> tuple:
        nn = _norm_key(m.get("nombre"))
        nc = _norm_key(m.get("nombre_comercial"))
        qn = _norm_key(q)
        exact_name = 0 if nn == qn or nc == qn else 1
        starts = 0 if nn.startswith(qn) or nc.startswith(qn) else 1
        ruc_hit = 0 if digits and m.get("ruc") == digits else 1
        return (ruc_hit, exact_name, starts, nn)

    matches.sort(key=_score)
    matches = matches[:lim]
    for m in matches:
        m["_id"] = str(m["_id"])
        m.pop("raw", None)
    return {"ok": True, "count": len(matches), "matches": matches, "best_match": matches[0] if matches else None}


def search_contifico_documents(
    *,
    query: str | None = None,
    tipo_documento: str | None = None,
    persona_id: str | None = None,
    year: int | None = None,
    documento: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    db = _db()
    filt: dict[str, Any] = {}
    if tipo_documento:
        filt["tipo_documento"] = tipo_documento.strip().upper()
    if persona_id:
        filt["persona_id"] = persona_id
    if year:
        filt["year"] = int(year)
    if documento:
        filt["documento"] = {"$regex": re.escape(documento), "$options": "i"}
    if query:
        q = _norm(query)
        # try persona resolve first
        persona = resolve_contifico_persona(q, limit=1).get("best_match")
        if persona and not persona_id:
            filt["persona_id"] = persona["persona_id"]
        else:
            filt["$or"] = [
                {"documento": {"$regex": re.escape(q), "$options": "i"}},
                {"ralfia_number": {"$regex": re.escape(q), "$options": "i"}},
                {"descripcion": {"$regex": re.escape(q), "$options": "i"}},
                {"contifico_id": q},
            ]
    cur = db[DOCS_COL].find(filt).sort([("fecha_iso", -1), ("total_num", -1)]).limit(max(1, min(limit, 200)))
    items = []
    for d in cur:
        d["_id"] = str(d["_id"])
        items.append(d)
    return {"ok": True, "count": len(items), "filter": filt, "documents": items}


def query_contifico_stats(
    *,
    tipo_documento: str | None = "COT",
    year: int | None = None,
    persona_query: str | None = None,
    persona_id: str | None = None,
    top: int = 10,
) -> dict[str, Any]:
    """Estadísticas: conteos y montos por cliente / tipo / año."""
    db = _db()
    match: dict[str, Any] = {}
    if tipo_documento:
        match["tipo_documento"] = tipo_documento.strip().upper()
    if year:
        match["year"] = int(year)
    persona = None
    if persona_id:
        match["persona_id"] = _norm(persona_id)
        persona = db[PERSONAS_COL].find_one({"persona_id": match["persona_id"]})
        if persona:
            persona = {**persona, "_id": str(persona["_id"])}
            persona.pop("raw", None)
    elif persona_query:
        persona = resolve_contifico_persona(persona_query, limit=1).get("best_match")
        if persona:
            match["persona_id"] = persona["persona_id"]
        else:
            return {
                "ok": False,
                "error": "persona_not_found",
                "query": persona_query,
                "hint": "Normaliza personas con normalize_contifico_all / materialize_contifico_personas",
            }

    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {
            "$group": {
                "_id": "$persona_id",
                "count": {"$sum": 1},
                "total_amount": {"$sum": {"$ifNull": ["$total_num", 0]}},
                "avg_amount": {"$avg": {"$ifNull": ["$total_num", 0]}},
            }
        },
        {"$sort": {"count": -1, "total_amount": -1}},
        {"$limit": max(1, min(int(top), 100))},
    ]
    rows = list(db[DOCS_COL].aggregate(pipeline))
    # enrich names
    enriched = []
    for row in rows:
        pid = row.get("_id")
        pdoc = db[PERSONAS_COL].find_one({"persona_id": pid}, {"nombre": 1, "ruc": 1, "nombre_comercial": 1}) or {}
        enriched.append(
            {
                "persona_id": pid,
                "nombre": pdoc.get("nombre") or pid or "(sin persona)",
                "ruc": pdoc.get("ruc"),
                "count": row.get("count"),
                "total_amount": round(float(row.get("total_amount") or 0), 2),
                "avg_amount": round(float(row.get("avg_amount") or 0), 2),
            }
        )

    totals_pipe = [
        {"$match": match} if match else {"$match": {}},
        {
            "$group": {
                "_id": None,
                "documents": {"$sum": 1},
                "total_amount": {"$sum": {"$ifNull": ["$total_num", 0]}},
            }
        },
    ]
    totals = list(db[DOCS_COL].aggregate(totals_pipe))
    summary = totals[0] if totals else {"documents": 0, "total_amount": 0}
    return {
        "ok": True,
        "tipo_documento": tipo_documento,
        "year": year,
        "persona": persona,
        "documents": summary.get("documents", 0),
        "total_amount": round(float(summary.get("total_amount") or 0), 2),
        "top_clients": enriched,
    }


def get_contifico_client_summary(query: str, year: int | None = None) -> dict[str, Any]:
    """Resumen de un cliente: COT/FAC counts y montos."""
    persona = resolve_contifico_persona(query, limit=1).get("best_match")
    if not persona:
        return {"ok": False, "error": "persona_not_found", "query": query}
    pid = persona["persona_id"]
    by_type = []
    for tipo in ("COT", "FAC", "NCT", "DAC", "DNA", "PRE"):
        st = query_contifico_stats(tipo_documento=tipo, year=year, persona_id=pid, top=1)
        by_type.append(
            {
                "tipo_documento": tipo,
                "documents": st.get("documents", 0),
                "total_amount": st.get("total_amount", 0),
            }
        )
    recent = search_contifico_documents(persona_id=pid, year=year, limit=10)
    return {
        "ok": True,
        "persona": persona,
        "year": year,
        "by_type": by_type,
        "recent_documents": recent.get("documents", []),
    }


def contifico_inventory_summary() -> dict[str, Any]:
    db = _db()
    docs = db[DOCS_COL]
    total = docs.count_documents({})
    tipos = list(docs.aggregate([{"$group": {"_id": "$tipo_documento", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]))
    personas_n = db[PERSONAS_COL].count_documents({})
    orphan = docs.count_documents({"$or": [{"persona_id": None}, {"persona_id": ""}]})
    normalized = docs.count_documents({"normalized_at": {"$exists": True}})
    with_year = docs.count_documents({"year": {"$type": "int"}})
    synthetic = db[PERSONAS_COL].count_documents({"persona_id_synthetic": True})
    with_party = db[PERSONAS_COL].count_documents({"party_id": {"$nin": [None, ""]}})
    with_client = db[PERSONAS_COL].count_documents({"client_id": {"$nin": [None, ""]}})
    from raphiia_openai import contifico_ledger

    ledger = contifico_ledger.ledger_inventory_summary()
    return {
        "ok": True,
        "documents": total,
        "personas_normalized": personas_n,
        "personas_synthetic_id": synthetic,
        "personas_with_party_id": with_party,
        "personas_with_client_id": with_client,
        "documents_normalized": normalized,
        "documents_with_year": with_year,
        "orphan_persona": orphan,
        "by_type": {t["_id"]: t["n"] for t in tipos},
        "lines": db[LINES_COL].count_documents({}),
        "ledger": ledger,
        "crm_parties": db["crm_parties"].count_documents({}),
        "ops_clients": db["ops_clients"].count_documents({}),
    }
