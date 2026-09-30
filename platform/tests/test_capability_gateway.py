import pytest
from inneros_core_runtime.capability_gateway import (
    register_capability,
    capability_search,
    capability_describe,
    capability_invoke,
    capability_execution,
    NETWORK_DEVICE_QUERY_MANIFEST
)

def test_capability_search():
    res = capability_search(query="network")
    assert res["ok"] is True
    assert len(res["capabilities"]) >= 1
    assert res["capabilities"][0]["capability_id"] == "network.device.query.v1"

def test_capability_describe():
    res = capability_describe("network.device.query.v1")
    assert res["ok"] is True
    assert res["capability"]["title"] == "Network Device Unified Query Capability"
    assert res["capability"]["mode"] == "read_only"

def test_capability_invoke_read_only():
    res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters={"tenant_id": "bellini", "sections": ["health", "inventory"]},
        idempotency_key="test-idem-pytest-01"
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    assert "health" in res["result"]["data"]
    assert "inventory" in res["result"]["data"]

def test_capability_invoke_mutation_guard():
    # Register mutation capability
    mut_manifest = {
        "capability_id": "test.mutation.sample.v1",
        "version": "1.0.0",
        "title": "Sample Mutation Capability",
        "domain": "test",
        "mode": "mutation",
        "risk_class": "high"
    }
    register_capability(mut_manifest, lambda p, c: {"mutated": True})
    
    # When enforce_read_only is active, it must fail-closed
    res = capability_invoke(
        capability_id="test.mutation.sample.v1",
        parameters={},
        context={"enforce_read_only": True}
    )
    assert res["ok"] is False
    assert res["error"] == "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE"

def test_capability_execution():
    res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters={"tenant_id": "bellini", "sections": ["vlans"]}
    )
    exec_id = res["execution_id"]
    status_res = capability_execution(execution_id=exec_id, action="status")
    assert status_res["ok"] is True
    assert status_res["execution"]["status"] == "COMPLETED"
