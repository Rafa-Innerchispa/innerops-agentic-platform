"""P0 offline tests: actual candidate AMD/Intel inference routing, never live runtime."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CANDIDATE = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "local_model_router.py"
SPEC = importlib.util.spec_from_file_location("candidate_ha_local_model_router", CANDIDATE)
assert SPEC and SPEC.loader
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)


@pytest.fixture
def intel_down(monkeypatch):
    audit = {"probes": [], "generations": [], "logs": []}
    monkeypatch.setattr(router, "classify_task_runtime", lambda *args, **kw: {
        "task_type": "coding", "recommended_model": "qwen2.5-coder:7b",
        "recommended_provider": "local-intel-4", "recommended_backend": "ollama",
        "reason": "local",
    })
    monkeypatch.setattr(router, "local_model_health", lambda: {"ok": True})
    monkeypatch.setattr(router, "_http_ok", lambda *args, **kw: {"ok": False})
    monkeypatch.setattr(router, "_ollama_url_for_provider", lambda provider: "http://127.0.0.1:11434")
    monkeypatch.setattr(router, "_vllm_url_for_provider", lambda provider: "http://192.168.1.5:8001")
    monkeypatch.setattr(router, "_log_route", lambda **kw: audit["logs"].append(kw) or kw)
    def http(url, **kw):
        audit["probes"].append(url)
        assert url == "http://192.168.1.5:8001/v1/models"
        return {"ok": True, "data": {"data": [{"id": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"}]}}
    monkeypatch.setattr(router, "_http_json", http)
    def vllm(**kw):
        audit["generations"].append(kw)
        return {"ok": True, "response": "AMD responded", "model": kw["model"]}
    monkeypatch.setattr(router, "_vllm_chat", vllm)
    return audit


def test_intel_down_uses_amd_and_reports_degraded_model(intel_down):
    result = router.run_local_model(task_type="coding", prompt="patch this")
    assert result["ok"] is True
    assert result["selected_node"] == "amd"
    assert result["provider_id"] == "local-amd-5"
    assert result["fallback_reason"] == "intel_ollama_unreachable"
    assert result["quality_degraded"] is True
    assert result["external_needed"] is False
    assert result["fallback_silent"] is False
    assert len(intel_down["generations"]) == 1
    assert intellocal(intel_down["probes"])


def intellocal(urls):
    return all(item.startswith("http://192.168.1.5:8001/") for item in urls)


@pytest.mark.parametrize("mode,reason", [
    ("failed", "intel_ollama_generation_failed"),
    ("empty", "intel_ollama_empty_response"),
])
def test_intel_generation_failure_uses_amd(intel_down, monkeypatch, mode, reason):
    monkeypatch.setattr(router, "_http_ok", lambda *args, **kw: {"ok": True})
    def http(url, **kw):
        if url.endswith("/api/chat"):
            return {"ok": False, "error": "offline"} if mode == "failed" else {"ok": True, "data": {"message": {"content": ""}}}
        return {"ok": True, "data": {"data": [{"id": "Coder-AMD"}]}}
    monkeypatch.setattr(router, "_http_json", http)
    result = router.run_local_model(task_type="coding", prompt="patch this")
    assert result["ok"] is True
    assert result["fallback_reason"] == reason


def test_explicit_pinned_intel_model_must_not_be_swapped(intel_down):
    result = router.run_local_model(task_type="coding", prompt="patch", model="intel-only")
    assert result["ok"] is False
    assert result["fallback_error"] == "amd_vllm_exact_model_unavailable"
    assert result["external_needed"] is False
    assert not intel_down["generations"]


def test_no_external_failover_endpoint(intel_down, monkeypatch):
    monkeypatch.setattr(router, "_vllm_url_for_provider", lambda provider: "https://api.example.com")
    result = router.run_local_model(task_type="coding", prompt="patch")
    assert result["ok"] is False
    assert result["fallback_error"] == "fallback_endpoint_not_local"
    assert not intel_down["probes"]


def test_amd_without_served_models_is_not_success(intel_down, monkeypatch):
    monkeypatch.setattr(router, "_http_json", lambda *args, **kw: {"ok": True, "data": {"data": []}})
    result = router.run_local_model(task_type="coding", prompt="patch")
    assert result["ok"] is False
    assert result["fallback_error"] == "amd_vllm_no_text_models"


def test_explicit_amd_model_is_not_silently_replaced_on_intel(monkeypatch):
    monkeypatch.setattr(router, "classify_task_runtime", lambda *args, **kw: {
        "task_type": "coding", "recommended_model": "amd-coder",
        "recommended_provider": "local-amd-5", "recommended_backend": "vllm", "reason": "local",
    })
    monkeypatch.setattr(router, "local_model_health", lambda: {"ok": True})
    monkeypatch.setattr(router, "_http_ok", lambda *args, **kw: {"ok": False})
    monkeypatch.setattr(router, "_ollama_url_for_provider", lambda provider: "http://192.168.1.4:11434")
    monkeypatch.setattr(router, "_http_json", lambda url, **kw: {"ok": True, "data": {"models": [{"name": "qwen2.5-coder:7b"}]}})
    result = router.run_local_model(task_type="coding", prompt="patch", model="amd-coder")
    assert result["ok"] is False
    assert result["error"] == "intel_ollama_exact_model_unavailable"


@pytest.mark.parametrize("url,allowed", [
    ("http://192.168.1.5:8001", True),
    ("http://127.0.0.1:8000", True),
    ("http://100.72.153.124:8000", True),
    ("http://8.8.8.8:8000", False),
    ("https://192.168.1.5:8000", False),
    ("http://evil.example:8000", False),
    ("http://user:pass@192.168.1.5:8000", False),
])
def test_private_endpoint_policy(url, allowed):
    assert router._local_private_endpoint(url) is allowed
