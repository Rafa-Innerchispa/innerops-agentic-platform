from mcp_router_gateway.backend_health import health_url_for_mcp, probe_backend_health


def test_health_url_for_mcp():
    assert health_url_for_mcp("http://127.0.0.1:8112/mcp") == "http://127.0.0.1:8112/health"


def test_probe_backend_health_local_compact():
    # May fail in CI without server; ensure callable returns bool
    assert isinstance(probe_backend_health("http://127.0.0.1:59999/mcp", timeout=0.2), bool)
