"""Two-way InnerOS inference failover, isolated from real host/model endpoints."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from unittest import mock

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "local_model_router.py"
SPEC = importlib.util.spec_from_file_location("candidate_inneros_local_model_router_ha", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)

_REAL_LOG_ROUTE = router._log_route


@pytest.fixture(autouse=True)
def no_real_network_or_model_work(monkeypatch):
    monkeypatch.setattr(router, "local_model_health", lambda: {"ok": True})
    monkeypatch.setattr(router, "_log_route", lambda **_: {"ok": True, "log_id": "fixture"})
    monkeypatch.setattr(router, "_ollama_chat", lambda **_: {"ok": False, "error": "stub_only"})
    monkeypatch.setattr(router, "_vllm_chat", lambda **_: {"ok": False, "error": "stub_only"})
    monkeypatch.setattr(router, "_http_json", lambda *_args, **_kw: {"ok": False, "error": "offline"})
    monkeypatch.setattr(router, "_http_ok", lambda *_args, **_kw: {"ok": False})
    monkeypatch.setattr(router, "_pick_installed_ollama_model", lambda *_args, **_kw: None)


def classify(provider, backend):
    return {
        "task_type": "summary",
        "recommended_model": "preferred-test-model",
        "recommended_provider": provider,
        "recommended_backend": backend,
        "reason": "fixture_model_routing",
    }


def test_intel_failure_fails_over_to_served_amd_vllm(monkeypatch):
    monkeypatch.setattr(router, "classify_task_runtime", lambda *_args, **_kw: classify("local-intel-4", "ollama"))
    monkeypatch.setattr(router, "_http_json", lambda url, **_kw: {
        "ok": True, "data": {"data": [{"id": "served-amd-qwen"}]}
    } if url.endswith("/v1/models") else {"ok": False})
    issued = []
    monkeypatch.setattr(router, "_vllm_chat", lambda **kw: issued.append(kw) or {
        "ok": True, "response": "Respuesta AMD", "model": kw["model"],
    })
    result = router.run_local_model(task_type="summary", prompt="resumen de prueba")
    assert result["ok"] is True
    assert result["response"] == "Respuesta AMD"
    assert result["selected_node"] == "amd"
    assert result["provider_id"] == "local-amd-5"
    assert result["selected_model"] == "served-amd-qwen"
    assert issued[0]["model"] == "served-amd-qwen"
    assert result["fallback_reason"] == "intel_ollama_unreachable"
    assert result["external_needed"] is False
    assert result["fallback_silent"] is False


def test_amd_failure_uses_intel_ollama_without_cloud(monkeypatch):
    monkeypatch.setattr(router, "classify_task_runtime", lambda *_args, **_kw: classify("local-amd-5", "vllm"))
    monkeypatch.setattr(router, "_pick_installed_ollama_model", lambda *_args, **_kw: "qwen-intel")
    monkeypatch.setattr(router, "_ollama_chat", lambda **_kw: {
        "ok": True, "data": {"message": {"content": "Respuesta Intel"}}
    })
    result = router.run_local_model(task_type="summary", prompt="test")
    assert result["ok"] is True
    assert result["selected_node"] == "intel"
    assert result["response"] == "Respuesta Intel"
    assert result["provider_id"] == "local-intel-4"
    assert result["external_needed"] is False


def test_amd_self_recovers_with_local_ollama_if_intel_and_vllm_unavailable(monkeypatch):
    monkeypatch.setattr(router, "IS_AMD_NODE", True)
    monkeypatch.setattr(router, "classify_task_runtime", lambda *_args, **_kw: classify("local-intel-4", "ollama"))
    monkeypatch.setattr(router, "_pick_installed_ollama_model", lambda *_args, **_kw: "tiny-amd")
    monkeypatch.setattr(router, "_ollama_chat", lambda **_kw: {
        "ok": True, "data": {"message": {"content": "AMD liviano"}}
    })
    result = router.run_local_model(task_type="summary", prompt="test")
    assert result["ok"] is True
    assert result["selected_node"] == "amd"
    assert result["selected_model"] == "tiny-amd"
    assert result["external_needed"] is False


def test_all_model_routes_down_fail_closed_with_no_external_spend(monkeypatch):
    monkeypatch.setattr(router, "IS_AMD_NODE", True)
    monkeypatch.setattr(router, "classify_task_runtime", lambda *_args, **_kw: classify("local-intel-4", "ollama"))
    result = router.run_local_model(task_type="summary", prompt="test")
    assert result["ok"] is False
    assert result["error"] == "all_local_model_routes_unavailable"
    assert result["external_needed"] is False
    assert result["fallback_silent"] is False
    assert len(result["failures"]) == 2


def test_local_intel_ollama_resolves_loopback_on_intel(monkeypatch):
    monkeypatch.setattr(router, "IS_INTEL_NODE", True)
    with mock.patch.dict(os.environ, {"INNEROS_INTEL_OLLAMA_URL": ""}):
        assert router._ollama_url_for_provider("local-intel-4") == "http://127.0.0.1:11434"


def test_intel_generation_failure_can_retry_amd(monkeypatch):
    monkeypatch.setattr(router, "classify_task_runtime", lambda *_args, **_kw: classify("local-intel-4", "ollama"))
    monkeypatch.setattr(router, "_http_ok", lambda *_args, **_kw: {"ok": True})
    monkeypatch.setattr(router, "_http_json", lambda url, **_kw: (
        {"ok": True, "data": {"data": [{"id": "amd-served"}]}}
        if url.endswith("/v1/models") else {"ok": False, "error": "intel_generate_failed"}
    ))
    monkeypatch.setattr(router, "_vllm_chat", lambda **_kw: {
        "ok": True, "response": "Recuperado por AMD"
    })
    result = router.run_local_model(task_type="summary", prompt="test")
    assert result["ok"] is True
    assert result["selected_node"] == "amd"
    assert result["fallback_reason"] == "intel_ollama_generation_failed"


def test_unavailable_mongo_defaults_does_not_block_stateless_inference(monkeypatch):
    monkeypatch.setattr(router.mongo_store, "get_coordination_state", lambda *_: (_ for _ in ()).throw(ConnectionError("down")))
    assert router._router_default("summary") is None


def test_failed_audit_is_explicitly_degraded_not_hidden(monkeypatch):
    monkeypatch.setattr(router, "IS_AMD_NODE", True)
    monkeypatch.setattr(router, "_pick_installed_ollama_model", lambda *_args, **_kw: "amd-model")
    monkeypatch.setattr(router, "_ollama_chat", lambda **_kw: {
        "ok": True, "data": {"message": {"content": "Solo inferencia"}}
    })
    monkeypatch.setattr(router, "_log_route", lambda **_kw: (_ for _ in ()).throw(ConnectionError("audit down")))
    result = router._amd_local_ollama_fallback(
        task_type="summary", prompt="test", system_prompt="test",
        max_tokens=5, temperature=0.2, fallback_reason="intel_down",
    )
    assert result["ok"] is True
    assert result["audit_degraded"] is True
    assert result["routing_log"]["terminal_evidence"] is False
    assert result["external_needed"] is False


def test_intel_can_answer_statelessly_when_mongo_audit_is_down(monkeypatch):
    monkeypatch.setattr(router, "IS_INTEL_NODE", True)
    monkeypatch.setattr(router, "classify_task_runtime", lambda *_args, **_kw: classify("local-intel-4", "ollama"))
    monkeypatch.setattr(router, "_http_ok", lambda *_args, **_kw: {"ok": True})
    monkeypatch.setattr(router, "_http_json", lambda url, **_kw: {
        "ok": True, "data": {"message": {"content": "Intel sin Mongo"}}
    } if url.endswith("/api/chat") else {"ok": False})
    monkeypatch.setattr(router, "_log_route", _REAL_LOG_ROUTE)
    monkeypatch.setattr(router.mongo_store, "get_db", lambda: (_ for _ in ()).throw(ConnectionError("offline")))
    result = router.run_local_model(task_type="summary", prompt="health degraded", model="qwen-small")
    assert result["ok"] is True
    assert result["response"] == "Intel sin Mongo"
    assert result["audit_degraded"] is True
    assert result["routing_log"]["terminal_evidence"] is False
    assert result["selected_node"] == "intel"


def test_intel_fallback_can_answer_when_mongo_audit_is_down(monkeypatch):
    monkeypatch.setattr(router, "_pick_installed_ollama_model", lambda *_args, **_kw: "qwen-intel")
    monkeypatch.setattr(router, "_ollama_chat", lambda **_kw: {
        "ok": True, "data": {"message": {"content": "Intel recuperado sin Mongo"}}
    })
    monkeypatch.setattr(router, "_log_route", _REAL_LOG_ROUTE)
    monkeypatch.setattr(router.mongo_store, "get_db", lambda: (_ for _ in ()).throw(ConnectionError("offline")))
    result = router._intel_ollama_fallback(
        task_type="summary", prompt="test", system_prompt="test",
        max_tokens=32, temperature=0.2, fallback_reason="amd_down"
    )
    assert result["ok"] is True
    assert result["audit_degraded"] is True
    assert result["routing_log"]["terminal_evidence"] is False
