"""Offline regressions for empty/truncated paid inference responses."""
import json
from unittest import mock
import pytest
from inneros_core_runtime.nebius_nvidia_reasoning import NebiusNvidiaReasoning

@pytest.mark.parametrize("content,finish,status", [
    (None, "stop", "EMPTY_DIAGNOSTIC_CONTENT"),
    (None, "length", "OUTPUT_TOKEN_LIMIT_REACHED"),
    ('{"root_cause":', "length", "OUTPUT_TOKEN_LIMIT_REACHED"),
    ("not-json", "stop", "INVALID_DIAGNOSTIC_JSON"),
    ("[]", "stop", "INVALID_DIAGNOSTIC_OBJECT"),
])
def test_invalid_response_retains_receipt_without_claiming_real_diagnosis(content, finish, status):
    response = {"id":"receipt-offline-test", "usage":{"completion_tokens":512},
                "choices":[{"finish_reason":finish, "message":{"content":content}}]}
    with mock.patch("urllib.request.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
        result = NebiusNvidiaReasoning(api_key="offline-test", model="nvidia/test").diagnose({"offline":True})
    assert request.call_count == 1  # Never automatically retry a billable request.
    assert result["inference_mode"] == "LOCAL_HEURISTIC"
    assert result["provider_receipt"]["evidence_mode"] == "BLOCKED"
    assert result["provider_receipt"]["status"] == status
    assert result["provider_receipt"]["response_id"] == "receipt-offline-test"
    assert result["provider_receipt"]["usage"]["completion_tokens"] == 512
    assert "offline-test" not in json.dumps(result) .replace("receipt-offline-test", "")


@pytest.mark.parametrize("limit", [0, 2049, True, "2048"])
def test_output_budget_rejects_invalid_limits(limit):
    with pytest.raises(ValueError):
        NebiusNvidiaReasoning(max_output_tokens=limit)

def test_explicit_output_budget_is_sent_without_automatic_retries():
    response = {"id":"offline-budget", "usage":{},
                "choices":[{"finish_reason":"stop", "message":{"content":"{}"}}]}
    with mock.patch("urllib.request.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
        result = NebiusNvidiaReasoning(api_key="offline", model="nvidia/test", max_output_tokens=2048).diagnose({})
    assert json.loads(request.call_args.args[0].data)["max_tokens"] == 2048
    assert request.call_count == 1
    assert result["provider_receipt"]["evidence_mode"] == "REAL"
