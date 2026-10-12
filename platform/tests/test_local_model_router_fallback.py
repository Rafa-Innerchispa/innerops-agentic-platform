"""Transport fallback: AMD vLLM unreachable → Intel Ollama (canonical raphiia_openai router)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from raphiia_openai import local_model_router as lmr


class LocalModelRouterFallbackTests(unittest.TestCase):
    @patch.object(lmr, "_intel_ollama_fallback")
    @patch.object(lmr, "_http_ok")
    @patch.object(lmr, "local_model_health")
    def test_amd_vllm_unreachable_uses_ollama_fallback(self, mock_health, mock_ok, mock_fallback):
        mock_health.return_value = {"ok": True}
        mock_ok.side_effect = lambda url: {"ok": "/v1/models" not in url}
        mock_fallback.return_value = {
            "ok": True,
            "runtime": "local_model",
            "response": "ok",
            "fallback_reason": "amd_vllm_unreachable",
        }

        with patch.object(lmr, "classify_task_runtime") as mock_classify:
            mock_classify.return_value = {
                "task_type": "coding",
                "recommended_model": "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ",
                "recommended_provider": "local-amd-5",
                "recommended_backend": "vllm",
                "reason": "test",
            }
            out = lmr.run_local_model(task_type="coding", prompt="ping")

        self.assertTrue(out.get("ok"))
        mock_fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
