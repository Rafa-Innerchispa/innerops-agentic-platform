"""CRUD REST /api/v1/* para admin Refine."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from tools.companies import ensure_companies, seed_innerchispa_catalog
from tools.schema import ensure_client_hub, new_id

BRANDING_DIR = Path(__file__).resolve().parents[1] / "assets" / "branding"

router = APIRouter(prefix="/api/v1", tags=["admin"])


def _db():
    from tools.mongo import get_db

    return get_db()


def _now():
    return datetime.now(timezone.utc)


def _strip_id(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _list_collection(
    collection: str,
    id_field: str,
    skip: int = 0,
    limit: int = 25,
    sort: str | None = None,
) -> dict:
    db = _db()
    cur = db[collection].find({}, {"_id": 0}).skip(skip).limit(min(limit, 200))
    if sort:
        cur = cur.sort(sort, -1)
    data = list(cur)
    total = db[collection].count_documents({})
    return {"data": data, "total": total}


# --- Clients DB04 ---
class ClientIn(BaseModel):
    ruc: str
    name: str
    city: str = ""
    pais: str = "Ecuador"
    address: str = ""
    email: str = ""
    phone: str = ""
    estado: str = "Cliente"
    entidades: list[str] = Field(default_factory=list)


@router.get("/clients")
def list_clients(skip: int = 0, limit: int = 25):
    return _list_collection("clients", "client_id", skip, limit, "updated_at")


@router.get("/clients/search")
def search_clients(q: str = Query(..., min_length=2)):
    """Busca por RUC, cédula o nombre (autocompletar visitas/cotizaciones)."""
    from api.validators import normalize_phone_ec

    db = _db()
    clean = re.sub(r"\D", "", q)
    filt: dict = {"$or": [
        {"name": {"$regex": q, "$options": "i"}},
        {"ruc": {"$regex": q, "$options": "i"}},
    ]}
    if clean:
        filt["$or"].append({"ruc": {"$regex": clean}})
    data = list(
        db.clients.find(filt, {"_id": 0, "client_id": 1, "name": 1, "ruc": 1, "city": 1, "phone": 1})
        .limit(15)
    )
    return {"data": data}


@router.get("/ruc/lookup")
def ruc_lookup_api(id: str = Query(..., min_length=10)):
    from tools.gates import check_duplicate_client
    from tools.ruc_api import lookup_ruc, normalize_tax_id

    norm = normalize_tax_id(id)
    data = lookup_ruc(id)
    dup = check_duplicate_client(ruc=data.get("ruc") or norm.get("ruc"))
    return {"normalized": norm, "result": data, "duplicate": dup}


@router.get("/clients/{client_id}")
def get_client(client_id: str):
    doc = _db().clients.find_one({"client_id": client_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "cliente no encontrado")
    return doc


@router.post("/clients")
def create_client(body: ClientIn):
    from api.validators import normalize_phone_ec, validate_email, validate_phone_ec, validate_ruc_cedula
    from tools.gates import check_duplicate_client
    from tools.ruc_api import normalize_tax_id

    if err := validate_ruc_cedula(body.ruc):
        raise HTTPException(400, err)
    if not body.name.strip():
        raise HTTPException(400, "Nombre es obligatorio")
    if err := validate_email(body.email):
        raise HTTPException(400, err)
    if err := validate_phone_ec(body.phone):
        raise HTTPException(400, err)
    if body.estado not in {"Cliente", "Proveedor", "Cliente y Proveedor"}:
        raise HTTPException(400, "Estado debe ser Cliente, Proveedor o Cliente y Proveedor")

    norm = normalize_tax_id(body.ruc)
    ruc_final = norm.get("ruc") or body.ruc
    dup = check_duplicate_client(ruc=ruc_final)
    if not dup.get("passed"):
        raise HTTPException(409, dup.get("message", "Cliente duplicado por RUC"))

    db = _db()
    client_id = new_id("cli")
    doc = {
        "client_id": client_id,
        "ruc": ruc_final,
        "cedula": norm.get("cedula"),
        "name": body.name.strip(),
        "city": body.city.strip(),
        "pais": body.pais.strip() or "Ecuador",
        "address": body.address.strip(),
        "email": body.email.strip(),
        "phone": normalize_phone_ec(body.phone),
        "estado": body.estado,
        "entidades": body.entidades or [],
        "hub_ready": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.clients.insert_one(doc)
    doc.pop("_id", None)
    ensure_client_hub(db, doc["client_id"], doc["name"])
    return _strip_id(doc)


@router.patch("/clients/{client_id}")
def update_client(client_id: str, body: dict[str, Any]):
    from tools.client_sanitize import normalize_tax_id_field, valid_tax_id

    body = dict(body)
    body["updated_at"] = _now()
    if "ruc" in body:
        ruc = normalize_tax_id_field(body.get("ruc"))
        if valid_tax_id(ruc):
            body["ruc"] = ruc
        else:
            body.pop("ruc", None)
            _db().clients.update_one({"client_id": client_id}, {"$unset": {"ruc": ""}})
    res = _db().clients.update_one({"client_id": client_id}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "cliente no encontrado")
    return get_client(client_id)


# --- Inventory DB26 ---
@router.get("/inventory-items")
def list_inventory(skip: int = 0, limit: int = 25, q: str | None = None):
    db = _db()
    filt = {}
    if q:
        filt = {"$or": [
            {"nombre": {"$regex": q, "$options": "i"}},
            {"sku": {"$regex": q, "$options": "i"}},
            {"item_code": {"$regex": q, "$options": "i"}},
        ]}
    data = list(db.inventory_items.find(filt, {"_id": 0}).skip(skip).limit(limit))
    total = db.inventory_items.count_documents(filt)
    return {"data": data, "total": total}


@router.get("/inventory-items/{item_code}")
def get_inventory_item(item_code: str):
    doc = _db().inventory_items.find_one({"item_code": item_code}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "ítem no encontrado")
    return doc


class InventoryIn(BaseModel):
    nombre: str
    marca: str = ""
    sku: str = ""
    categoria: str = ""
    stock: int = 0
    supplier_id: str = ""
    precio_proveedor: float = 0
    precio_contado: float = 0
    precio_tarjeta: float = 0
    precio: float = 0


@router.post("/inventory-items")
def create_inventory(body: InventoryIn):
    from tools.schema import next_serial

    db = _db()
    if not body.nombre.strip():
        raise HTTPException(400, "Nombre es obligatorio")
    sku = body.sku.strip() or next_serial(db, "PCD", "INV")["code"]
    if db.inventory_items.find_one({"sku": sku}):
        raise HTTPException(409, f"SKU/código {sku} ya existe en inventario")
    precio_venta = body.precio_contado or body.precio or 0
    doc = {
        "item_code": new_id("inv"),
        "sku": sku,
        "nombre": body.nombre.strip(),
        "marca": body.marca.strip(),
        "categoria": body.categoria.strip(),
        "stock": body.stock,
        "supplier_id": body.supplier_id,
        "precio_proveedor": body.precio_proveedor,
        "precio_contado": body.precio_contado or precio_venta,
        "precio_tarjeta": body.precio_tarjeta or (precio_venta * 1.05 if precio_venta else 0),
        "precio": precio_venta,
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.inventory_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


# --- Catalog DB13 ---
class CatalogIn(BaseModel):
    code: str = ""
    nombre: str
    tipo: str = "servicio"
    empresa: str = "pcdoctor"
    linea_negocio: str = ""
    precio_sugerido: float = 0
    descripcion_comercial: str = ""
    estado: str = "Activo"


@router.get("/catalog-products")
def list_catalog(skip: int = 0, limit: int = 25):
    return _list_collection("catalog_products", "code", skip, limit)


@router.post("/catalog-products")
def create_catalog(body: CatalogIn):
    from tools.schema import next_serial

    db = _db()
    if not body.nombre.strip():
        raise HTTPException(400, "Nombre es obligatorio")
    code = body.code.strip()
    if not code:
        ent = "PCD" if body.empresa == "pcdoctor" else "IS"
        code = next_serial(db, ent, "COT")["code"] + "-CAT"
    if db.catalog_products.find_one({"code": code}):
        raise HTTPException(409, f"El código {code} ya existe en catálogo")
    doc = {**body.model_dump(), "code": code, "created_at": _now(), "updated_at": _now(), "activo": True}
    db.catalog_products.insert_one(doc)
    doc.pop("_id", None)
    return doc


# --- Suppliers DB25 ---
class SupplierIn(BaseModel):
    nombre: str
    ruc: str = ""
    ciudad: str = ""
    email: str = ""
    phone: str = ""
    estado: str = "Activo"


@router.get("/suppliers")
def list_suppliers(skip: int = 0, limit: int = 25):
    return _list_collection("suppliers", "supplier_id", skip, limit)


@router.post("/suppliers")
def create_supplier(body: SupplierIn):
    db = _db()
    doc = {
        "supplier_id": new_id("sup"),
        **body.model_dump(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.suppliers.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _iso_date(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    s = str(value)
    return s[:10] if len(s) >= 10 else s


VISIT_ESTADO_EN = {
    "abierta": "Open",
    "cerrada": "Closed",
    "Cerrado": "Closed",
    "cerrado": "Closed",
    "en_progreso": "In progress",
    "completada": "Completed",
    "cancelada": "Cancelled",
    "Borrador": "Draft",
    "borrador": "Draft",
}


# --- Quotes DB27 ---
@router.get("/quotes")
def list_quotes(skip: int = 0, limit: int = 25):
    from tools.gates import calc_quote_from_lines

    db = _db()
    data = list(db.quotes.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))
    client_ids = {q.get("client_id") for q in data if q.get("client_id")}
    clients_map: dict[str, dict] = {}
    if client_ids:
        for c in db.clients.find(
            {"client_id": {"$in": list(client_ids)}},
            {"_id": 0, "client_id": 1, "name": 1, "ruc": 1},
        ):
            clients_map[c["client_id"]] = c

    for q in data:
        q["serial"] = q.get("serial") or q.get("code") or ""
        if not q.get("company_id"):
            q["company_id"] = q.get("empresa") or "pcdoctor"
        cid = q.get("client_id")
        if cid and cid in clients_map:
            c = clients_map[cid]
            q.setdefault("client_name", c.get("name"))
            q.setdefault("ruc", c.get("ruc"))
        elif q.get("client_ruc"):
            q.setdefault("ruc", q["client_ruc"])
        total_val = q.get("total") or q.get("total_calculado") or 0
        if not total_val and q.get("quote_id"):
            calc = calc_quote_from_lines(q["quote_id"])
            if calc["total"]:
                q["total"] = calc["total"]
        elif total_val and not q.get("total"):
            q["total"] = total_val

    total = db.quotes.count_documents({})
    return {"data": data, "total": total}


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str):
    db = _db()
    doc = db.quotes.find_one({"quote_id": quote_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "cotización no encontrada")
    doc["lines"] = list(db.quote_lines.find({"quote_id": quote_id}, {"_id": 0}))
    return doc


class QuoteIn(BaseModel):
    client_id: str
    company_id: str = "pcdoctor"
    titulo: str = ""
    notas: str = ""


@router.post("/quotes")
def create_quote(body: QuoteIn):
    from tools.schema import next_serial

    db = _db()
    if not db.clients.find_one({"client_id": body.client_id}):
        raise HTTPException(404, "cliente no encontrado")
    serial_doc = next_serial(db, "PCD", "COT")
    serial = serial_doc["code"]
    doc = {
        "quote_id": new_id("qte"),
        "serial": serial,
        "client_id": body.client_id,
        "company_id": body.company_id,
        "titulo": body.titulo or f"Cotización {serial}",
        "notas": body.notas,
        "estado": "borrador",
        "total": 0.0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.quotes.insert_one(doc)
    doc.pop("_id", None)
    return doc


# --- Visits DB42 ---
@router.get("/sop-visits")
def list_visits(skip: int = 0, limit: int = 25):
    db = _db()
    data = list(db.sop_visits.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))
    for v in data:
        c = db.clients.find_one({"client_id": v.get("client_id")}, {"_id": 0, "name": 1, "ruc": 1})
        if c:
            v["client_name"] = c.get("name")
            v["client_ruc"] = c.get("ruc")
        v["fecha"] = _iso_date(v.get("fecha") or v.get("created_at"))
        estado = v.get("estado") or "abierta"
        v["estado_label"] = VISIT_ESTADO_EN.get(estado, estado)
    total = db.sop_visits.count_documents({})
    return {"data": data, "total": total}


class VisitIn(BaseModel):
    client_id: str = ""
    client_ruc: str = ""
    client_query: str = ""
    tipo: str = "soporte"
    notas: str = ""


def _resolve_client_id(db, client_id: str = "", client_ruc: str = "", client_query: str = "") -> str:
    if client_id:
        if db.clients.find_one({"client_id": client_id}):
            return client_id
        raise HTTPException(404, "cliente no encontrado")
    q = re.sub(r"\D", "", client_ruc or client_query)
    if q:
        hit = db.clients.find_one({"ruc": {"$regex": q}}, {"client_id": 1})
        if hit:
            return hit["client_id"]
    if client_query:
        hit = db.clients.find_one({"name": {"$regex": client_query, "$options": "i"}}, {"client_id": 1})
        if hit:
            return hit["client_id"]
    raise HTTPException(404, "No encontré cliente — busca por RUC o nombre")


@router.post("/sop-visits")
def create_visit(body: VisitIn):
    db = _db()
    cid = _resolve_client_id(db, body.client_id, body.client_ruc, body.client_query)
    client = db.clients.find_one({"client_id": cid}, {"_id": 0, "name": 1, "ruc": 1})
    doc = {
        "visit_id": new_id("vis"),
        "client_id": cid,
        "client_name": client.get("name") if client else "",
        "client_ruc": client.get("ruc") if client else "",
        "tipo": body.tipo,
        "notas": body.notas,
        "estado": "abierta",
        "fecha": _now().isoformat(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.sop_visits.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/sop-visits/by-client/{client_id}")
def visits_by_client(client_id: str):
    db = _db()
    if not db.clients.find_one({"client_id": client_id}):
        raise HTTPException(404, "cliente no encontrado")
    data = list(
        db.sop_visits.find({"client_id": client_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(50)
    )
    return {"data": data, "total": len(data)}


# --- Technical reports DB45 ---
@router.get("/technical-reports")
def list_reports(skip: int = 0, limit: int = 25):
    db = _db()
    data = list(db.technical_reports.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))
    for r in data:
        r["serial"] = r.get("serial") or r.get("code") or ""
        r["titulo"] = r.get("titulo") or r.get("title") or "Technical report"
        if r.get("client_id"):
            c = db.clients.find_one({"client_id": r["client_id"]}, {"_id": 0, "name": 1, "ruc": 1})
            if c:
                r["client_name"] = c.get("name")
                r["client_ruc"] = c.get("ruc")
        elif r.get("visit_id"):
            v = db.sop_visits.find_one({"visit_id": r["visit_id"]}, {"_id": 0, "client_name": 1, "client_ruc": 1})
            if v:
                r["client_name"] = v.get("client_name")
                r["client_ruc"] = v.get("client_ruc")
        estado = r.get("estado") or "borrador"
        r["estado_label"] = VISIT_ESTADO_EN.get(estado, estado)
    total = db.technical_reports.count_documents({})
    return {"data": data, "total": total}


class ReportIn(BaseModel):
    titulo: str
    visit_id: str
    client_id: str = ""
    content_md: str = ""


@router.post("/technical-reports")
def create_report(body: ReportIn):
    from tools.schema import next_serial

    db = _db()
    visit = db.sop_visits.find_one({"visit_id": body.visit_id}, {"_id": 0})
    if not visit:
        raise HTTPException(404, "visita no encontrada — el informe debe ligarse a una visita")
    client_id = body.client_id or visit.get("client_id") or ""
    client = db.clients.find_one({"client_id": client_id}, {"_id": 0, "name": 1, "ruc": 1}) if client_id else None
    serial_doc = next_serial(db, "PCD", "RPT")
    serial = serial_doc["code"]
    doc = {
        "report_id": new_id("rpt"),
        "serial": serial,
        "titulo": body.titulo,
        "client_id": client_id,
        "client_name": client.get("name") if client else visit.get("client_name", ""),
        "client_ruc": client.get("ruc") if client else visit.get("client_ruc", ""),
        "visit_id": body.visit_id,
        "visit_tipo": visit.get("tipo", ""),
        "content_md": body.content_md,
        "estado": "borrador",
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.technical_reports.insert_one(doc)
    doc.pop("_id", None)
    return doc


# --- Companies (multiempresa) ---
@router.get("/companies")
def list_companies():
    db = _db()
    ensure_companies(db)
    data = list(db.companies.find({"active": True}, {"_id": 0}))
    return {"data": data, "total": len(data)}


@router.get("/companies/{company_id}")
def get_company(company_id: str):
    doc = _db().companies.find_one({"company_id": company_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "empresa no encontrada")
    return doc


@router.patch("/companies/{company_id}")
def update_company(company_id: str, body: dict[str, Any]):
    allowed = {
        "brand_name", "legal_name", "tagline", "logo_file", "icon_file",
        "colors", "default_for_quotes", "active",
    }
    patch = {k: v for k, v in body.items() if k in allowed}
    if not patch:
        raise HTTPException(400, "sin campos válidos")
    patch["updated_at"] = _now()
    res = _db().companies.update_one({"company_id": company_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "empresa no encontrada")
    return get_company(company_id)


@router.post("/companies/seed-catalog")
def seed_catalog():
    """Crea servicios InnerChispa en catálogo si no existen."""
    db = _db()
    ensure_companies(db)
    n = seed_innerchispa_catalog(db)
    return {"inserted": n, "message": f"{n} servicios InnerChispa agregados al catálogo"}


@router.post("/companies/{company_id}/logo")
async def upload_company_logo(company_id: str, file: UploadFile = File(...)):
    company = _db().companies.find_one({"company_id": company_id})
    if not company:
        raise HTTPException(404, "empresa no encontrada")
    ext = Path(file.filename or "logo.png").suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise HTTPException(400, "formato no soportado")
    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"logo_{company['slug']}{ext}"
    dest = BRANDING_DIR / fname
    content = await file.read()
    dest.write_bytes(content)
    _db().companies.update_one(
        {"company_id": company_id},
        {"$set": {"logo_file": fname, "updated_at": _now()}},
    )
    return {"logo_file": fname, "url": f"/assets/branding/{fname}"}


# --- Entities DB01 ---
class EntityIn(BaseModel):
    name: str
    slug: str = ""
    kind: str = "organization"  # organization | personal | platform
    aliases: list[str] = Field(default_factory=list)
    status: str = "active"
    notes: str = ""
    linkedin_author_urn: str = ""
    linkedin_publish_as: str = ""  # person | organization


@router.get("/entities")
def list_entities(skip: int = 0, limit: int = 50):
    return _list_collection("entities", "entity_id", skip, limit, "name")


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    doc = _db().entities.find_one({"entity_id": entity_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "entidad no encontrada")
    return doc


@router.post("/entities")
def create_entity(body: EntityIn):
    if not body.name.strip():
        raise HTTPException(400, "Nombre obligatorio")
    slug = (body.slug or body.name).strip().lower().replace(" ", "-")
    db = _db()
    if db.entities.find_one({"slug": slug}):
        raise HTTPException(409, "slug ya existe")
    entity_id = new_id("ent")
    now = _now()
    doc = {
        "entity_id": entity_id,
        "slug": slug,
        "name": body.name.strip(),
        "kind": body.kind,
        "aliases": body.aliases or [],
        "status": body.status or "active",
        "notes": body.notes or "",
        "linkedin_author_urn": (body.linkedin_author_urn or "").strip(),
        "linkedin_publish_as": (body.linkedin_publish_as or body.kind or "").strip(),
        "created_at": now,
        "updated_at": now,
    }
    db.entities.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: str, body: EntityIn):
    db = _db()
    if not db.entities.find_one({"entity_id": entity_id}):
        raise HTTPException(404, "entidad no encontrada")
    patch = {
        "name": body.name.strip(),
        "kind": body.kind,
        "aliases": body.aliases or [],
        "status": body.status or "active",
        "notes": body.notes or "",
        "linkedin_author_urn": (body.linkedin_author_urn or "").strip(),
        "linkedin_publish_as": (body.linkedin_publish_as or body.kind or "").strip(),
        "updated_at": _now(),
    }
    if body.slug.strip():
        patch["slug"] = body.slug.strip().lower()
    db.entities.update_one({"entity_id": entity_id}, {"$set": patch})
    doc = db.entities.find_one({"entity_id": entity_id}, {"_id": 0})
    return doc


# --- Meta ---
@router.get("/stats")
def admin_stats():
    db = _db()
    return {
        "clients": db.clients.count_documents({}),
        "entities": db.entities.count_documents({}),
        "inventory_items": db.inventory_items.count_documents({}),
        "catalog_products": db.catalog_products.count_documents({}),
        "suppliers": db.suppliers.count_documents({}),
        "quotes": db.quotes.count_documents({}),
        "sop_visits": db.sop_visits.count_documents({}),
        "technical_reports": db.technical_reports.count_documents({}),
    }
