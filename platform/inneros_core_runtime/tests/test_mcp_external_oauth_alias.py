"""MCP externo: URLs OAuth sin duplicar, alias cloud y schemas garantizados."""
import pytest

from inneros_core_runtime import capability_gateway as gw


def test_resolve_legacy_aliases():
    assert gw.resolve_capability_id("vultr_inference_embeddings") == "cloud.vultr.inference.embeddings.v1"
    assert gw.resolve_capability_id("vultr_status") == "cloud.provider.status.v1"
    assert gw.resolve_capability_id("vultr_inference_chat") == "cloud.vultr.inference.chat.v1"
    assert gw.resolve_capability_id("vultr_inference_rerank") == "cloud.vultr.inference.rerank.v1"


def test_resolve_version_fallback():
    assert gw.resolve_capability_id("cloud.provider.status") == "cloud.provider.status.v1"
    assert gw.resolve_capability_id("no_existe_xyz") == "no_existe_xyz"


def test_describe_always_has_schema():
    gw.register_capability({"capability_id": "test.sin_schema.v1", "version": "1.0.0"})
    try:
        out = gw.capability_describe("test.sin_schema.v1")
    finally:
        gw._CAPABILITY_REGISTRY.pop("test.sin_schema.v1", None)
    assert out["ok"] is True
    assert out["capability"]["parameters_schema"] == {"type": "object", "properties": {}}


def test_router_public_url_no_duplica():
    pytest.importorskip("fastapi")
    import inneros_core_runtime.mcp_server as ms

    try:
        orig = ms.MCP_PUBLIC_URL
        cases = [
            ("https://mcp.pcdoctor.ai/router/mcp", "https://mcp.pcdoctor.ai/router/mcp"),
            ("https://mcp.pcdoctor.ai/router", "https://mcp.pcdoctor.ai/router/mcp"),
            ("https://mcp.pcdoctor.ai", "https://mcp.pcdoctor.ai/router/mcp"),
        ]
        for base, expected in cases:
            ms.MCP_PUBLIC_URL = base
            assert ms._router_mcp_public_url() == expected, base
    finally:
        ms.MCP_PUBLIC_URL = orig


def test_auth_tiene_landing():
    pytest.importorskip("fastapi")
    from inneros_core_runtime import auth_server

    paths = {getattr(r, "path", "") for r in auth_server.app.routes}
    assert "/" in paths
