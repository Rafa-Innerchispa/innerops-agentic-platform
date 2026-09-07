from __future__ import annotations

from unittest import mock

from inneros_core_runtime import local_model_router as router


def _completion(content: str = '{"ok":true}') -> dict:
    return {
        "ok": True,
        "data": {
            "choices": [
                {
                    "message": {
                        "content": content,
                    }
                }
            ]
        },
    }


def test_vllm_chat_requests_json_mode_for_json_prompts() -> None:
    calls: list[dict] = []

    def fake_http_json(_url, *, body, **_kwargs):
        calls.append(body)
        return _completion()

    with mock.patch.object(router, "_http_json", side_effect=fake_http_json):
        result = router._vllm_chat(
            model="model",
            prompt="Return ONLY valid JSON with this shape: {}",
            system_prompt="system",
            max_tokens=64,
            temperature=0.0,
            endpoint="http://127.0.0.1:18000",
        )

    assert result["ok"] is True
    assert result["json_mode_requested"] is True
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_vllm_chat_retries_without_json_mode_when_backend_rejects_it() -> None:
    calls: list[dict] = []

    def fake_http_json(_url, *, body, **_kwargs):
        calls.append(body)
        if len(calls) == 1:
            return {"ok": False, "status": 400, "error": "bad request"}
        return _completion()

    with mock.patch.object(router, "_http_json", side_effect=fake_http_json):
        result = router._vllm_chat(
            model="model",
            prompt="Return JSON only: {}",
            system_prompt="system",
            max_tokens=64,
            temperature=0.0,
            endpoint="http://127.0.0.1:18000",
        )

    assert result["ok"] is True
    assert result["retried_without_json_mode"] is True
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]
