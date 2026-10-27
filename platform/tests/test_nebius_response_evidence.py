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
