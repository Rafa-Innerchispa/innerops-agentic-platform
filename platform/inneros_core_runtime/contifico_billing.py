"""Contífico billing API — governed read/write for MCP (multi-entity)."""

from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from inneros_core_runtime import contifico_entities as entities
from raphiia_openai import mongo_store
from raphiia_openai.settings import (
    CONTIFICO_API_BASE,
    CONTIFICO_API_KEY,
    CONTIFICO_COMPANY_TOKEN,
    CONTIFICO_REQUEST_DELAY_MS,
)

DEFAULT_TIMEOUT = 60.0
CONTIFICO_API_V2_BASE = os.getenv(
    "CONTIFICO_API_V2_BASE", "https://api.contifico.com/sistema/api/v2"
)
IDEMPOTENCY_COL = "contifico_idempotency"
AUDIT_COL = "contifico_mutation_audit"
_SECRET_RE = re.compile(r"(authorization|api[_-]?key|token)\s*[:=]\s*\S+", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_ec() -> str:
    return datetime.now(ZoneInfo("America/Guayaquil")).strftime("%d/%m/%Y")


def _throttle() -> None:
    delay = max(0.0, CONTIFICO_REQUEST_DELAY_MS / 1000.0)
    if delay:
        time.sleep(delay)


def _entity(entity_id: str | None = None) -> entities.ContificoEntity:
    return entities.resolve_entity(entity_id)


def _api_key_for(entity: entities.ContificoEntity) -> str:
    return entities.entity_api_key(entity)


def _sanitize_text(text: str) -> str:
    if not text:
        return text
    red = _SECRET_RE.sub(r"\1=***", text)
    for ent in entities.list_entities():
        key = _api_key_for(ent)
        if key:
            red = red.replace(key, "***")
    return red


def _headers(entity: entities.ContificoEntity) -> dict[str, str]:
    key = _api_key_for(entity)
    if not key:
        raise ValueError(f"{entity.api_key_env} not configured (entity={entity.entity_id})")
    return {"Authorization": key, "Accept": "application/json", "Content-Type": "application/json"}


def _pos_token(entity_id: str | None = None) -> str:
    ent = _entity(entity_id)
    explicit = entities.entity_pos_token(ent)
    if explicit:
        return explicit
    key = _api_key_for(ent)
    if not key:
        return ""
    url = f"{CONTIFICO_API_V2_BASE.rstrip('/')}/pos/"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers={"Authorization": key, "Accept": "application/json"})
    if not resp.is_success:
        return ""
    try:
        data = resp.json()
    except Exception:
        return ""
    for row in data.get("results") or []:
        tok = str(row.get("token") or "").strip()
        if tok:
            return tok
    return ""


def list_pos_emission_points(*, entity_id: str | None = None) -> dict[str, Any]:
    ent = _entity(entity_id)
    key = _api_key_for(ent)
    if not key:
        return {"ok": False, "entity_id": ent.entity_id, "error": f"{ent.api_key_env} not configured"}
    url = f"{CONTIFICO_API_V2_BASE.rstrip('/')}/pos/"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers={"Authorization": key, "Accept": "application/json"})
    try:
        data = resp.json()
    except Exception:
        data = {"raw": _sanitize_text((resp.text or "")[:500])}
    if not resp.is_success:
        return {"ok": False, "entity_id": ent.entity_id, "status": resp.status_code, "error": data}
    points = []
    for row in data.get("results") or []:
        points.append(
            {
                "establecimiento": row.get("establecimiento"),
                "punto_emision": row.get("punto_emision"),
                "token_fingerprint": hashlib.sha256(str(row.get("token") or "").encode()).hexdigest()[:12],
                "ruc": row.get("ruc"),
                "razon_social": row.get("razon_social"),
                "tiene_firma": row.get("tiene_firma"),
            }
        )
    return {"ok": True, "entity_id": ent.entity_id, "expected_ruc": ent.ruc, "count": len(points), "points": points}


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    api_base: str | None = None,
    pos_token: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    _throttle()
    ent = _entity(entity_id)
    base = (api_base or CONTIFICO_API_BASE).rstrip("/")
    url = f"{base}{path}"
    headers = _headers(ent)
    if pos_token:
        headers["Pos"] = pos_token
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.request(method.upper(), url, headers=headers, params=params, json=json_body)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": _sanitize_text((resp.text or "")[:800])}
    if not resp.is_success:
        return {
            "ok": False,
            "status": resp.status_code,
            "error": data,
            "path": path,
        }
    return {"ok": True, "status": resp.status_code, "data": data}


def _connection_status_one(entity_id: str) -> dict[str, Any]:
    ent = _entity(entity_id)
    key = _api_key_for(ent)
    base = {
        "entity_id": ent.entity_id,
        "label": ent.label,
        "expected_ruc": ent.ruc,
        "trade_name": ent.trade_name,
        "api_key_env": ent.api_key_env,
    }
    if not key:
        return {
            **base,
            "ok": False,
            "configured": False,
            "connected": False,
            "message": f"{ent.api_key_env} missing",
        }
    probe = _request(
        "GET",
        "/persona/",
        params={"result_page": 1, "result_size": 1},
        entity_id=ent.entity_id,
    )
    doc_probe = _request(
        "GET",
        "/documento/",
        params={"result_page": 1, "result_size": 3},
        entity_id=ent.entity_id,
    )
    pos_info = list_pos_emission_points(entity_id=ent.entity_id)
    doc_types: set[str] = set()
    sample_pos = None
    if doc_probe.get("ok"):
        items = doc_probe.get("data")
        if isinstance(items, list):
            for row in items:
                td = str(row.get("tipo_documento") or "").upper()
                if td:
                    doc_types.add(td)
                if sample_pos is None and row.get("pos"):
                    sample_pos = row.get("pos")
    connected_ruc = (pos_info.get("points") or [{}])[0].get("ruc") if pos_info.get("ok") and pos_info.get("points") else None
    ruc_match = connected_ruc == ent.ruc if connected_ruc else None
    return {
        **base,
        "ok": bool(probe.get("ok")),
        "configured": True,
        "connected": bool(probe.get("ok")),
        "api_key_fingerprint": hashlib.sha256(key.encode()).hexdigest()[:12],
        "document_types_seen": sorted(doc_types),
        "sample_pos": sample_pos,
        "pos_emission_points": pos_info.get("points") if pos_info.get("ok") else [],
        "connected_company_ruc": connected_ruc,
        "ruc_matches_registry": ruc_match,
    }


def connection_status(entity_id: str | None = None) -> dict[str, Any]:
    """Status for one entity (entity_id set) or all registered entities (default)."""
    registry = entities.entities_registry_public()
    shared = {
        "api_base": CONTIFICO_API_BASE,
        "company_token_set": bool((CONTIFICO_COMPANY_TOKEN or "").strip()),
        "non_fiscal_draft_type": "COT",
        "fiscal_invoice_type": "FAC",
        "sandbox_detected": False,
        "note": "Use entity_id pcdoctor | domotika | innerchispa. COT borrador; FAC requiere owner approval.",
        "write_api_note": "POST /documento/ requiere Pos token v2 por entidad; habilitar escritura API en Contifico.",
        "module": "contifico_billing.v2_multi_entity",
        "registry": registry,
    }
    if entity_id is not None and str(entity_id).strip():
        one = _connection_status_one(str(entity_id))
        return {**shared, **one}
    statuses = [_connection_status_one(e.entity_id) for e in entities.list_entities()]
    primary = next((s for s in statuses if s.get("entity_id") == entities.DEFAULT_ENTITY_ID), statuses[0])
    return {
        **shared,
        "ok": any(s.get("connected") for s in statuses),
        "configured": any(s.get("configured") for s in statuses),
        "connected": any(s.get("connected") for s in statuses),
        "entities": statuses,
        "entity_id": primary.get("entity_id"),
        "connected_company_ruc": primary.get("connected_company_ruc"),
        "pos_emission_points": primary.get("pos_emission_points"),
        "api_key_fingerprint": primary.get("api_key_fingerprint"),
    }


def _persona_matches(row: dict[str, Any], query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    fields = [
        str(row.get("cedula") or ""),
        str(row.get("ruc") or ""),
        str(row.get("razon_social") or ""),
        str(row.get("email") or ""),
        str(row.get("nombre_comercial") or ""),
    ]
    blob = " ".join(fields).lower()
    if q.isdigit() and (q in blob.replace(" ", "")):
        return True
    return q in blob


def customer_search(
    *,
    entity_id: str | None = None,
    query: str = "",
    cedula: str | None = None,
    ruc: str | None = None,
    email: str | None = None,
    max_pages: int = 40,
    page_size: int = 50,
) -> dict[str, Any]:
    needle = (cedula or ruc or email or query or "").strip()
    if not needle:
        return {"ok": False, "error": "query_required"}
    matches: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        out = _request("GET", "/persona/", params={"result_page": page, "result_size": page_size}, entity_id=entity_id)
        if not out.get("ok"):
            return out
        batch = out.get("data")
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            if _persona_matches(row, needle) or _persona_matches(row, query):
                matches.append(
                    {
                        "persona_id": row.get("id"),
                        "razon_social": row.get("razon_social"),
                        "cedula": row.get("cedula"),
                        "ruc": row.get("ruc"),
                        "email": row.get("email"),
                        "nombre_comercial": row.get("nombre_comercial"),
                        "es_cliente": row.get("es_cliente"),
                    }
                )
        if len(batch) < page_size:
            break
    return {"ok": True, "entity_id": _entity(entity_id).entity_id, "query": needle, "count": len(matches), "customers": matches}


def customer_get(persona_id: str, *, entity_id: str | None = None) -> dict[str, Any]:
    pid = (persona_id or "").strip()
    if not pid:
        return {"ok": False, "error": "persona_id_required"}
    out = _request("GET", f"/persona/{pid}/", entity_id=entity_id)
    if not out.get("ok"):
        return out
    row = out.get("data") or {}
    return {
        "ok": True,
        "customer": {
            "persona_id": row.get("id"),
            "razon_social": row.get("razon_social"),
            "cedula": row.get("cedula"),
            "ruc": row.get("ruc"),
            "email": row.get("email"),
            "direccion": row.get("direccion"),
            "nombre_comercial": row.get("nombre_comercial"),
            "es_cliente": row.get("es_cliente"),
        },
    }


def customer_create(payload: dict[str, Any], *, allow_duplicate: bool = False, entity_id: str | None = None) -> dict[str, Any]:
    cedula = str(payload.get("cedula") or "").strip()
    ruc = str(payload.get("ruc") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not allow_duplicate:
        search_key = cedula or ruc or email
        if search_key:
            existing = customer_search(query=search_key, cedula=cedula or None, ruc=ruc or None, email=email or None, entity_id=entity_id)
            if existing.get("ok") and existing.get("count", 0) > 0:
                return {
                    "ok": False,
                    "error": "duplicate_customer",
                    "existing": existing.get("customers"),
                }
    body = {
        "razon_social": str(payload.get("razon_social") or "").strip(),
        "cedula": cedula,
        "ruc": ruc,
        "email": email,
        "direccion": str(payload.get("direccion") or "").strip(),
        "telefonos": str(payload.get("telefonos") or "").strip(),
        "es_cliente": True,
        "tipo": str(payload.get("tipo") or ("J" if len(ruc) == 13 else "N")),
    }
    if not body["razon_social"]:
        return {"ok": False, "error": "razon_social_required"}
    if not (cedula or ruc):
        return {"ok": False, "error": "cedula_or_ruc_required"}
    out = _request("POST", "/persona/", json_body=body, entity_id=entity_id)
    _audit("customer.create", {**body, "entity_id": _entity(entity_id).entity_id}, out)
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    return {"ok": True, "customer": data, "persona_id": data.get("id")}


def item_search(query: str = "", *, limit: int = 20, entity_id: str | None = None) -> dict[str, Any]:
    from inneros_core_runtime import contifico_bridge as bridge

    local = bridge.search_contifico_products(query, limit=limit)
    api_matches: list[dict[str, Any]] = []
    if query.strip():
        out = _request("GET", "/producto/", params={"result_page": 1, "result_size": min(limit, 50)}, entity_id=entity_id)
        if out.get("ok") and isinstance(out.get("data"), list):
            q = query.lower()
            for row in out["data"]:
                name = str(row.get("nombre") or row.get("descripcion") or "")
                if q in name.lower():
                    api_matches.append(
                        {
                            "producto_id": row.get("id"),
                            "nombre": name,
                            "precio": row.get("precio"),
                            "source": "contifico_api",
                        }
                    )
    return {
        "ok": True,
        "query": query,
        "local_catalog": local,
        "entity_id": _entity(entity_id).entity_id,
        "api_items": api_matches[:limit],
    }


def _calc_iva_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    subtotal = 0.0
    normalized: list[dict[str, Any]] = []
    for line in lines:
        qty = float(line.get("cantidad") or line.get("quantity") or 1)
        price = float(line.get("precio") or line.get("price") or 0)
        iva_pct = float(line.get("porcentaje_iva") if line.get("porcentaje_iva") is not None else 15)
        base = round(qty * price, 2)
        iva = round(base * iva_pct / 100.0, 2)
        subtotal += base
        normalized.append(
            {
                "producto_id": line.get("producto_id"),
                "producto_nombre": str(line.get("descripcion") or line.get("producto_nombre") or "Servicio"),
                "cantidad": f"{qty:.1f}",
                "precio": f"{price:.2f}",
                "porcentaje_iva": int(iva_pct),
                "porcentaje_descuento": "0.0",
                "base_gravable": f"{base:.1f}",
                "base_cero": "0.0",
                "base_no_gravable": "0.0",
                "valor_ice": "0.0",
            }
        )
    subtotal = round(subtotal, 2)
    iva_total = round(subtotal * 0.15, 2)
    total = round(subtotal + iva_total, 2)
    return {
        "lines": normalized,
        "subtotal": subtotal,
        "iva": iva_total,
        "total": total,
    }


def _idempotency_get(key: str, entity_id: str | None = None) -> dict[str, Any] | None:
    if not key:
        return None
    ent = _entity(entity_id).entity_id
    doc = mongo_store.get_db()[IDEMPOTENCY_COL].find_one({"idempotency_key": key, "entity_id": ent})
    return doc if isinstance(doc, dict) else None


def _idempotency_put(key: str, record: dict[str, Any], entity_id: str | None = None) -> None:
    if not key:
        return
    ent = _entity(entity_id).entity_id
    mongo_store.get_db()[IDEMPOTENCY_COL].update_one(
        {"idempotency_key": key, "entity_id": ent},
        {"$set": {**record, "idempotency_key": key, "entity_id": ent, "updated_at": _now()}},
        upsert=True,
    )


def _audit(action: str, request: dict[str, Any], response: dict[str, Any]) -> None:
    mongo_store.get_db()[AUDIT_COL].insert_one(
        {
            "action": action,
            "request": request,
            "response_ok": bool(response.get("ok")),
            "status": response.get("status"),
            "at": _now(),
        }
    )


def invoice_draft(
    *,
    persona_id: str,
    lines: list[dict[str, Any]],
    descripcion: str = "",
    dry_run: bool = False,
    idempotency_key: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Create non-fiscal COT (cotización) as borrador comercial."""
    pid = (persona_id or "").strip()
    if not pid:
        return {"ok": False, "error": "persona_id_required"}
    if not lines:
        return {"ok": False, "error": "lines_required"}
    calc = _calc_iva_lines(lines)
    payload = {
        "tipo_documento": "COT",
        "tipo_registro": "CLI",
        "persona_id": pid,
        "electronico": False,
        "fecha_emision": _today_ec(),
        "descripcion": (descripcion or "Borrador InnerOS MCP")[:500],
        "detalles": calc["lines"],
    }
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "entity_id": _entity(entity_id).entity_id,
            "document_type": "COT",
            "persona_id": pid,
            "payload": payload,
            "totals": {"subtotal": calc["subtotal"], "iva_15": calc["iva"], "total": calc["total"]},
        }
    if idempotency_key:
        cached = _idempotency_get(idempotency_key, entity_id=entity_id)
        if cached and cached.get("contifico_document_id"):
            return {
                "ok": True,
                "idempotent": True,
                "document_id": cached.get("contifico_document_id"),
                "document_type": cached.get("document_type"),
                "entity_id": _entity(entity_id).entity_id,
            }
    pos = _pos_token(entity_id)
    ent = _entity(entity_id)
    out = _request(
        "POST",
        "/documento/",
        json_body=payload,
        api_base=CONTIFICO_API_V2_BASE if pos else CONTIFICO_API_BASE,
        pos_token=pos or None,
        entity_id=ent.entity_id,
    )
    _audit("invoice.draft", {"persona_id": pid, "lines": len(lines), "entity_id": ent.entity_id}, out)
    if not out.get("ok"):
        err = out.get("error")
        if isinstance(err, dict) and "Pos" in err:
            out["remediation"] = (
                f"Configure {ent.pos_token_env} or enable API write for entity {ent.entity_id} in Contifico."
            )
        out["entity_id"] = ent.entity_id
        return out
    data = out.get("data") or {}
    doc_id = data.get("id")
    if idempotency_key and doc_id:
        _idempotency_put(
            idempotency_key,
            {
                "contifico_document_id": doc_id,
                "document_type": "COT",
                "persona_id": pid,
                "created_at": _now(),
            },
            entity_id=entity_id,
        )
    return {
        "ok": True,
        "entity_id": ent.entity_id,
        "document_id": doc_id,
        "document_type": "COT",
        "document_number": data.get("documento"),
        "estado": data.get("estado"),
        "electronico": data.get("electronico"),
        "payload_sent": payload,
        "totals": {"subtotal": calc["subtotal"], "iva_15": calc["iva"], "total": calc["total"]},
        "contifico_response": {k: data.get(k) for k in ("id", "documento", "estado", "iva", "total", "persona_id")},
    }


def invoice_create(
    *,
    persona_id: str,
    lines: list[dict[str, Any]],
    owner_approved: bool = False,
    approved_by: str | None = None,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Fiscal FAC — blocked unless explicit owner approval and fiscal emit flag."""
    fiscal_enabled = os.getenv("CONTIFICO_FISCAL_EMIT_ENABLED", "0").strip().lower() in ("1", "true", "yes")
    calc = _calc_iva_lines(lines)
    payload = {
        "tipo_documento": "FAC",
        "tipo_registro": "CLI",
        "persona_id": (persona_id or "").strip(),
        "electronico": True,
        "fecha_emision": _today_ec(),
        "detalles": calc["lines"],
    }
    if not owner_approved or not approved_by:
        return {
            "ok": False,
            "status": "owner_approval_required",
            "error": "owner_approval_required",
            "payload_preview": payload,
            "totals": {"subtotal": calc["subtotal"], "iva_15": calc["iva"], "total": calc["total"]},
        }
    if not fiscal_enabled:
        return {
            "ok": False,
            "status": "owner_approval_required",
            "error": "CONTIFICO_FISCAL_EMIT_ENABLED not set",
            "approved_by": approved_by,
            "payload_preview": payload,
        }
    if dry_run:
        return {"ok": True, "dry_run": True, "payload": payload}
    if idempotency_key:
        cached = _idempotency_get(idempotency_key, entity_id=entity_id)
        if cached and cached.get("contifico_document_id"):
            return {
                "ok": True,
                "idempotent": True,
                "document_id": cached.get("contifico_document_id"),
                "entity_id": _entity(entity_id).entity_id,
            }
    ent = _entity(entity_id)
    pos = _pos_token(entity_id)
    out = _request(
        "POST",
        "/documento/",
        json_body=payload,
        api_base=CONTIFICO_API_V2_BASE if pos else CONTIFICO_API_BASE,
        pos_token=pos or None,
        entity_id=ent.entity_id,
    )
    _audit("invoice.create", {"persona_id": persona_id, "approved_by": approved_by, "entity_id": ent.entity_id}, out)
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    doc_id = data.get("id")
    if idempotency_key and doc_id:
        _idempotency_put(idempotency_key, {"contifico_document_id": doc_id, "document_type": "FAC", "created_at": _now()}, entity_id=entity_id)
    return {"ok": True, "entity_id": ent.entity_id, "document_id": doc_id, "document_type": "FAC", "contifico_response": data}


def invoice_get(document_id: str, *, entity_id: str | None = None) -> dict[str, Any]:
    did = (document_id or "").strip()
    if not did:
        return {"ok": False, "error": "document_id_required"}
    out = _request("GET", f"/documento/{did}/", entity_id=entity_id)
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    return {
        "ok": True,
        "entity_id": _entity(entity_id).entity_id,
        "document": {
            "id": data.get("id"),
            "tipo_documento": data.get("tipo_documento"),
            "documento": data.get("documento"),
            "estado": data.get("estado"),
            "electronico": data.get("electronico"),
            "autorizacion": data.get("autorizacion"),
            "iva": data.get("iva"),
            "total": data.get("total"),
            "persona_id": data.get("persona_id"),
            "detalles_count": len(data.get("detalles") or []),
        },
    }


def invoice_status(document_id: str, *, entity_id: str | None = None) -> dict[str, Any]:
    got = invoice_get(document_id, entity_id=entity_id)
    if not got.get("ok"):
        return got
    doc = got.get("document") or {}
    return {
        "ok": True,
        "entity_id": _entity(entity_id).entity_id,
        "document_id": document_id,
        "estado": doc.get("estado"),
        "autorizacion": doc.get("autorizacion"),
        "electronico": doc.get("electronico"),
        "fiscal_issued": str(doc.get("tipo_documento") or "").upper() == "FAC" and bool(doc.get("autorizacion")),
    }


def payment_query(document_id: str, *, entity_id: str | None = None) -> dict[str, Any]:
    did = (document_id or "").strip()
    if not did:
        return {"ok": False, "error": "document_id_required"}
    out = _request("GET", f"/documento/{did}/cobro/", entity_id=entity_id)
    if not out.get("ok"):
        return out
    data = out.get("data")
    cobros = data if isinstance(data, list) else (data.get("results") if isinstance(data, dict) else [])
    return {"ok": True, "entity_id": _entity(entity_id).entity_id, "document_id": did, "count": len(cobros or []), "cobros": cobros or []}
