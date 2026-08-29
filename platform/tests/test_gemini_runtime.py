import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inneros_core_runtime import gemini_runtime as gr


class FakeInteraction:
    def __init__(self, interaction_id="ix-1", output_text="ok", steps=None):
        self.id = interaction_id
        self.output_text = output_text
        self.steps = steps or []


class FakeInteractions:
    def __init__(self):
        self.calls = []
        self.responses = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
        return FakeInteraction()


class FakeGenAIClient:
    def __init__(self):
        self.interactions = FakeInteractions()


class GeminiRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.config = gr.GeminiRuntimeConfig(
            project_id="innerops-agentic-platform",
            model="gemini-3.5-flash",
            model_location="global",
            agent_location="us-central1",
            store_interactions=True,
        )
        self.fake = FakeGenAIClient()
        self.client = gr.GeminiInteractionsClient(config=self.config, client=self.fake)

    def test_default_config_matches_hackathon_model_and_split_locations(self):
        with patch.dict("os.environ", {}, clear=True):
            cfg = gr.GeminiRuntimeConfig.from_env()
        self.assertEqual(cfg.project_id, "innerops-agentic-platform")
        self.assertEqual(cfg.model, "gemini-3.5-flash")
        self.assertEqual(cfg.model_location, "global")
        self.assertEqual(cfg.agent_location, "us-central1")

    def test_tool_spec_uses_interactions_function_schema(self):
        tool = gr.ToolSpec(
            name="get_task_status",
            description="Read one bounded task status",
            parameters={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        )
        payload = tool.as_interactions_tool()
        self.assertEqual(payload["type"], "function")
        self.assertEqual(payload["name"], "get_task_status")
        self.assertEqual(payload["parameters"]["required"], ["task_id"])

    def test_create_interaction_passes_model_tools_and_store(self):
        self.fake.interactions.responses.append(
            FakeInteraction(
                interaction_id="ix-tool",
                output_text="",
                steps=[
                    {
                        "type": "function_call",
                        "name": "get_task_status",
                        "call_id": "call-1",
                        "arguments": {"task_id": "ops-1"},
                    }
                ],
            )
        )
        tool = gr.ToolSpec(
            name="get_task_status",
            description="Read one bounded task status",
            parameters={"type": "object", "properties": {"task_id": {"type": "string"}}},
        )
        result = self.client.create_interaction(prompt="Check ops-1", tools=[tool])
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "gemini-3.5-flash")
        self.assertEqual(result["interaction_id"], "ix-tool")
        self.assertEqual(len(result["function_calls"]), 1)
        call = self.fake.interactions.calls[0]
        self.assertEqual(call["model"], "gemini-3.5-flash")
        self.assertTrue(call["store"])
        self.assertEqual(call["tools"][0]["name"], "get_task_status")

    def test_continue_with_tool_result_preserves_interaction_chain(self):
        self.fake.interactions.responses.append(FakeInteraction(interaction_id="ix-2", output_text="verified"))
        result = self.client.continue_with_tool_result(
            previous_interaction_id="ix-1",
            call_id="call-1",
            tool_name="get_task_status",
            result={"status": "accepted"},
            tools=[],
        )
        self.assertTrue(result["ok"])
        call = self.fake.interactions.calls[0]
        self.assertEqual(call["previous_interaction_id"], "ix-1")
        self.assertEqual(call["input"][0]["type"], "function_result")
        self.assertEqual(call["input"][0]["call_id"], "call-1")
        self.assertEqual(call["input"][0]["name"], "get_task_status")

    def test_runtime_requires_explicit_external_authorization(self):
        runtime = gr.InnerOSGeminiRuntime(client=self.client)
        result = runtime.run(
            prompt="Inspect task",
            correlation_id="corr-1",
            tools=[],
            allow_external=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "external_execution_not_authorized")
        self.assertEqual(self.fake.interactions.calls, [])

    def test_runtime_emits_correlation_and_bounded_tool_evidence(self):
        self.fake.interactions.responses.append(
            FakeInteraction(
                interaction_id="ix-3",
                steps=[
                    {
                        "type": "function_call",
                        "name": "read_signal",
                        "call_id": "call-7",
                        "arguments": {"signal_id": "mail-1"},
                    }
                ],
            )
        )
        evidence = []
        runtime = gr.InnerOSGeminiRuntime(client=self.client, evidence_sink=evidence.append)
        tool = gr.ToolSpec(
            name="read_signal",
            description="Read a sanitized strategic signal",
            parameters={"type": "object", "properties": {"signal_id": {"type": "string"}}},
            risk_level="low",
        )
        result = runtime.run(
            prompt="Determine why mail-1 matters",
            correlation_id="hackathon-demo-1",
            tools=[tool],
            allow_external=True,
            context={"project_id": "innerops-agentic-platform", "deadline": "2026-08-31"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["correlation_id"], "hackathon-demo-1")
        self.assertEqual(evidence[0]["interaction_id"], "ix-3")
        self.assertEqual(evidence[0]["requested_tools"], ["read_signal"])
        self.assertEqual(evidence[0]["requested_tool_risks"]["read_signal"], "low")
        self.assertFalse(evidence[0]["verified"])

    def test_resource_documents_make_gemini_discoverable_without_replacing_local_first(self):
        provider = gr.resource_provider_document()
        model = gr.model_provider_document()
        self.assertEqual(provider["provider_id"], "google-gemini-vertex")
        self.assertFalse(provider["local_first"])
        self.assertEqual(provider["cost_policy"], "strategic_cloud")
        self.assertEqual(model["model_ref"], "gemini-3.5-flash")
        self.assertIn("agentic_workflow", model["task_classes"])

    def test_invalid_or_duplicate_tools_are_rejected_before_model_call(self):
        tool = gr.ToolSpec(name="same", description="one", parameters={"type": "object"})
        with self.assertRaises(gr.GeminiRuntimeError) as ctx:
            gr.validate_tool_specs([tool, tool])
        self.assertEqual(ctx.exception.code, "invalid_tool_name")


if __name__ == "__main__":
    unittest.main()
