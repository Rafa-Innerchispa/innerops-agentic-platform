from unittest.mock import patch

from inneros_core_runtime import judge_multimodel_e2e as jm


def fake_http(url, timeout=5.0):
    if "8000" in url:
        return {"ok": True, "latency_ms": 12, "data": {"data": [{"id": "local-vllm"}]}}
    return {"ok": True, "latency_ms": 10, "data": {"models": [{"name": "local-ollama"}]}}


def test_route_status_marks_live_and_not_ready_without_hardcoded_pass():
    def smoke(lane_id, **kwargs):
        if lane_id == "google-gemma-bounded-review":
            return {"ok": False, "model": "gemma", "live_mode": "UNAVAILABLE", "error": "not_found"}
        return {"ok": True, "model": "gemini-3.5-flash", "live_mode": "LIVE", "text_preview": "ok"}

    def post(url, body, timeout=20.0):
        return {"ok": True, "latency_ms": 18, "data": {"choices": [{"message": {"content": "{\"intent\":\"tool\",\"route\":\"call_tool\"}"}}]}}

    with patch.object(jm, "_http_json", side_effect=fake_http), patch.object(jm, "_http_post_json", side_effect=post), patch.object(jm.google_extra_models, "smoke_lane", side_effect=smoke):
        result = jm.route_status(project_id="innerops-agentic-platform", live_probe=True, allow_live_google=True)

    assert result["overall_status"] == "LIVE"
    routes = result["routes"]
    assert routes["local_amd_vllm"]["status"] == "LIVE"
    assert routes["local_intel_ollama"]["status"] == "LIVE"
    assert routes["gemini_35_plus"]["status"] == "LIVE"
    assert routes["function_gemma"]["status"] == "LIVE"
    assert routes["function_gemma"]["provider"] == "local-amd"
    assert routes["google_gemma_vertex"]["status"] == "NOT_READY"
    assert routes["mi325x_cloud_burst"]["detail"]["approval_required"] is True
    assert routes["auto"]["detail"]["selected_route"] == "function_gemma"


def test_e2e_writes_are_gated_and_dispatch_optional(tmp_path, monkeypatch):
    monkeypatch.setattr(jm, "EVIDENCE_DIR", tmp_path)
    with patch.object(jm, "route_status", return_value={"ok": True, "routes": {"auto": {"status": "LIVE", "provider": "local"}}}):
        result = jm.run_e2e(correlation_id="corr", allow_live_google=False, allow_writes=False, dispatch_a2a=False)

    assert result["steps"]["firestore"]["status"] == "PARTIAL"
    assert result["steps"]["pubsub"]["status"] == "PARTIAL"
    assert result["steps"]["a2a_dispatch"]["status"] == "PARTIAL"
    assert result["cost_guard"]["mi325x_created"] is False
    assert result["evidence_path"].endswith(".json")


def test_function_gemma_uses_local_amd_when_vertex_is_404():
    posts = []

    def smoke(lane_id, **kwargs):
        return {"ok": False, "model": "gemma-3-27b-it", "live_mode": "UNAVAILABLE", "error": "404 endpoint not found"}

    def post(url, body, timeout=20.0):
        posts.append((url, body))
        return {"ok": True, "latency_ms": 18, "data": {"choices": [{"message": {"content": "{\"intent\":\"pdf_evidence\",\"route\":\"call_tool\"}"}}]}}

    with patch.object(jm, "_http_json", side_effect=fake_http), patch.object(jm, "_http_post_json", side_effect=post), patch.object(jm.google_extra_models, "smoke_lane", side_effect=smoke):
        result = jm.route_status(project_id="innerops-agentic-platform", live_probe=True, allow_live_google=True)

    assert posts
    routes = result["routes"]
    assert routes["google_gemma_vertex"]["status"] == "NOT_READY"
    assert routes["function_gemma"]["status"] == "LIVE"
    assert routes["function_gemma"]["runtime"] == "local_vllm_function_intent"
    assert routes["function_gemma"]["detail"]["replaces_blocking_vertex_dependency"] is True
