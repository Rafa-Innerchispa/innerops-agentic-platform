import pytest
from inneros_core_runtime.capability_gateway import (
    register_capability,
    capability_search,
    capability_describe,
    capability_invoke,
    capability_execution,
    resolve_capability_id,
    NETWORK_DEVICE_QUERY_MANIFEST,
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

def test_local_execution_capabilities_discoverable():
    res = capability_search(query="local execution repo", max_results=30)
    assert res["ok"] is True
    ids = {item["capability_id"] for item in res["capabilities"]}
    assert "local_exec.inspect_repo.v1" in ids
    assert "local_exec.write_file.v1" in ids
    assert "local_exec.commit_branch.v1" in ids
    desc = capability_describe("local_exec.write_file.v1")
    assert desc["ok"] is True
    assert desc["capability"]["domain"] == "local_execution"


def test_lep_golden_flow_capabilities_searchable():
    cases = {
        "lock repo": "local_exec.acquire_lock.v1",
        "release lock": "local_exec.release_lock.v1",
        "apply patch": "local_exec.apply_patch.v1",
        "push branch": "local_exec.push_branch.v1",
        "report evidence": "local_exec.report_evidence.v1",
        "draft merge request": "local_gitlab.create_draft_merge_request.v1",
    }
    for query, cap_id in cases.items():
        res = capability_search(query=query, max_results=15)
        assert res["ok"] is True
        found = {item["capability_id"] for item in res["capabilities"]}
        assert cap_id in found, f"query={query!r} got {sorted(found)}"


def test_peer_capabilities_searchable():
    res = capability_search(query="peer observability amd", max_results=15)
    ids = {item["capability_id"] for item in res["capabilities"]}
    assert "peer.observability_snapshot.v1" in ids
    assert "peer.route_check.v1" in ids


def test_legacy_local_exec_alias_describe():
    assert resolve_capability_id("local_exec_write_file") == "local_exec.write_file.v1"
    desc = capability_describe("local_exec_write_file")
    assert desc["ok"] is True
    assert desc["capability"]["capability_id"] == "local_exec.write_file.v1"


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


def test_capability_search_finds_universal_network_audit():
    res = capability_search(query="network audit ports segmentation dhcp", max_results=20)
    assert res["ok"] is True
    ids = {item["capability_id"] for item in res["capabilities"]}
    for cap_id in (
        "network.device.ports.v1",
        "network.l2.topology.v1",
        "network.segmentation.audit.v1",
        "network.dhcp.arp.v1",
    ):
        assert cap_id in ids, f"missing {cap_id} in {sorted(ids)}"


def test_capability_execution():
    res = capability_invoke(
        capability_id="network.device.query.v1",
        parameters={"tenant_id": "bellini", "sections": ["vlans"]}
    )
    exec_id = res["execution_id"]
    status_res = capability_execution(execution_id=exec_id, action="status")
    assert status_res["ok"] is True
    assert status_res["execution"]["status"] == "COMPLETED"
