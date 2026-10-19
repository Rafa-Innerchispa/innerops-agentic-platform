import pytest
from inneros_core_runtime.capability_gateway import (
    register_capability,
    capability_search,
    capability_describe,
    capability_invoke,
    capability_execution,
    NETWORK_DEVICE_QUERY_MANIFEST,
)

def test_capability_search():
    res = capability_search(query="network")
    assert res["ok"] is True
    assert len(res["capabilities"]) >= 1
    assert any(cap["capability_id"] == "network.device.query.v1" for cap in res["capabilities"])

def test_capability_describe():
    res = capability_describe("network.device.query.v1")
    assert res["ok"] is True
    assert res["capability"]["title"] == "Network Device Unified Query Capability"
    assert res["capability"]["mode"] == "read_only"

def test_capability_invoke_read_only(monkeypatch):
    monkeypatch.setattr(
        "inneros_core_runtime.device_fabric.device_fabric_health",
        lambda site_id="": {"ok": True, "site_filter": site_id, "providers": []},
    )
    monkeypatch.setattr(
        "inneros_core_runtime.device_fabric.device_fabric_inventory",
        lambda client_id="", site_id="", live=False: {
            "ok": True,
            "provider": "grandstream_gwn",
            "inventory": [{"device_ref": "192.168.3.1"}],
        },
    )
    res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters={
            "tenant_id": "bellini",
            "site_id": "bellini-i-ii",
            "sections": ["health", "inventory"],
        },
        idempotency_key="test-idem-pytest-01",
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"
    assert res["result"]["provenance"]["source"] == "device_fabric"
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

def test_coordination_messaging_list_capability(monkeypatch):
    monkeypatch.setattr(
        "raphiia_openai.memory.agent_messages.list_agent_messages",
        lambda **kwargs: {"ok": True, "count": 0, "messages": [], "role": kwargs.get("role")},
    )
    found = capability_search(query="coordination messaging")
    assert any(item["capability_id"] == "coordination.messaging.list.v1" for item in found["capabilities"])
    res = capability_invoke(
        capability_id="coordination.messaging.list.v1",
        parameters={"agent": "chatgpt", "limit": 5},
    )
    assert res["ok"] is True
    assert res["status"] == "COMPLETED"


def test_capability_execution():
    res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters={"tenant_id": "bellini", "sections": ["vlans"]}
    )
    exec_id = res["execution_id"]
    status_res = capability_execution(execution_id=exec_id, action="status")
    assert status_res["ok"] is True
    assert status_res["execution"]["status"] == "COMPLETED"



def test_local_exec_authorize_repo_capability_is_registered():
    found = capability_search(query="authorize owner approved repo", domain="local_execution")
    assert found["ok"] is True
    assert any(
        item["capability_id"] == "local_exec.authorize_repo.v1"
        for item in found["capabilities"]
    )

    described = capability_describe("local_exec.authorize_repo.v1")
    assert described["ok"] is True
    manifest = described["capability"]
    assert manifest["mode"] == "mutation"
    assert manifest["risk_class"] == "high"
    assert "approval_id" in manifest["parameters_schema"]["required"]


def test_local_exec_authorize_repo_respects_read_only_guard():
    result = capability_invoke(
        capability_id="local_exec.authorize_repo.v1",
        parameters={
            "repo": "Rafa-Innerchispa/example-repo",
            "approval_id": "owner-approved-test",
            "actor": "chatgpt",
            "task_id": "ops_test",
            "correlation_id": "test-correlation",
            "dry_run": True,
        },
        context={"enforce_read_only": True},
    )
    assert result["ok"] is False
    assert result["error"] == "MUTATION_FORBIDDEN_IN_READ_ONLY_MODE"
