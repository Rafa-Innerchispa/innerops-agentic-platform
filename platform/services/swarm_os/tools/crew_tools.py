"""Herramientas CrewAI conectadas a MongoDB y servicios locales."""

import json
import re
import uuid

from crewai.tools import tool

from tools.mongo import (
    create_client,
    create_inspection,
    get_inspection,
    log_action,
    lookup_client_by_ruc,
    save_findings,
    save_quote,
    save_report,
    search_inventory,
)
from tools.ruc_api import lookup_ruc


def _extract_ruc(text: str) -> str | None:
    m = re.search(r"\b\d{13}\b", text)
    return m.group(0) if m else None


@tool("Consultar RUC o cédula en SRI")
def sri_lookup_tool(ruc: str) -> str:
    """Consulta contribuyente por RUC (13 dígitos) o cédula (10 dígitos). Devuelve JSON."""
    data = lookup_ruc(ruc)
    log_action("cliente", "sri_lookup", {"ruc": ruc})
    return json.dumps(data, ensure_ascii=False)


@tool("Crear o actualizar cliente en MongoDB")
def upsert_client_tool(ruc: str, name: str, address: str = "", city: str = "") -> str:
    """Guarda cliente en la base de datos. Usar después de consultar SRI."""
    from tools.client_sanitize import normalize_tax_id_field, valid_tax_id

    ruc = normalize_tax_id_field(ruc)
    if not valid_tax_id(ruc):
        return json.dumps({"error": "RUC/cédula vacío o inválido"}, ensure_ascii=False)
    client = create_client({"ruc": ruc, "name": name, "address": address, "city": city})
    log_action("cliente", "upsert_client", {"ruc": ruc})
    return json.dumps(client, ensure_ascii=False, default=str)


@tool("Buscar cliente existente por RUC")
def find_client_tool(ruc: str) -> str:
    """Devuelve cliente si ya existe en MongoDB."""
    client = lookup_client_by_ruc(ruc)
    return json.dumps(client or {"found": False}, ensure_ascii=False, default=str)


@tool("Buscar ítems en inventario")
def inventory_search_tool(query: str) -> str:
    """Busca materiales y servicios en inventario para cotizar."""
    items = search_inventory(query, limit=8)
    return json.dumps(items, ensure_ascii=False)


@tool("Guardar hallazgos y bitácora de inspección")
def save_inspection_findings_tool(inspection_id: str, findings_json: str, pending_json: str) -> str:
    """Guarda hallazgos (JSON array) y tareas pendientes (JSON array de strings)."""
    findings = json.loads(findings_json)
    pending = json.loads(pending_json)
    doc = save_findings(inspection_id, findings, pending)
    log_action("bitacora", "save_findings", {"inspection_id": inspection_id})
    return json.dumps(doc, ensure_ascii=False, default=str)


@tool("Guardar informe técnico en MongoDB")
def save_report_tool(inspection_id: str, report_json: str) -> str:
    """Guarda informe técnico estructurado (JSON)."""
    report = json.loads(report_json)
    doc = save_report(inspection_id, report)
    log_action("informes", "save_report", {"inspection_id": inspection_id})
    return json.dumps(doc, ensure_ascii=False, default=str)


@tool("Guardar cotización en MongoDB")
def save_quote_tool(inspection_id: str, quote_json: str) -> str:
    """Guarda cabecera y líneas de cotización (JSON con lines, subtotal, iva, total)."""
    quote = json.loads(quote_json)
    doc = save_quote(inspection_id, quote)
    log_action("cotizador", "save_quote", {"inspection_id": inspection_id})
    return json.dumps(doc, ensure_ascii=False, default=str)


def start_inspection_record(raw_input: str, inspection_id: str | None = None) -> str:
    """Crea registro de inspección (no es tool de agente, uso interno)."""
    inspection_id = inspection_id or uuid.uuid4().hex[:12]
    ruc = _extract_ruc(raw_input)
    if not get_inspection(inspection_id):
        create_inspection(inspection_id, raw_input, ruc=ruc)
    log_action("director", "inspection_started", {"inspection_id": inspection_id})
    return inspection_id


def get_inspection_context(inspection_id: str) -> dict:
    return get_inspection(inspection_id) or {}
