"""Capability Registry en sombra — inventario + perfiles sin romper tools legacy.

capability_id es inmutable; mcp_tool_name puede cambiar o ser alias.
Modo sombra: no filtra el endpoint MCP global; solo documenta y sirve perfiles.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from raphiia_openai.mcp_catalog import tool_catalog

REGISTRY_COL = "ralfia_capability_registry"
INVENTORY_COL = "ralfia_tool_inventory"
ROUTING_TRACE_COL = "ralfia_routing_trace"

# Heurística dominio por prefijo/nombre
_DOMAIN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("contifico", re.compile(r"contifico|banco_movimientos|import_contifico", re.I)),
    ("accounting", re.compile(r"payable|receivable|accounting_|purchase|payment|collection", re.I)),
    ("pcdoctor", re.compile(r"client|site|visit|asset|quote|supervisor|observation|media_to_", re.I)),
    ("communications", re.compile(r"whatsapp|email|correo|notify|contact|reminder", re.I)),
    ("coordination", re.compile(r"coordination|agent_message|ops_task|project_map|bootstrap|mailbox", re.I)),
    ("notion", re.compile(r"notion", re.I)),
    ("editorial", re.compile(r"pipeline|draft_image|publish_pipeline|dalle|linkedin", re.I)),
    ("ai_runtime", re.compile(r"ollama|local_model|classify_task|cognitive|route_ai", re.I)),
    ("mcp_meta", re.compile(r"mcp_|diagnose_mcp|describe_tool|health_check|system_|list_mcp", re.I)),
    ("search", re.compile(r"^(search|fetch)$", re.I)),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    from raphiia_openai import mongo_store

    return mongo_store.get_db()


def infer_domain(tool_name: str) -> str:
    for domain, pat in _DOMAIN_RULES:
        if pat.search(tool_name):
            return domain
    return "general"


def infer_risk(tool_name: str, meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    if meta.get("risk_level"):
        return str(meta["risk_level"])
    scopes = meta.get("required_scopes") or []
    name = tool_name.lower()
    if any(s.endswith("admin") for s in scopes) or "delete" in name or "import_contifico_full" in name:
        return "high"
    if any("write" in s for s in scopes) or name.startswith(("create_", "upsert_", "update_", "send_", "publish_")):
        return "medium"
    return "low"


def capability_id_for_tool(tool_name: str) -> str:
    return f"cap.legacy.{tool_name}"


def build_tool_inventory() -> dict[str, Any]:
    """Inventario de todas las tools del catálogo legacy."""
    items = []
    for name in sorted(tool_catalog.ALL_MCP_TOOL_NAMES):
        meta = tool_catalog.TOOL_DEFINITIONS.get(name) or {}
        domain = infer_domain(name)
        risk = infer_risk(name, meta)
        audience = "all"
        if domain in {"mcp_meta", "coordination"}:
            audience = "operators"
        elif domain == "contifico":
            audience = "finance_ops"
        elif domain == "pcdoctor":
            audience = "field_ops"
        items.append(
            {
                "mcp_tool_name": name,
                "capability_id": capability_id_for_tool(name),
                "type": "tool",
                "domain": domain,
                "module": domain,
                "risk": risk,
                "scopes": meta.get("required_scopes") or [],
                "status": "legacy_active",
                "shadow": True,
                "description": (meta.get("description") or "")[:240],
                "inventoried_at": _now(),
            }
        )
    # Contífico analytics capabilities (piloto — no reemplazan legacy aún)
    for cid, tool, desc in [
        ("cap.contifico.resolve_entity", "contifico_resolve_entity", "Resuelve entidad Contífico con ranking"),
        ("cap.contifico.query", "contifico_query", "Query DSL analítica Contífico read-only"),
        ("cap.contifico.get_document", "contifico_get_document", "Detalle documento Contífico"),
        ("cap.contifico.party_360", "contifico_get_party_360", "Vista 360 cliente/proveedor"),
        ("cap.contifico.explain_metric", "contifico_explain_metric", "Definición de métrica canónica"),
        ("cap.contifico.analytics_caps", "contifico_analytics_capabilities", "Catálogo DSL Contífico"),
    ]:
        items.append(
            {
                "mcp_tool_name": tool,
                "capability_id": cid,
                "type": "tool",
                "domain": "contifico",
                "module": "contifico_analytics",
                "risk": "low",
                "scopes": ["ralfia:read"],
                "status": "pilot_active",
                "shadow": True,
                "description": desc,
                "inventoried_at": _now(),
            }
        )
    by_domain: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for it in items:
        by_domain[it["domain"]] = by_domain.get(it["domain"], 0) + 1
        by_risk[it["risk"]] = by_risk.get(it["risk"], 0) + 1
    return {
        "ok": True,
        "count": len(items),
        "legacy_tools": len(tool_catalog.ALL_MCP_TOOL_NAMES),
        "by_domain": dict(sorted(by_domain.items(), key=lambda x: -x[1])),
        "by_risk": by_risk,
        "items": items,
        "catalog_version": tool_catalog.MCP_VERSION,
    }


def persist_shadow_registry(*, replace: bool = True) -> dict[str, Any]:
    """Persiste inventario en Mongo (sombra). No altera el endpoint tools/list global."""
    db = _db()
    inv = build_tool_inventory()
    if replace:
        db[INVENTORY_COL].delete_many({})
        db[REGISTRY_COL].delete_many({"shadow": True})
    if inv["items"]:
        db[INVENTORY_COL].insert_many(inv["items"])
        for it in inv["items"]:
            db[REGISTRY_COL].update_one(
                {"capability_id": it["capability_id"]},
                {"$set": {**it, "updated_at": _now()}, "$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
    snapshot = {
        "ok": True,
        "persisted": len(inv["items"]),
        "by_domain": inv["by_domain"],
        "by_risk": inv["by_risk"],
        "catalog_version": inv["catalog_version"],
        "mode": "shadow",
        "updated_at": _now(),
    }
    db.ralfia_coordination_state.update_one(
        {"_id": "capability_registry_shadow"},
        {"$set": {"state": snapshot, "updated_at": _now()}},
        upsert=True,
    )
    return snapshot


def catalog_fingerprint() -> dict[str, Any]:
    names = sorted(tool_catalog.ALL_MCP_TOOL_NAMES)
    names_hash = hashlib.sha256(json.dumps(names, separators=(",", ":")).encode()).hexdigest()
    return {
        "ok": True,
        "catalog_version": tool_catalog.MCP_VERSION,
        "tool_count": len(names),
        "tool_names_hash": names_hash,
        "tool_names_hash_short": names_hash[:16],
        "pin_hint": f"{tool_catalog.MCP_VERSION}:{names_hash[:12]}",
    }


def log_routing_trace(payload: dict[str, Any]) -> None:
    """Trace de routing (separado del audit de negocio)."""
    try:
        doc = {**payload, "created_at": _now(), "kind": "routing_trace"}
        _db()[ROUTING_TRACE_COL].insert_one(doc)
    except Exception:
        pass


def get_registry_summary() -> dict[str, Any]:
    db = _db()
    n = db[REGISTRY_COL].count_documents({})
    domains = list(db[REGISTRY_COL].aggregate([{"$group": {"_id": "$domain", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]))
    fp = catalog_fingerprint()
    return {
        "ok": True,
        "registry_count": n,
        "by_domain": {d["_id"]: d["n"] for d in domains},
        "fingerprint": fp,
        "mode": "shadow",
        "note": "Legacy MCP tools/list intacto. Registry no filtra exposición global aún.",
    }
