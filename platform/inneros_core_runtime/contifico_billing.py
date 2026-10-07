"""Contífico billing API — governed read/write for MCP capabilities (PC Doctor)."""

from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

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


def _sanitize_text(text: str) -> str:
    if not text:
        return text
    red = _SECRET_RE.sub(r"\1=***", text)
    key = (CONTIFICO_API_KEY or "").strip()
    if key:
        red = red.replace(key, "***")
    return red


def _headers() -> dict[str, str]:
    key = (CONTIFICO_API_KEY or "").strip()
    if not key:
        raise ValueError("CONTIFICO_API_KEY not configured")
    return {"Authorization": key, "Accept": "application/json", "Content-Type": "application/json"}


def _pos_token() -> str:
    explicit = (os.getenv("CONTIFICO_POS_TOKEN") or "").strip()
    if explicit:
        return explicit
    listed = list_pos_emission_points()
    if listed.get("ok") and listed.get("points"):
        return str(listed["points"][0].get("token") or "")
    return ""


def list_pos_emission_points() -> dict[str, Any]:
    key = (CONTIFICO_API_KEY or "").strip()
    if not key:
        return {"ok": False, "error": "CONTIFICO_API_KEY not configured"}
    url = f"{CONTIFICO_API_V2_BASE.rstrip('/')}/pos/"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers={"Authorization": key, "Accept": "application/json"})
    try:
        data = resp.json()
    except Exception:
        data = {"raw": _sanitize_text((resp.text or "")[:500])}
    if not resp.is_success:
        return {"ok": False, "status": resp.status_code, "error": data}
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
    return {"ok": True, "count": len(points), "points": points}


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    api_base: str | None = None,
    pos_token: str | None = None,
) -> dict[str, Any]:
    _throttle()
    base = (api_base or CONTIFICO_API_BASE).rstrip("/")
    url = f"{base}{path}"
    headers = _headers()
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


def connection_status() -> dict[str, Any]:
    key = (CONTIFICO_API_KEY or "").strip()
    if not key:
        return {
            "ok": False,
            "configured": False,
            "connected": False,
            "message": "CONTIFICO_API_KEY missing",
        }
    probe = _request("GET", "/persona/", params={"result_page": 1, "result_size": 1})
    doc_probe = _request("GET", "/documento/", params={"result_page": 1, "result_size": 3})
    pos_info = list_pos_emission_points()
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
    return {
        "ok": bool(probe.get("ok")),
        "configured": True,
        "connected": bool(probe.get("ok")),
        "api_base": CONTIFICO_API_BASE,
        "company_token_set": bool((CONTIFICO_COMPANY_TOKEN or "").strip()),
        "api_key_fingerprint": hashlib.sha256(key.encode()).hexdigest()[:12],
        "document_types_seen": sorted(doc_types),
        "sample_pos": sample_pos,
        "non_fiscal_draft_type": "COT",
        "fiscal_invoice_type": "FAC",
        "sandbox_detected": False,
        "note": "COT (cotización, electronico=false) used as borrador no fiscal; FAC requires owner approval.",
        "pos_emission_points": pos_info.get("points") if pos_info.get("ok") else [],
        "connected_company_ruc": (pos_info.get("points") or [{}])[0].get("ruc") if pos_info.get("ok") and pos_info.get("points") else None,
        "write_api_note": "POST /documento/ requiere Pos token v2; si falla Pos token, habilitar escritura API en Contifico.",
        "module": "contifico_billing.v1",
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
        out = _request("GET", "/persona/", params={"result_page": page, "result_size": page_size})
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
    return {"ok": True, "query": needle, "count": len(matches), "customers": matches}


def customer_get(persona_id: str) -> dict[str, Any]:
    pid = (persona_id or "").strip()
    if not pid:
        return {"ok": False, "error": "persona_id_required"}
    out = _request("GET", f"/persona/{pid}/")
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


def customer_create(payload: dict[str, Any], *, allow_duplicate: bool = False) -> dict[str, Any]:
    cedula = str(payload.get("cedula") or "").strip()
    ruc = str(payload.get("ruc") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not allow_duplicate:
        search_key = cedula or ruc or email
        if search_key:
            existing = customer_search(query=search_key, cedula=cedula or None, ruc=ruc or None, email=email or None)
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
    out = _request("POST", "/persona/", json_body=body)
    _audit("customer.create", body, out)
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    return {"ok": True, "customer": data, "persona_id": data.get("id")}


def item_search(query: str = "", *, limit: int = 20) -> dict[str, Any]:
    from inneros_core_runtime import contifico_bridge as bridge

    local = bridge.search_contifico_products(query, limit=limit)
    api_matches: list[dict[str, Any]] = []
    if query.strip():
        out = _request("GET", "/producto/", params={"result_page": 1, "result_size": min(limit, 50)})
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


def _idempotency_get(key: str) -> dict[str, Any] | None:
    if not key:
        return None
    doc = mongo_store.get_db()[IDEMPOTENCY_COL].find_one({"idempotency_key": key})
    return doc if isinstance(doc, dict) else None


def _idempotency_put(key: str, record: dict[str, Any]) -> None:
    if not key:
        return
    mongo_store.get_db()[IDEMPOTENCY_COL].update_one(
        {"idempotency_key": key},
        {"$set": {**record, "idempotency_key": key, "updated_at": _now()}},
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
            "document_type": "COT",
            "persona_id": pid,
            "payload": payload,
            "totals": {"subtotal": calc["subtotal"], "iva_15": calc["iva"], "total": calc["total"]},
        }
    if idempotency_key:
        cached = _idempotency_get(idempotency_key)
        if cached and cached.get("contifico_document_id"):
            return {
                "ok": True,
                "idempotent": True,
                "document_id": cached.get("contifico_document_id"),
                "document_type": cached.get("document_type"),
            }
    pos = _pos_token()
    out = _request(
        "POST",
        "/documento/",
        json_body=payload,
        api_base=CONTIFICO_API_V2_BASE if pos else CONTIFICO_API_BASE,
        pos_token=pos or None,
    )
    _audit("invoice.draft", {"persona_id": pid, "lines": len(lines)}, out)
    if not out.get("ok"):
        err = out.get("error")
        if isinstance(err, dict) and "Pos" in err:
            out["remediation"] = (
                "Configure CONTIFICO_POS_TOKEN from GET /sistema/api/v2/pos/ and confirm API write scope with Contifico."
            )
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
        )
    return {
        "ok": True,
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
        cached = _idempotency_get(idempotency_key)
        if cached and cached.get("contifico_document_id"):
            return {
                "ok": True,
                "idempotent": True,
                "document_id": cached.get("contifico_document_id"),
            }
    out = _request("POST", "/documento/", json_body=payload)
    _audit("invoice.create", {"persona_id": persona_id, "approved_by": approved_by}, out)
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    doc_id = data.get("id")
    if idempotency_key and doc_id:
        _idempotency_put(idempotency_key, {"contifico_document_id": doc_id, "document_type": "FAC", "created_at": _now()})
    return {"ok": True, "document_id": doc_id, "document_type": "FAC", "contifico_response": data}


def invoice_get(document_id: str) -> dict[str, Any]:
    did = (document_id or "").strip()
    if not did:
        return {"ok": False, "error": "document_id_required"}
    out = _request("GET", f"/documento/{did}/")
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    return {
        "ok": True,
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


def invoice_status(document_id: str) -> dict[str, Any]:
    got = invoice_get(document_id)
    if not got.get("ok"):
        return got
    doc = got.get("document") or {}
    return {
        "ok": True,
        "document_id": document_id,
        "estado": doc.get("estado"),
        "autorizacion": doc.get("autorizacion"),
        "electronico": doc.get("electronico"),
        "fiscal_issued": str(doc.get("tipo_documento") or "").upper() == "FAC" and bool(doc.get("autorizacion")),
    }


def payment_query(document_id: str) -> dict[str, Any]:
    did = (document_id or "").strip()
    if not did:
        return {"ok": False, "error": "document_id_required"}
    out = _request("GET", f"/documento/{did}/cobro/")
    if not out.get("ok"):
        return out
    data = out.get("data")
    cobros = data if isinstance(data, list) else (data.get("results") if isinstance(data, dict) else [])
    return {"ok": True, "document_id": did, "count": len(cobros or []), "cobros": cobros or []}
