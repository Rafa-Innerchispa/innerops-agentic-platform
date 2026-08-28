from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import voice_gateway


class VoiceModelReconciliationTests(unittest.TestCase):
    def test_resolve_uses_installed_fallback(self):
        with mock.patch.object(voice_gateway, "_installed_ollama_models", return_value={"qwen2.5:7b-instruct-q4_K_M"}):
            resolved = voice_gateway._resolve_configured_voice_model("qwen2.5:32b-instruct-q4_K_M")
        self.assertEqual(resolved, "qwen2.5:7b-instruct-q4_K_M")

    def test_resolve_raises_when_missing(self):
        with mock.patch.object(voice_gateway, "_installed_ollama_models", return_value={"llama3.2:3b"}):
            with self.assertRaises(ValueError):
                voice_gateway._resolve_configured_voice_model(
                    "qwen2.5:32b-instruct-q4_K_M",
                    fallbacks=("missing-model",),
                )


if __name__ == "__main__":
    unittest.main()
