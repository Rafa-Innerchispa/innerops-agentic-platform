"""Tests for Contífico Read-Only Query Capability and MCP routing."""

from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import pytest
from inneros_core_runtime import capability_gateway as cg
from inneros_core_runtime import capability_gateway_contifico as cgc
from inneros_core_runtime import capability_router as cr
from inneros_core_runtime import contifico_read_query as crq
from inneros_core_runtime import contifico_analytics as ca
from inneros_core_runtime import mcp_profiles as mp


@pytest.fixture(autouse=True)
def ensure_registered():
    cgc.register_contifico_capabilities()


def test_contifico_query_capability_registered():
    desc = cg.capability_describe("contifico.query.v1")
    assert desc["ok"] is True
    cap = desc["capability"]
    assert cap["capability_id"] == "contifico.query.v1"
    assert cap["mode"] == "read_only"
    assert cap["risk_class"] == "low"
    assert "cartimex" in cap["keywords"]


def test_contifico_legacy_aliases_resolve():
    assert cg.resolve_capability_id("contifico_query") == "contifico.query.v1"
    assert cg.resolve_capability_id("contifico.read.query.v1") == "contifico.query.v1"
    assert cg.resolve_capability_id("search_contifico_documents") == "contifico.query.v1"
    assert cg.resolve_capability_id("search_contifico_transactions") == "contifico.query.v1"
    assert cg.resolve_capability_id("cap.contifico.query") == "contifico.query.v1"

    desc = cg.capability_describe("contifico_query")
    assert desc["ok"] is True
    assert desc["capability"]["capability_id"] == "contifico.query.v1"


def test_capability_search_finds_contifico_query():
    search = cg.capability_search("contifico", max_results=20)
    assert search["ok"] is True
    ids = {row["capability_id"] for row in search["capabilities"]}
    assert "contifico.query.v1" in ids


def test_route_mcp_tools_recommends_contifico_query():
    routed = cr.route_tools(
        title="Auditoria read-only Contifico compras Cartimex y ventas Ryzen PC Doctor",
        body="Cruzar facturas de venta para identificar costos, precios y márgenes",
        granted_scopes=["ralfia:read", "ralfia:agents"],
    )
    assert routed["ok"] is True
    recs = {row["capability_id"] for row in routed["recommended_capabilities"]}
    assert "contifico.query.v1" in recs

    # chatgpt_compact tool count stays strictly bounded at 25 tools
    compact = mp.get_profile("chatgpt_compact")
    assert len(compact["tools"]) == 25


def test_contifico_read_query_real_cartimex_purchases():
    res = crq.contifico_read_query(proveedor="CARTIMEX", tipo="compra", limit=10)
    assert res["ok"] is True
    assert res["count"] > 0
    assert len(res["documentos"]) > 0
    # Every doc should be verified read-only
    first = res["documentos"][0]
    assert first["documento"] is not None
    assert first["fecha_emision"] is not None
    assert res["provenance"]["read_only"] is True


def test_contifico_read_query_cruce_margen():
    res = crq.contifico_read_query(proveedor="CARTIMEX", cruce_margen=True, limit=50)
    assert res["ok"] is True
    assert res["cruce_margen"] is not None
    assert len(res["cruce_margen"]) > 0
    sample_cruce = res["cruce_margen"][0]
    assert "costo_unitario" in sample_cruce
    assert "precio_venta_unitario" in sample_cruce
    assert "margen_bruto_unitario" in sample_cruce
    assert sample_cruce["precio_venta_unitario"] > 0
    assert sample_cruce["costo_unitario"] > 0


def test_capability_invoke_contifico_query():
    res = cg.capability_invoke(
        capability_id="contifico.query.v1",
        parameters={"proveedor": "CARTIMEX", "tipo": "compra", "limit": 5},
        idempotency_key="test-contifico-query-pytest-01",
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    assert res["result"]["count"] > 0
    assert res["result"]["documentos"]


def test_contifico_analytics_query_delegation():
    # Calling contifico_query directly with proveedor delegating to read query
    res = ca.contifico_query(proveedor="CARTIMEX", tipo="compra", limit=5)
    assert res["ok"] is True
    assert res["count"] > 0
