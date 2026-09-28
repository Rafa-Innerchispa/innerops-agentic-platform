"""Local-only failover regression tests with no network or database writes."""
import importlib.util
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inneros_core_runtime import local_model_router as router

@pytest.fixture
def harness(monkeypatch):
    calls, logs = [], []
    monkeypatch.setattr(router, "classify_task_runtime", lambda *a, **kw: {
        "task_type": "coding", "recommended_model": "amd-model",
        "recommended_provider": "local-amd-5", "recommended_backend": "vllm", "reason": "local"})
    monkeypatch.setattr(router, "local_model_health", lambda: {"ok": True})
    monkeypatch.setattr(router, "_http_ok", lambda *a, **kw: {"ok": False})
    monkeypatch.setattr(router, "_ollama_url_for_provider", lambda p: "http://127.0.0.1:11434")
    monkeypatch.setattr(router, "_log_route", lambda **kw: logs.append(kw) or kw)
    def http(url, **kw):
        calls.append((url, kw))
        if url.endswith("/api/tags"):
            return {"ok": True, "data": {"models": [{"name": "qwen2.5-coder:7b"}]}}
        assert url == "http://127.0.0.1:11434/api/chat"
        assert kw["body"]["model"] == "qwen2.5-coder:7b"
        return {"ok": True, "data": {"message": {"content": "PATCH"}, "model": "qwen2.5-coder:7b"}}
    monkeypatch.setattr(router, "_http_json", http)
    return calls, logs

def test_health_failure_uses_installed_local_model(harness):
    calls, logs = harness
    result = router.run_local_model(task_type="coding", prompt="code", max_tokens=100)
    assert result["ok"] and result["response"] == "PATCH"
    assert result["provider_id"] == "local-intel-4"
    assert result["selected_node"] == "intel"
    assert result["selected_model"] == "qwen2.5-coder:7b"
    assert result["fallback_reason"].startswith("amd_vllm_unreachable")
    assert not result["external_needed"]
    assert len(calls) == 2 and not logs[-1]["external_needed"]

def test_generation_failure_uses_local_fallback(harness, monkeypatch):
    monkeypatch.setattr(router, "_http_ok", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(router, "_vllm_chat", lambda **kw: {"ok": False, "error": "connection reset"})
    result = router.run_local_model(task_type="coding", prompt="code")
    assert result["ok"] and result["fallback_reason"] == "amd_vllm_generation_failed"

def test_healthy_amd_is_preserved(harness, monkeypatch):
    monkeypatch.setattr(router, "_http_ok", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(router, "_vllm_chat", lambda **kw: {"ok": True, "response": "AMD"})
    result = router.run_local_model(task_type="coding", prompt="code")
    assert result["response"] == "AMD" and result["selected_node"] == "amd"
    assert not harness[0]

@pytest.mark.parametrize("failure", ["offline", "missing", "empty", "generation"])
def test_no_external_when_ollama_unusable(harness, monkeypatch, failure):
    calls = []
    def http(url, **kw):
        calls.append(url)
        if url.endswith("/api/tags"):
            if failure == "offline":
                return {"ok": False, "error": "offline"}
            return {"ok": True, "data": {"models": [] if failure == "missing" else [{"model": "qwen2.5-coder:7b"}]}}
        assert url.startswith("http://127.0.0.1:11434/")
        return {"ok": failure != "generation", "data": {"message": {"content": ""}}}
    monkeypatch.setattr(router, "_http_json", http)
    result = router.run_local_model(task_type="coding", prompt="code")
    assert not result["ok"] and not result["external_needed"]
    assert all(url.startswith("http://127.0.0.1:11434/") for url in calls)
    assert len(calls) == (1 if failure in ("offline", "missing") else 2)
