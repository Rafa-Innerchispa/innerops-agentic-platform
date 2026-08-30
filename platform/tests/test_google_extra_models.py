"""Tests for governed Google AI model lanes."""
from __future__ import annotations

import unittest
from unittest.mock import patch, Mock

from inneros_core_runtime import google_extra_models, resource_fabric


class FakeTextResponse:
    text = "ok"


class FakeEmbeddingResponse:
    embeddings = [type("Embedding", (), {"values": [0.1, 0.2, 0.3]})()]


class FakeModels:
    def generate_content(self, **kwargs):
        self.last_generate = kwargs
        return FakeTextResponse()

    def embed_content(self, **kwargs):
        self.last_embed = kwargs
        return FakeEmbeddingResponse()


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


class GoogleExtraModelsTests(unittest.TestCase):
    def test_allowlist_has_bounded_models_and_limits(self) -> None:
        data = google_extra_models.allowlist()
        self.assertTrue(data["ok"])
        self.assertIn("gemini-2.5-flash-lite", data["allowed_models"])
        self.assertIn("gemini-3.5-flash-lite", data["allowed_models"])
        self.assertIn("gemini-embedding-001", data["allowed_models"])
        self.assertEqual(data["lanes"], data["allowed_lanes"])
        self.assertTrue(data["lanes"])
        self.assertLessEqual(data["smoke_limits"]["max_output_tokens"], 32)
        self.assertGreaterEqual(data["gcloud_timeout_seconds"], 30)

    def test_smoke_defaults_to_dry_run(self) -> None:
        result = google_extra_models.smoke_lane("google-flash-lite-triage")
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])

    def test_text_smoke_uses_allowlisted_lane_and_cost_limits(self) -> None:
        with patch.object(google_extra_models, "_client", return_value=FakeClient()):
            result = google_extra_models.smoke_lane(
                "google-flash-lite-triage",
                project_id="innerops-agentic-platform",
                prompt="x" * 2000,
                allow_live=True,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "gemini-2.5-flash-lite")
        self.assertEqual(result["cost_guard"]["prompt_chars"], google_extra_models.SMOKE_MAX_PROMPT_CHARS)
        self.assertEqual(result["cost_guard"]["max_output_tokens"], google_extra_models.SMOKE_MAX_OUTPUT_TOKENS)

    def test_embedding_smoke_reports_dimensions(self) -> None:
        with patch.object(google_extra_models, "_client", return_value=FakeClient()):
            result = google_extra_models.smoke_lane("google-memory-embedding", allow_live=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["modality"], "embedding")
        self.assertEqual(result["embedding_dimensions"], 3)

    def test_resource_fabric_bootstrap_includes_google_model_lanes(self) -> None:
        with patch.object(resource_fabric.digitalocean_amd_provider, "resource_provider_document", return_value={"provider_id": "digitalocean-amd-cloud"}), patch.object(
            resource_fabric.digitalocean_amd_provider, "model_provider_document", return_value={"model_provider": "amd-cloud-burst", "provider_id": "digitalocean-amd-cloud", "task_classes": []}
        ), patch.object(resource_fabric.local_gitlab_plane, "resource_provider_document", return_value={"provider_id": "gitlab"}), patch.object(
            resource_fabric.local_gitlab_plane, "model_provider_document", return_value={"model_provider": "gitlab", "provider_id": "gitlab", "task_classes": []}
        ), patch.object(resource_fabric.local_discord_plane, "resource_provider_document", return_value={"provider_id": "discord"}), patch.object(
            resource_fabric.funding_registry, "get_funding_registry_summary", return_value={"ok": True}
        ):
            result = resource_fabric.bootstrap_global_resource_fabric(dry_run=True)
        models = {row["model_provider"]: row for row in result["models"]}
        providers = {row["provider_id"]: row for row in result["providers"]}
        self.assertIn("google-ai-platform", providers)
        self.assertIn("google-flash-lite-triage", models)
        self.assertIn("google-memory-embedding", models)
        self.assertIn("google-gemini-35-bounded-review", models)
        self.assertTrue(models["google-gemini-35-bounded-review"]["default_enabled"])
        self.assertEqual(models["google-gemini-35-bounded-review"]["preferred_location"], "global")
        self.assertIn("google-gemma-bounded-review", models)
        self.assertFalse(models["google-gemma-bounded-review"]["default_enabled"])

    def test_model_garden_preflight_is_dry_run_by_default(self) -> None:
        result = google_extra_models.model_garden_gemma_preflight()
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertIn("does not deploy", result["note"])

    def test_model_garden_preflight_forces_project_and_billing_project(self) -> None:
        payload = """[
          {
            "name": "publishers/google/models/functiongemma",
            "versionId": "function-gemma-270m",
            "launchStage": "GA",
            "openSourceCategory": "GOOGLE_OWNED_OSS_WITH_GOOGLE_CHECKPOINT",
            "supportedActions": {
              "deploy": {
                "modelDisplayName": "function-gemma-270m",
                "containerSpec": {"predictRoute": "/generate"},
                "dedicatedResources": {
                  "machineSpec": {
                    "machineType": "g2-standard-12",
                    "acceleratorType": "NVIDIA_L4",
                    "acceleratorCount": 1
                  }
                }
              }
            }
          }
        ]"""
        completed = Mock(returncode=0, stdout=payload, stderr="")
        with patch.object(google_extra_models, "_run_gcloud", return_value=completed) as run_gcloud:
            result = google_extra_models.model_garden_gemma_preflight(project_id="innerops-agentic-platform", allow_live=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["deploy_started"])
        self.assertTrue(result["read_only"])
        self.assertTrue(result["models"][0]["can_deploy"])
        self.assertEqual(result["models"][0]["deployment_options"][0]["accelerator_type"], "NVIDIA_L4")
        command = run_gcloud.call_args.args[0]
        self.assertIn("model-garden", command)
        self.assertIn("--format", command)
        self.assertEqual(run_gcloud.call_args.kwargs["project_id"], "innerops-agentic-platform")


if __name__ == "__main__":
    unittest.main()
