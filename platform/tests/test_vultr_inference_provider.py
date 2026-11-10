import pytest
from inneros_core_runtime import vultr_inference_provider, resource_fabric, capability_gateway

def test_vultr_inference_status():
    st = vultr_inference_provider.status()
    assert st["ok"] is True
    assert st["provider_id"] == "vultr-inference"
    assert st["configured"] is True
    assert "deepseek" in st["default_models"]["chat"]
    assert "qwen3-embedding" in st["default_models"]["embeddings"]
    assert "bge-reranker" in st["default_models"]["rerank"]

def test_vultr_inference_models():
    res = vultr_inference_provider.list_models()
    assert res["ok"] is True
    assert res["count"] >= 30
    assert "deepseek-v4.1-flash-1017" in res["models"]
    assert "qwen3-embedding-4b" in res["models"]
    assert "bge-reranker-v2-m3" in res["models"]

def test_vultr_inference_documents():
    rp = vultr_inference_provider.resource_provider_document()
    assert rp["provider_id"] == "vultr-inference"
    assert "coding" in rp["capabilities"]
    assert "embeddings" in rp["capabilities"]
    assert "rerank" in rp["capabilities"]

    mp = vultr_inference_provider.model_provider_document()
    assert mp["model_provider"] == "vultr-inference"
    assert mp["priority"] == 50
    assert mp["cost_policy"] == "explicit_burst_only"

def test_resource_fabric_routing():
    # Local default
    r_local = resource_fabric.route_resource_request("proj_test", "coding", prefer_cloud=False)
    assert r_local["ok"] is True
    assert r_local["selected"]["model"]["model_provider"] == "local-amd"

    # Cloud burst
    r_cloud = resource_fabric.route_resource_request("proj_test", "embeddings", prefer_cloud=True)
    assert r_cloud["ok"] is True
    assert r_cloud["selected"]["model"]["model_provider"] == "vultr-inference"

def test_capability_gateway_search():
    res = capability_gateway.capability_search("vultr")
    assert res["total_matches"] >= 10
    cap_ids = [c["capability_id"] for c in res["capabilities"]]
    assert "cloud.vultr.inference.chat.v1" in cap_ids
    assert "cloud.vultr.inference.embeddings.v1" in cap_ids
    assert "cloud.vultr.inference.rerank.v1" in cap_ids
