import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import gemini_runtime as gr
from inneros_core_runtime import gcp_memory_bank as gmb

class FakeInteraction:
    def __init__(self, interaction_id="ix-1", output_text="ok", steps=None):
        self.id = interaction_id
        self.output_text = output_text
        self.steps = steps or []

class FakeGenAIClient:
    def __init__(self):
        self.interactions = MagicMock()
        self.interactions.create.return_value = FakeInteraction()

class GovernedGeminiTests(unittest.TestCase):
    def setUp(self):
        self.config = gr.GeminiRuntimeConfig(project_id="test-proj")
        self.fake = FakeGenAIClient()
        self.client = gr.GeminiInteractionsClient(config=self.config, client=self.fake)
        self.runtime = gr.InnerOSGeminiRuntime(client=self.client)

    @patch("inneros_core_runtime.gemini_runtime._write_cloud_log")
    @patch("inneros_core_runtime.gemini_runtime._sanitize_with_model_armor")
    @patch("inneros_core_runtime.gemini_runtime._save_evidence_to_firestore")
    @patch("inneros_core_runtime.gemini_runtime._publish_event_to_pubsub")
    @patch("inneros_core_runtime.gcp_memory_bank.save_memory")
    def test_governed_runtime_executes_sanitization_evidence_and_memory_sync(
        self, mock_save_memory, mock_publish, mock_save_evidence, mock_sanitize, mock_cloud_log
    ):
        mock_sanitize.side_effect = lambda proj, text, mode: (f"sanitized_{text}", False)
        mock_cloud_log.return_value = {"ok": True, "log_name": "inneros-gemini-runtime"}
        mock_publish.return_value = {"ok": True, "message_id": "msg_test", "topic": "inneros-events"}
        mock_save_memory.return_value = {"ok": True, "document_id": "mem_test"}
        mock_save_evidence.return_value = {"ok": True, "document_id": "ev_test"}

        result = self.runtime.run(
            prompt="Hello World",
            correlation_id="corr-123",
            tools=[],
            allow_external=True
        )

        self.assertTrue(result["ok"])
        # Check sanitization was called on input
        mock_sanitize.assert_any_call("test-proj", "Hello World", mode="prompt")
        # Check sanitization was called on output
        mock_sanitize.assert_any_call("test-proj", "ok", mode="response")

        # Check Firestore evidence was saved
        mock_save_evidence.assert_called_once()
        evidence = mock_save_evidence.call_args[0][1]
        self.assertEqual(evidence["correlation_id"], "corr-123")
        self.assertEqual(evidence["interaction_id"], "ix-1")

        # Check Pub/Sub event was published
        mock_publish.assert_called_once()

        # Check Memory Bank was synchronized
        mock_save_memory.assert_called_once_with(
            agent_id="google-gemini-vertex",
            content={
                "prompt": "sanitized_Hello World",
                "output_text": "sanitized_ok",
                "interaction_id": "ix-1",
                "correlation_id": "corr-123",
                "status": "success"
            },
            correlation_id="corr-123"
        )

    @patch("urllib.request.urlopen")
    @patch("google.auth.default")
    def test_model_armor_sanitization_detects_blocks(self, mock_auth, mock_urlopen):
        mock_auth.return_value = (MagicMock(), "test-proj")

        # Mock Model Armor response indicating MATCH_FOUND (Blocked)
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"sanitizationResult": {"filterMatchState": "MATCH_FOUND", "userPromptData": {"text": "blocked_input"}}}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Calling sanitization should return the sanitized version or raise error
        res = gr._sanitize_with_model_armor("test-proj", "jailbreak_text", mode="prompt")
        self.assertEqual(res, ("blocked_input", False))

    @patch("urllib.request.urlopen")
    @patch("google.auth.default")
    @patch.dict("os.environ", {"INNEROS_GEMINI_SECURITY_REQUIRED": "yes"})
    def test_model_armor_security_required_fails_closed(self, mock_auth, mock_urlopen):
        mock_auth.return_value = (MagicMock(), "test-proj")
        mock_urlopen.side_effect = Exception("Network Down")

        with self.assertRaises(ValueError):
            gr._sanitize_with_model_armor("test-proj", "jailbreak_text", mode="prompt")

    @patch.dict("os.environ", {"INNEROS_GEMINI_CLOUD_REQUIRED": "yes"})
    def test_cloud_required_fails_without_cloud(self):
        self.fake.interactions.create.side_effect = Exception("No cloud access")
        with self.assertRaises(gr.GeminiRuntimeError):
            self.client.create_interaction(prompt="Hello")

if __name__ == "__main__":
    unittest.main()
